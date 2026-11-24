#!/usr/bin/env python3
"""ob-ai-relay 零相依任務卡 CLI（OB 任務卡唯一正本管理）。

用法：
  python .ai/scripts/tasks.py list [--status 今天] [--owner 我]
  python .ai/scripts/tasks.py new "標題" [--project 個人事務] [--owner 我] [--status 今天] [--priority 2] [--due YYYY-MM-DD] [--next "第一步"]
  python .ai/scripts/tasks.py card "關鍵字" --status 完成|取消|今天|明天|本週|等別人|之後 [--next "..."] [--due YYYY-MM-DD]
  python .ai/scripts/tasks.py stray
  python .ai/scripts/tasks.py snapshot --kind am|pm
  python .ai/scripts/tasks.py wrap-draft [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

CLOSED = ('完成', '已完成', '取消', '已封存')
STRAY_SKIP = ('/任務卡/', '/模板/', '/封存/', '/.obsidian/', '/.ai/', '/.git/')
STRAY_RE = re.compile(r'^\s*(?:[-*]|\d+\.)\s+\[ \]\s+\S', re.M)
WEIGHTS = {'1': 3, '2': 2, '3': 1}


def find_vault(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    here = Path(__file__).resolve()
    # 預設路徑：<vault>/.ai/scripts/tasks.py
    candidate = here.parents[2]
    if (candidate / '任務系統').is_dir() or (candidate / 'AGENTS.md').is_file():
        return candidate
    cur = Path.cwd().resolve()
    for p in (cur, *cur.parents):
        if (p / '任務系統').is_dir() and (p / '.ai').is_dir():
            return p
    return candidate


def parse_frontmatter(text: str) -> dict[str, str]:
    if text.startswith('\ufeff'):
        text = text[1:]
    lines = text.replace('\r\n', '\n').split('\n')
    if not lines or lines[0].strip() != '---':
        return {}
    out: dict[str, str] = {}
    for ln in lines[1:]:
        if ln.strip() == '---':
            return out
        m = re.match(r'^([A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*)\s*:\s*(.*)$', ln)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            out[m.group(1)] = v
    return {}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.tasks-')
    os.close(fd)
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def update_frontmatter(path: Path, updates: dict[str, str]) -> bool:
    text = path.read_text(encoding='utf-8-sig')
    if not text.startswith('---'):
        return False
    m = re.search(r'\r?\n---[ \t]*(\r?\n|$)', text[3:])
    if not m:
        return False
    nl = '\r\n' if '\r\n' in text else '\n'
    fm_lines = text[3:3 + m.start()].splitlines()
    rest = text[3 + m.end():]
    seen: set[str] = set()
    new_lines: list[str] = []
    changed = False
    for line in fm_lines:
        if ':' in line and not line.lstrip().startswith('#'):
            key = line.split(':', 1)[0].strip()
            if key in updates:
                seen.add(key)
                desired = f'{key}: {updates[key]}'
                if line.strip() != desired.strip():
                    changed = True
                new_lines.append(desired)
                continue
        new_lines.append(line)
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f'{k}: {v}')
            changed = True
    if not changed:
        return False
    atomic_write(path, '---' + nl + nl.join(new_lines) + nl + '---' + nl + rest)
    return True


def load_cards(vault: Path) -> list[dict]:
    root = vault / '任務系統' / '專案'
    if not root.is_dir():
        return []
    cards: list[dict] = []
    for p in sorted(root.rglob('*.md')):
        if '任務卡' not in p.parts:
            continue
        try:
            fm = parse_frontmatter(p.read_text(encoding='utf-8-sig', errors='replace'))
        except OSError:
            continue
        if fm.get('type') != '任務卡':
            continue
        cards.append({
            'title': p.stem,
            'path': p,
            'rel': p.relative_to(vault).as_posix(),
            'project': fm.get('project') or p.parent.parent.name,
            'status': fm.get('status', ''),
            'owner': fm.get('owner', '我'),
            'priority': fm.get('priority', '2'),
            'due': fm.get('due', ''),
            'next': fm.get('next', ''),
        })
    return cards


def ob_link(vault: Path, card: dict) -> str:
    rel = Path(card['path']).relative_to(vault).with_suffix('').as_posix()
    return f'[{card["title"]}](obsidian://open?vault={quote(vault.name)}&file={quote(rel)})'


def safe_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#\[\]]+', ' ', title)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return (cleaned[:60] or '新任務').strip()


def cmd_list(vault: Path, status: str | None, owner: str | None, include_closed: bool) -> int:
    cards = load_cards(vault)
    rows = []
    for c in cards:
        if not include_closed and c['status'] in CLOSED:
            continue
        if status and c['status'] != status:
            continue
        if owner and c['owner'] != owner:
            continue
        rows.append(c)
    if not rows:
        print('沒有符合條件的任務卡。')
        return 0
    for c in rows:
        due = f'｜期限 {c["due"]}' if c['due'] else ''
        nxt = f'｜下一步：{c["next"]}' if c['next'] else ''
        print(f'- [{c["status"] or "未設"}] {c["title"]}（{c["project"]}／{c["owner"]}{due}）{nxt}')
    return 0


def cmd_new(
    vault: Path,
    title: str,
    project: str,
    owner: str,
    status: str,
    priority: int,
    due: str,
    nxt: str,
) -> int:
    proj_dir = vault / '任務系統' / '專案' / project
    cards_dir = proj_dir / '任務卡'
    cards_dir.mkdir(parents=True, exist_ok=True)
    readme = proj_dir / 'README.md'
    if not readme.exists():
        atomic_write(
            readme,
            '\n'.join([
                '---',
                '卡別: 專案卡',
                f'名稱: {project}',
                'status: 進行中',
                '現況: 建立中',
                '截止:',
                '---',
                '',
                f'# {project}',
                '',
                '![[任務看板.base#本案]]',
                '',
            ]),
        )
    base = safe_filename(title)
    target = cards_dir / f'{base}.md'
    idx = 2
    while target.exists():
        target = cards_dir / f'{base} ({idx}).md'
        idx += 1
    today = dt.date.today().isoformat()
    nxt_clean = (nxt or '寫下 2 分鐘能開始的第一步').replace('"', "'")
    lines = [
        '---',
        'type: 任務卡',
        f'status: {status}',
        f'owner: {owner}',
        f'project: {project}',
        f'priority: {priority}',
        f'due: {due}',
        f'next: "{nxt_clean}"',
        f'created: {today}',
        '---',
        '',
        f'- **要做什麼**：{title}',
        f'- **下一步**：{nxt_clean}',
        f'- **期限**：{due or "未設定"}',
        '',
        f'# {title}',
        '',
        '## 進度紀錄',
        '',
    ]
    atomic_write(target, '\n'.join(lines))
    print(f'已建立任務卡：{target.relative_to(vault).as_posix()}')
    return 0


def cmd_card(vault: Path, keyword: str, status: str | None, nxt: str | None, due: str | None) -> int:
    cards = load_cards(vault)
    matches = [c for c in cards if keyword.lower() in c['title'].lower() or keyword.lower() in c['rel'].lower()]
    if not matches:
        print(f'找不到包含「{keyword}」的任務卡。', file=sys.stderr)
        return 1
    if len(matches) > 1:
        exact = [c for c in matches if c['title'].lower() == keyword.lower()]
        if len(exact) == 1:
            matches = exact
        else:
            print(f'命中多張卡片，請給更精確關鍵字：', file=sys.stderr)
            for c in matches[:10]:
                print(f'  - {c["rel"]} ({c["status"]})', file=sys.stderr)
            return 1
    target = matches[0]
    updates: dict[str, str] = {}
    if status:
        updates['status'] = status
    if nxt is not None:
        updates['next'] = f'"{nxt.replace(chr(34), chr(39))}"'
    if due is not None:
        updates['due'] = due
    if not updates:
        print('請至少指定 --status、--next 或 --due。', file=sys.stderr)
        return 1
    update_frontmatter(target['path'], updates)
    print(f'已更新：{target["title"]} → {updates}')
    return 0


def find_stray(vault: Path) -> list[tuple[str, int]]:
    base = vault / '任務系統'
    if not base.is_dir():
        return []
    out: list[tuple[str, int]] = []
    for p in sorted(base.rglob('*.md')):
        rel = '/' + p.relative_to(vault).as_posix()
        if any(skip in rel for skip in STRAY_SKIP):
            continue
        try:
            text = p.read_text(encoding='utf-8-sig', errors='replace')
        except OSError:
            continue
        n = len(STRAY_RE.findall(text))
        if n:
            out.append((rel[1:], n))
    return out


def cmd_stray(vault: Path) -> int:
    rows = find_stray(vault)
    if not rows:
        print('任務卡以外沒有未勾選待辦，唯一正本成立。')
        return 0
    print(f'發現 {len(rows)} 頁共 {sum(n for _, n in rows)} 個任務卡以外的未勾選待辦（第二來源）：')
    for rel, n in rows:
        print(f'- {rel}：{n} 筆')
    return 1


def _score(cards: list[dict], today_ids: set[str], current_by_rel: dict[str, dict]) -> tuple[int, int, int]:
    total = len(today_ids)
    done = 0
    w_total = 0
    w_done = 0
    for rel in today_ids:
        cur = current_by_rel.get(rel)
        w = WEIGHTS.get(str((cur or {}).get('priority', '2')), 2)
        w_total += w
        if cur and cur['status'] in ('完成', '已完成'):
            done += 1
            w_done += w
    pct = round(w_done * 100 / w_total) if w_total else 100
    return done, total, pct


def cmd_snapshot(vault: Path, kind: str, date_str: str) -> int:
    cards = load_cards(vault)
    snap_dir = vault / '.ai' / 'logs' / 'snapshots'
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f'{date_str}-{kind}.json'
    today_cards = [
        {
            'rel': c['rel'],
            'title': c['title'],
            'owner': c['owner'],
            'status': c['status'],
            'priority': c['priority'],
            'due': c['due'],
            'next': c['next'],
        }
        for c in cards
        if c['status'] == '今天'
    ]
    payload = {
        'date': date_str,
        'kind': kind,
        'captured_at': dt.datetime.now().isoformat(timespec='seconds'),
        'cards': today_cards,
    }
    atomic_write(snap_path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    mine = [c for c in today_cards if c['owner'] in ('我', '主人', '')]
    ai = [c for c in today_cards if c['owner'] not in ('我', '主人', '')]
    print(f'已寫入 {kind} 快照（{snap_path.relative_to(vault).as_posix()}）：我的今天卡 {len(mine)} 張、AI 今天卡 {len(ai)} 張')
    return 0


def cmd_wrap_draft(vault: Path, date_str: str) -> int:
    cards = load_cards(vault)
    by_rel = {c['rel']: c for c in cards}
    am_path = vault / '.ai' / 'logs' / 'snapshots' / f'{date_str}-am.json'
    am_cards: list[dict] = []
    if am_path.is_file():
        try:
            am_cards = json.loads(am_path.read_text(encoding='utf-8')).get('cards', [])
        except Exception:
            am_cards = []

    my_am = {c['rel'] for c in am_cards if c.get('owner') in ('我', '主人', '')}
    ai_am = {c['rel'] for c in am_cards if c.get('owner') not in ('我', '主人', '')}
    my_done, my_tot, my_pct = _score(cards, my_am, by_rel)
    ai_done, ai_tot, ai_pct = _score(cards, ai_am, by_rel)

    still_today = [c for c in cards if c['status'] == '今天']
    overdue = [c for c in cards if c['due'] and c['due'] < date_str and c['status'] not in CLOSED]
    strays = find_stray(vault)

    lines = [
        f'# 每日收工報告 {date_str}',
        '',
        f'- **我的完成度**：{my_done}/{my_tot}（加權 {my_pct}%）' + ('（今日未存開工快照，請先確認）' if not am_cards else ''),
        f'- **AI 完成度**：{ai_done}/{ai_tot}（加權 {ai_pct}%）',
        f'- **尚未歸零的「今天」卡**：{len(still_today)} 張',
        f'- **逾期任務卡**：{len(overdue)} 張',
        f'- **第二來源待辦（stray）**：{len(strays)} 頁',
        '',
        '## 完成項目',
        '',
    ]
    done_list = [by_rel[r] for r in sorted(my_am | ai_am) if r in by_rel and by_rel[r]['status'] in ('完成', '已完成')]
    if done_list:
        for c in done_list:
            lines.append(f'- {ob_link(vault, c)}')
    else:
        lines.append('- （請補入今日完成項目與成品連結）')

    lines.extend(['', '## 未完成（明天開工自動提醒）', ''])
    unfinished = [by_rel[r] for r in sorted(my_am | ai_am) if r in by_rel and by_rel[r]['status'] not in ('完成', '已完成', '取消')]
    if unfinished:
        for c in unfinished:
            lines.append(f'- {ob_link(vault, c)}：目前 {c["status"]}，下一步：{c["next"] or "待補"}')
    else:
        lines.append('- 無')

    lines.extend([
        '',
        '## 經驗與減法（至多 3 條）',
        '',
        '- （事件、根因、改進位置）',
        '',
        '## 明天第一件',
        '',
        '- **我**：（寫出明天第一件與 2 分鐘第一步）',
        '- **AI**：（寫出可先背景執行的第一件）',
        '',
    ])

    out_path = vault / '.ai' / 'logs' / 'daily' / f'{date_str}.md'
    atomic_write(out_path, '\n'.join(lines))
    print(f'已產生收工草稿：{out_path.relative_to(vault).as_posix()}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='ob-ai-relay 任務卡唯一正本 CLI')
    parser.add_argument('--vault', help='Obsidian Vault 根目錄')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list', help='列出任務卡')
    p_list.add_argument('--status')
    p_list.add_argument('--owner')
    p_list.add_argument('--all', action='store_true', help='包含已完成與取消')

    p_new = sub.add_parser('new', help='建立任務卡')
    p_new.add_argument('title')
    p_new.add_argument('--project', default='個人事務')
    p_new.add_argument('--owner', default='我')
    p_new.add_argument('--status', default='本週')
    p_new.add_argument('--priority', type=int, default=2)
    p_new.add_argument('--due', default='')
    p_new.add_argument('--next', dest='nxt', default='')

    p_card = sub.add_parser('card', help='更新任務卡狀態或下一步')
    p_card.add_argument('keyword')
    p_card.add_argument('--status')
    p_card.add_argument('--next', dest='nxt')
    p_card.add_argument('--due')

    sub.add_parser('stray', help='檢查任務卡以外的第二來源待辦')

    p_snap = sub.add_parser('snapshot', help='儲存 am/pm 開收工快照')
    p_snap.add_argument('--kind', choices=('am', 'pm'), required=True)
    p_snap.add_argument('--date', default=dt.date.today().isoformat())

    p_wrap = sub.add_parser('wrap-draft', help='產生今日收工報告草稿')
    p_wrap.add_argument('--date', default=dt.date.today().isoformat())

    args = parser.parse_args(argv)
    vault = find_vault(args.vault)

    if args.cmd == 'list':
        return cmd_list(vault, args.status, args.owner, args.all)
    if args.cmd == 'new':
        return cmd_new(vault, args.title, args.project, args.owner, args.status, args.priority, args.due, args.nxt)
    if args.cmd == 'card':
        return cmd_card(vault, args.keyword, args.status, args.nxt, args.due)
    if args.cmd == 'stray':
        return cmd_stray(vault)
    if args.cmd == 'snapshot':
        return cmd_snapshot(vault, args.kind, args.date)
    if args.cmd == 'wrap-draft':
        return cmd_wrap_draft(vault, args.date)
    return 0


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8')
    sys.exit(main())
