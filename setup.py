#!/usr/bin/env python3
"""ob-ai-relay 一鍵安裝與體檢腳本（零第三方相依，支援 Windows／macOS／Linux）。

用法：
  python setup.py init "<Obsidian Vault 路徑>" [--tools claude,codex,ag] [--codex-global] [--force] [--dry-run]
  python setup.py doctor "<Obsidian Vault 路徑>"
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'template'
SUPPORTED_TOOLS = ('claude', 'codex', 'ag')
SKILLS = ('daily-start', 'daily-wrap', 'decision-options')
MARKER = '.ai/hooks/'


def python_exe() -> str:
    exe = Path(sys.executable).resolve()
    s = exe.as_posix()
    return f'"{s}"' if ' ' in s else s


def hook_cmd(rel_script: str, extra: str = '') -> str:
    base = f'{python_exe()} "{rel_script}"' if ' ' in rel_script else f'{python_exe()} {rel_script}'
    return f'{base} {extra}'.strip()


def claude_hook_cmd(rel_script: str, extra: str = '') -> str:
    p = f'"${{CLAUDE_PROJECT_DIR}}/{rel_script}"'
    return f'{python_exe()} {p} {extra}'.strip()


def load_json_safe(path: Path) -> dict:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding='utf-8-sig').strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def write_json_with_backup(path: Path, data: dict, dry_run: bool) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if path.is_file():
        cur = path.read_text(encoding='utf-8-sig')
        if cur.replace('\r\n', '\n') == content:
            return
        if not dry_run:
            bak = path.with_suffix(path.suffix + '.bak')
            if not bak.exists():
                shutil.copy2(path, bak)
    if dry_run:
        print(f'[dry-run] 寫入 JSON：{path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _is_ours(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get('hooks')
    if not isinstance(hooks, list):
        return False
    return any(isinstance(h, dict) and MARKER in str(h.get('command', '')) for h in hooks)


def configure_claude(vault: Path, dry_run: bool) -> None:
    cfg_path = vault / '.claude' / 'settings.json'
    cfg = load_json_safe(cfg_path)
    hooks = cfg.get('hooks') if isinstance(cfg.get('hooks'), dict) else {}

    ss = [e for e in (hooks.get('SessionStart') or []) if not _is_ours(e)]
    ss.append({
        'matcher': 'startup|clear',
        'hooks': [{'type': 'command', 'command': claude_hook_cmd('.ai/hooks/session_brief.py'), 'timeout': 10}],
    })
    hooks['SessionStart'] = ss

    st = [e for e in (hooks.get('Stop') or []) if not _is_ours(e)]
    st.append({
        'matcher': '',
        'hooks': [
            {'type': 'command', 'command': claude_hook_cmd('.ai/hooks/zh_guard.py'), 'timeout': 10},
            {'type': 'command', 'command': claude_hook_cmd('.ai/hooks/ask_options_guard.py', '--tool claude'), 'timeout': 15},
            {'type': 'command', 'command': claude_hook_cmd('.ai/hooks/live_handoff.py', 'stop --tool claude'), 'timeout': 15},
        ],
    })
    hooks['Stop'] = st
    cfg['hooks'] = hooks
    write_json_with_backup(cfg_path, cfg, dry_run)


def configure_ag(vault: Path, dry_run: bool) -> None:
    cfg_path = vault / '.agents' / 'hooks.json'
    cfg = load_json_safe(cfg_path)
    cfg['ob-ai-relay'] = {
        'SessionStart': [
            {'type': 'command', 'command': hook_cmd('.ai/hooks/session_brief.py', '--format ag'), 'timeout': 10},
        ],
        'Stop': [
            {'type': 'command', 'command': hook_cmd('.ai/hooks/zh_guard.py'), 'timeout': 10},
            {'type': 'command', 'command': hook_cmd('.ai/hooks/ask_options_guard.py', '--tool ag'), 'timeout': 15},
            {'type': 'command', 'command': hook_cmd('.ai/hooks/live_handoff.py', 'stop --tool ag'), 'timeout': 15},
        ],
    }
    write_json_with_backup(cfg_path, cfg, dry_run)


def configure_codex(vault: Path, codex_global: bool, dry_run: bool) -> None:
    brief = (vault / '.ai' / 'hooks' / 'session_brief.py').resolve().as_posix()
    zh = (vault / '.ai' / 'hooks' / 'zh_guard.py').resolve().as_posix()
    ask = (vault / '.ai' / 'hooks' / 'ask_options_guard.py').resolve().as_posix()
    lh = (vault / '.ai' / 'hooks' / 'live_handoff.py').resolve().as_posix()

    sample_entry_ss = {
        'hooks': [{'type': 'command', 'command': hook_cmd(brief, '--format codex'), 'timeout': 10}],
    }
    sample_entry_stop = {
        'hooks': [
            {'type': 'command', 'command': hook_cmd(zh), 'timeout': 10},
            {'type': 'command', 'command': hook_cmd(ask, '--tool codex'), 'timeout': 15},
            {'type': 'command', 'command': hook_cmd(lh, 'stop --tool codex'), 'timeout': 15},
        ],
    }

    sample_path = vault / '.ai' / 'codex-hooks.sample.json'
    write_json_with_backup(
        sample_path,
        {
            'description': 'ob-ai-relay Codex hooks 範本（含實際絕對路徑）',
            'hooks': {'SessionStart': [sample_entry_ss], 'Stop': [sample_entry_stop]},
        },
        dry_run,
    )

    if codex_global:
        global_path = Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex')) / 'hooks.json'
        cfg = load_json_safe(global_path)
        hooks = cfg.get('hooks') if isinstance(cfg.get('hooks'), dict) else {}
        ss = [e for e in (hooks.get('SessionStart') or []) if not _is_ours(e)]
        ss.append(sample_entry_ss)
        st = [e for e in (hooks.get('Stop') or []) if not _is_ours(e)]
        st.append(sample_entry_stop)
        hooks['SessionStart'] = ss
        hooks['Stop'] = st
        cfg['hooks'] = hooks
        write_json_with_backup(global_path, cfg, dry_run)


def sync_skills(vault: Path, force: bool, dry_run: bool) -> None:
    src_skills = TEMPLATE / '.ai' / 'skills'
    for target_root in (vault / '.agents' / 'skills', vault / '.claude' / 'skills'):
        for skill in SKILLS:
            src = src_skills / skill / 'SKILL.md'
            dst = target_root / skill / 'SKILL.md'
            if dst.exists() and not force:
                continue
            if dry_run:
                print(f'[dry-run] 同步 skill：{dst}')
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def cmd_init(vault: Path, tools: list[str], codex_global: bool, force: bool, dry_run: bool) -> int:
    if sys.version_info < (3, 10):
        print('錯誤：需要 Python 3.10 以上版本。', file=sys.stderr)
        return 1
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    for src in sorted(TEMPLATE.rglob('*')):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATE)
        dst = vault / rel
        if dst.exists() and not force:
            skipped += 1
            continue
        copied += 1
        if dry_run:
            print(f'[dry-run] 複製：{rel.as_posix()}')
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    if 'claude' in tools:
        configure_claude(vault, dry_run)
    if 'ag' in tools:
        configure_ag(vault, dry_run)
    if 'codex' in tools:
        configure_codex(vault, codex_global, dry_run)

    sync_skills(vault, force=force, dry_run=dry_run)

    # 讓 handoff-live.md 的時間戳略晚於剛複製出的模板檔，避免首次純問答誤觸 Stop 提醒
    live_file = vault / '.ai' / 'logs' / 'handoff-live.md'
    if not dry_run and live_file.is_file():
        now = time.time() + 1.0
        os.utime(live_file, (now, now))

    mode = '（預覽）' if dry_run else ''
    print(f'ob-ai-relay 安裝完成{mode}：目標 {vault}')
    print(f'- 複製檔案：{copied}、保留既有：{skipped}')
    print(f'- 啟用工具：{", ".join(tools)}' + ('（含 ~/.codex/hooks.json）' if ('codex' in tools and codex_global) else ''))
    return 0


def cmd_doctor(vault: Path) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(('Python >= 3.10', sys.version_info >= (3, 10), sys.version.split()[0]))

    required_files = [
        ('共用規則 AGENTS.md', vault / 'AGENTS.md'),
        ('任務看板 任務看板.base', vault / '任務系統' / '任務看板.base'),
        ('任務 CLI tasks.py', vault / '.ai' / 'scripts' / 'tasks.py'),
        ('即時交接 live_handoff.py', vault / '.ai' / 'hooks' / 'live_handoff.py'),
        ('早報腳本 session_brief.py', vault / '.ai' / 'hooks' / 'session_brief.py'),
        ('選項護欄 ask_options_guard.py', vault / '.ai' / 'hooks' / 'ask_options_guard.py'),
        ('繁中護欄 zh_guard.py', vault / '.ai' / 'hooks' / 'zh_guard.py'),
        ('Claude 設定 .claude/settings.json', vault / '.claude' / 'settings.json'),
        ('AG Hooks .agents/hooks.json', vault / '.agents' / 'hooks.json'),
        ('Codex Hooks 範本', vault / '.ai' / 'codex-hooks.sample.json'),
    ]
    for label, path in required_files:
        checks.append((label, path.is_file(), str(path.relative_to(vault)) if path.exists() else '缺少檔案'))

    for skill in SKILLS:
        p_ag = vault / '.agents' / 'skills' / skill / 'SKILL.md'
        p_cl = vault / '.claude' / 'skills' / skill / 'SKILL.md'
        checks.append((f'Skill {skill}', p_ag.is_file() and p_cl.is_file(), '.agents & .claude'))

    # 實跑早報與 stray 檢查
    brief_script = vault / '.ai' / 'hooks' / 'session_brief.py'
    if brief_script.is_file():
        r = subprocess.run(
            [sys.executable, '-X', 'utf8', str(brief_script), '--selftest', '--vault', str(vault)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
        )
        checks.append(('早報執行測試', r.returncode == 0 and '早報' in r.stdout, f'rc={r.returncode}'))

    tasks_script = vault / '.ai' / 'scripts' / 'tasks.py'
    if tasks_script.is_file():
        r = subprocess.run(
            [sys.executable, '-X', 'utf8', str(tasks_script), '--vault', str(vault), 'stray'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
        )
        checks.append(('唯一正本 stray 檢查', r.returncode == 0, r.stdout.strip() or r.stderr.strip()))

    failed = 0
    for label, ok, detail in checks:
        tag = '[OK]' if ok else '[FAIL]'
        if not ok:
            failed += 1
        print(f'{tag} {label}：{detail}')
    print(f'體檢結果：{"全部通過" if failed == 0 else f"有 {failed} 項未通過"}')
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='ob-ai-relay 安裝與體檢工具')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_init = sub.add_parser('init', help='將 ob-ai-relay 安裝進指定 Obsidian Vault')
    p_init.add_argument('vault', type=Path, help='Obsidian Vault 路徑')
    p_init.add_argument('--tools', default='claude,codex,ag', help='逗號分隔：claude,codex,ag')
    p_init.add_argument('--codex-global', action='store_true', help='一併寫入 ~/.codex/hooks.json（會先備份）')
    p_init.add_argument('--force', action='store_true', help='覆蓋已存在的同名檔案')
    p_init.add_argument('--dry-run', action='store_true', help='只預覽不寫檔')

    p_doc = sub.add_parser('doctor', help='檢查 Vault 的 ob-ai-relay 安裝與健康狀態')
    p_doc.add_argument('vault', type=Path, help='Obsidian Vault 路徑')

    args = parser.parse_args(argv)
    if args.cmd == 'init':
        tools = [t.strip().lower() for t in args.tools.split(',') if t.strip()]
        invalid = [t for t in tools if t not in SUPPORTED_TOOLS]
        if invalid:
            parser.error('不支援的工具名稱：' + ', '.join(invalid))
        return cmd_init(args.vault.resolve(), tools, args.codex_global, args.force, args.dry_run)
    return cmd_doctor(args.vault.resolve())


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8')
    sys.exit(main())
