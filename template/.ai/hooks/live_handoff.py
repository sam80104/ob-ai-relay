#!/usr/bin/env python3
"""跨 AI 即時交接工具與 Stop Hook（Claude Code、Codex、Antigravity 共用，零相依）。

1. `live_handoff.py log --tool <名> --title <題> --done <做> --result <果> --next <下>`
   寫入 `.ai/logs/handoff-live.md`（最多保留 15 筆，最新在最上）。
2. `live_handoff.py stop --tool claude|codex|ag`
   - 純問答未改檔 → 放行。
   - 本輪已寫交接（handoff-live.md 比最新工作檔更新，或 5 分鐘內剛寫過）→ 放行。
   - 無 `.git` 的 Vault 會自動掃描 `任務系統/` 與根目錄 `.md` 的修改時間作為退路。
   - 同對話針對同一批修改只提醒一次，絕不死鎖。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LIVE_REL = Path('.ai/logs/handoff-live.md')
MAX_ENTRIES = 15
RECENT_EDIT_WINDOW_SEC = 20 * 60
FRESH_HANDOFF_SEC = 5 * 60
IGNORE_PREFIXES = ('.ai/', '.obsidian/', '.claude/', '.agents/', '.git/')
HEADER = (
    '# 跨 AI 即時交接（最新在最上，最多保留 15 筆）\n\n'
    '> 由 `.ai/hooks/live_handoff.py` 維護，三家 AI（Claude Code、Codex、Antigravity）開啟對話時自動注入最近 2 筆，說「繼續」即可無縫接手。\n'
)
ENTRY_RE = re.compile(r'(?m)^###\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}（([^）]+)）｜(.+)$')


def find_vault(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / 'AGENTS.md').is_file() or (candidate / '.ai').is_dir():
        return candidate
    return Path.cwd().resolve()


def parse_entries(text: str) -> list[str]:
    matches = list(ENTRY_RE.finditer(text))
    entries: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        entries.append(text[start:end].strip())
    return entries


def recent_summaries(root: Path, limit: int = 2) -> list[str]:
    path = Path(root) / LIVE_REL
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding='utf-8-sig', errors='replace')
    except OSError:
        return []
    out: list[str] = []
    for block in parse_entries(text)[:limit]:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        head = re.sub(r'^\d{4}-(\d{2}-\d{2}\s+\d{2}:\d{2})', r'\1', lines[0].lstrip('# ').strip())
        nxt = ''
        done = ''
        for ln in lines[1:]:
            if ln.startswith('- 下一步：'):
                nxt = ln[len('- 下一步：'):].strip()
            elif ln.startswith('- 做了什麼：'):
                done = ln[len('- 做了什麼：'):].strip()
        tail = f'下一步：{nxt}' if nxt else (f'進度：{done}' if done else '')
        out.append(f'{head}｜{tail}' if tail else head)
    return out


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.handoff-')
    os.close(fd)
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append_entry(
    root: Path,
    tool: str,
    title: str,
    done: str,
    result: str,
    nxt: str,
    when: dt.datetime | None = None,
) -> Path:
    path = Path(root) / LIVE_REL
    stamp = (when or dt.datetime.now().astimezone()).strftime('%Y-%m-%d %H:%M')
    clean = lambda s: re.sub(r'\s+', ' ', (s or '').strip())
    entry = '\n'.join([
        f'### {stamp}（{clean(tool) or "AI"}）｜{clean(title) or "工作交接"}',
        f'- 做了什麼：{clean(done) or "已處理本輪任務"}',
        f'- 結果在哪：{clean(result) or "見修改檔案"}',
        f'- 下一步：{clean(nxt) or "無"}',
    ])
    old_entries = []
    if path.is_file():
        old_entries = parse_entries(path.read_text(encoding='utf-8-sig', errors='replace'))
    merged = [entry] + old_entries[: MAX_ENTRIES - 1]
    atomic_write(path, HEADER + '\n' + '\n\n'.join(merged) + '\n')
    return path


def _recent_modified_work_files(root: Path, now_ts: float) -> tuple[list[str], float]:
    cutoff = now_ts - RECENT_EDIT_WINDOW_SEC
    hit: list[str] = []
    latest_mtime = 0.0

    # 優先使用 git status（有版本控制時最準）；無 git 時掃描工作檔案 mtime
    if (root / '.git').exists():
        try:
            r = subprocess.run(
                ['git', '-C', str(root), 'status', '--porcelain', '-uall'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5,
            )
            if r.returncode == 0:
                for raw in r.stdout.splitlines():
                    if len(raw) < 4:
                        continue
                    rel = raw[3:].strip()
                    if ' -> ' in rel:
                        rel = rel.split(' -> ', 1)[1].strip()
                    rel = rel.strip('"').replace('\\', '/')
                    if not rel or any(rel.startswith(p) for p in IGNORE_PREFIXES):
                        continue
                    try:
                        mt = (root / rel).stat().st_mtime
                    except OSError:
                        continue
                    if mt >= cutoff:
                        hit.append(rel)
                        latest_mtime = max(latest_mtime, mt)
                return hit, latest_mtime
        except Exception:
            pass

    for p in root.rglob('*.md'):
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if any(rel.startswith(pref) for pref in IGNORE_PREFIXES):
            continue
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt >= cutoff:
            hit.append(rel)
            latest_mtime = max(latest_mtime, mt)
    return hit, latest_mtime


def _state_file(session_key: str) -> Path:
    h = hashlib.sha256(session_key.encode('utf-8', 'replace')).hexdigest()[:16]
    d = Path(tempfile.gettempdir()) / 'ob-ai-relay-handoff'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{h}.json'


def _already_reminded(session_key: str, latest_mtime: float) -> bool:
    sf = _state_file(session_key)
    if not sf.is_file():
        return False
    try:
        obj = json.loads(sf.read_text(encoding='utf-8'))
        return float(obj.get('mtime', 0)) >= latest_mtime - 1.0
    except Exception:
        return False


def _mark_reminded(session_key: str, latest_mtime: float) -> None:
    try:
        _state_file(session_key).write_text(
            json.dumps({'mtime': latest_mtime, 'ts': time.time()}), encoding='utf-8'
        )
    except OSError:
        pass


def _is_codex_worker(transcript_path: str) -> bool:
    if not transcript_path or not Path(transcript_path).is_file():
        return False
    try:
        first = Path(transcript_path).read_text(encoding='utf-8', errors='replace').splitlines()[0]
        row = json.loads(first)
        src = str(((row.get('payload') or {}) if row.get('type') == 'session_meta' else {}).get('source') or '')
        return src == 'exec' or src.startswith('subagent')
    except Exception:
        return False


def _detect_tool(arg_tool: str, data: dict) -> str:
    if arg_tool:
        return arg_tool.lower()
    if 'conversationId' in data or 'terminationReason' in data:
        return 'ag'
    return 'claude'


def evaluate_stop(data: dict, tool_arg: str = '', root: Path | None = None, now_ts: float | None = None) -> dict:
    vault = Path(root) if root else find_vault()
    tool = _detect_tool(tool_arg, data)
    now_ts = now_ts if now_ts is not None else time.time()

    if data.get('stop_hook_active') or data.get('continuationActive'):
        return {}
    term_reason = str(data.get('terminationReason') or '')
    if term_reason and term_reason != 'NO_TOOL_CALL':
        return {}
    if tool == 'codex' and _is_codex_worker(str(data.get('transcript_path') or '')):
        return {}

    cwd = str(data.get('cwd') or '')
    if cwd:
        try:
            Path(cwd).resolve().relative_to(vault.resolve())
        except ValueError:
            return {}

    files, latest_mtime = _recent_modified_work_files(vault, now_ts)
    if not files:
        return {}

    live_path = vault / LIVE_REL
    if live_path.is_file():
        try:
            live_mt = live_path.stat().st_mtime
            has_entries = bool(parse_entries(live_path.read_text(encoding='utf-8-sig', errors='replace')))
            if live_mt >= latest_mtime - 1.0 or (has_entries and (now_ts - live_mt) <= FRESH_HANDOFF_SEC):
                return {}
        except OSError:
            pass

    sid = str(data.get('conversationId') or data.get('session_id') or f'{tool}-default')
    if _already_reminded(sid, latest_mtime):
        return {}
    _mark_reminded(sid, latest_mtime)

    tool_label = {'ag': 'Antigravity', 'codex': 'Codex', 'claude': 'Claude Code'}.get(tool, tool)
    sample = '、'.join(files[:3]) + (f' 等 {len(files)} 檔' if len(files) > 3 else '')
    reason = (
        f'【即時交接】偵測到本輪修改了 Vault 檔案（{sample}），但尚未寫入跨 AI 交接紀錄。'
        f'請執行一次以下指令補留三行交接，讓下一家 AI 說「繼續」即可接手：\n'
        f'python .ai/hooks/live_handoff.py log --tool "{tool_label}" '
        f'--title "主題" --done "做了什麼" --result "{files[0]}" --next "下一步"'
    )
    if tool == 'ag':
        return {'decision': 'continue', 'reason': reason}
    return {'decision': 'block', 'reason': reason}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='跨 AI 即時交接紀錄與 Stop Hook')
    sub = parser.add_subparsers(dest='cmd')

    p_log = sub.add_parser('log', help='追加一筆跨 AI 交接紀錄')
    p_log.add_argument('--vault')
    p_log.add_argument('--tool', required=True)
    p_log.add_argument('--title', required=True)
    p_log.add_argument('--done', required=True)
    p_log.add_argument('--result', required=True)
    p_log.add_argument('--next', dest='nxt', required=True)

    p_stop = sub.add_parser('stop', help='Stop Hook 入口')
    p_stop.add_argument('--tool', default='', choices=['', 'claude', 'codex', 'ag'])
    p_stop.add_argument('--vault')

    p_show = sub.add_parser('show', help='顯示最近交接摘要')
    p_show.add_argument('--vault')
    p_show.add_argument('--limit', type=int, default=5)

    args = parser.parse_args(argv)
    if args.cmd == 'log':
        vault = find_vault(args.vault)
        p = append_entry(vault, args.tool, args.title, args.done, args.result, args.nxt)
        print(f'已寫入即時交接：{p}')
        return 0
    if args.cmd == 'show':
        vault = find_vault(args.vault)
        for line in recent_summaries(vault, limit=args.limit):
            print('- ' + line)
        return 0
    if args.cmd == 'stop':
        vault = find_vault(args.vault)
        try:
            raw = sys.stdin.buffer.read().decode('utf-8-sig', errors='replace').strip()
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        out = evaluate_stop(data, tool_arg=args.tool, root=vault)
        if out:
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode('utf-8'))
        elif _detect_tool(args.tool, data) == 'ag':
            sys.stdout.buffer.write(b'{}')
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write(f'live_handoff 例外放行：{exc!r}\n')
        sys.exit(0)
