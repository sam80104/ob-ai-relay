#!/usr/bin/env python3
"""三家 AI 共用 Stop Hook：在文字裡問使用者做決定卻沒給規範選項時，提醒一次（零相依版本）。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ASK_WORDS = re.compile(r'要你決定|請你決定|你來決定|要你選|請你選|回我編號|直接回編號|回覆上面|還沒回的|要你回')
RECOMMEND_MARK = re.compile(r'（推薦）|\(Recommended\)|\(推薦\)|推薦順序|推薦放第一')
CODE_FENCE = re.compile(r'```.*?```', re.S)


def asks_in_text(text: str) -> bool:
    text = CODE_FENCE.sub('', text or '')
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith('>')]
    body = '\n'.join(lines)
    if ASK_WORDS.search(body):
        return True
    return sum(1 for ln in lines if ln.rstrip().endswith('？')) >= 2


def _claude_used_ask(transcript_path: str) -> bool:
    p = Path(transcript_path)
    if not transcript_path or not p.is_file():
        return False
    try:
        rows = [json.loads(ln) for ln in p.read_text(encoding='utf-8', errors='replace').splitlines() if ln.strip()]
    except Exception:
        return False
    start = 0
    for i in range(len(rows) - 1, -1, -1):
        r = rows[i]
        if isinstance(r, dict) and r.get('type') == 'user' and not r.get('isMeta'):
            start = i
            break
    for r in rows[start:]:
        content = ((r.get('message') or {}) if isinstance(r, dict) else {}).get('content')
        if isinstance(content, list):
            if any(isinstance(x, dict) and x.get('type') == 'tool_use'
                   and x.get('name') in ('AskUserQuestion', 'ask_question') for x in content):
                return True
    return False


def _ag_turn_info(transcript_path: str) -> tuple[str, bool]:
    p = Path(transcript_path)
    if not transcript_path or not p.is_file():
        return '', False
    last_text = ''
    asked = False
    try:
        rows = [json.loads(ln) for ln in p.read_text(encoding='utf-8', errors='replace').splitlines() if ln.strip()]
        start = 0
        for i in range(len(rows) - 1, -1, -1):
            r = rows[i]
            if isinstance(r, dict) and (r.get('role') == 'user' or r.get('type') in ('user', 'user_input')):
                start = i
                break
        for r in rows[start:]:
            if 'ask_question' in json.dumps(r, ensure_ascii=False):
                asked = True
            if isinstance(r, dict):
                txt = r.get('text') or r.get('response') or r.get('content')
                if isinstance(txt, str) and txt.strip() and (r.get('role') == 'assistant' or 'assistant' in str(r.get('type', ''))):
                    last_text = txt
    except Exception:
        return '', False
    return last_text, asked


def _codex_info(transcript_path: str) -> tuple[bool, bool]:
    """回傳 (是否為派工 worker, 本輪是否已呼叫互動提問工具)。"""
    p = Path(transcript_path)
    if not transcript_path or not p.is_file():
        return False, False
    try:
        rows = [json.loads(ln) for ln in p.read_text(encoding='utf-8', errors='replace').splitlines() if ln.strip()]
    except Exception:
        return False, False
    is_codex = False
    is_worker = False
    for r in rows[:3]:
        if isinstance(r, dict) and r.get('type') == 'session_meta':
            is_codex = True
            src = str((r.get('payload') or {}).get('source') or '')
            is_worker = src == 'exec' or src.startswith('subagent')
            break
    if not is_codex:
        return False, False
    if is_worker:
        return True, True
    for r in reversed(rows):
        if not isinstance(r, dict):
            continue
        pl = r.get('payload') or {}
        if r.get('type') == 'event_msg' and pl.get('type') == 'item_completed' and (pl.get('item') or {}).get('type') == 'UserMessage':
            break
        if r.get('type') == 'response_item' and pl.get('name') in ('request_user_input', 'AskUserQuestion', 'ask_question'):
            return True, True
    return True, False


def evaluate(data: dict, tool_arg: str = '') -> tuple[dict, bool]:
    is_ag = tool_arg == 'ag' or 'conversationId' in data or 'terminationReason' in data
    if data.get('stop_hook_active') or data.get('continuationActive'):
        return {}, is_ag
    term = str(data.get('terminationReason') or '')
    if is_ag and term and term != 'NO_TOOL_CALL':
        return {}, is_ag

    if is_ag:
        last, asked = _ag_turn_info(str(data.get('transcriptPath') or ''))
        if asked or not asks_in_text(last):
            return {}, True
        return {
            'decision': 'continue',
            'reason': (
                '【選項題】回覆在文字裡問使用者做決定，本輪沒呼叫 ask_question。'
                '改用 ask_question：先寫完整背景（哪件事、現況、為什麼要選），選項依推薦順序排列、'
                '第一項標 (Recommended) 並寫出原因與代價。'
            ),
        }, True

    last = str(data.get('last_assistant_message') or '')
    if not asks_in_text(last):
        return {}, False

    tp = str(data.get('transcript_path') or '')
    is_codex, codex_skip = _codex_info(tp)
    if tool_arg == 'codex' or is_codex:
        if codex_skip or RECOMMEND_MARK.search(last):
            return {}, False
        return {
            'decision': 'block',
            'reason': (
                '【選項題】回覆裡請使用者做決定，但未提供「完整前因後果＋推薦排序選項」。'
                '請先寫背景（哪件事、現況、為何要選），再用條列依推薦順序排出選項，'
                '首項標「（推薦）」並寫清每個選項的原因與代價。'
            ),
        }, False

    if _claude_used_ask(tp):
        return {}, False
    return {
        'decision': 'block',
        'reason': (
            '【選項題】回覆在文字裡問使用者做決定，本輪沒用 AskUserQuestion。改用 AskUserQuestion：'
            '先寫完整背景（哪件事、現況、為何要選），選項依推薦順序排列、首項標（推薦）並寫出原因與代價。'
        ),
    }, False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tool_arg = ''
    if '--tool' in argv:
        idx = argv.index('--tool')
        if idx + 1 < len(argv):
            tool_arg = argv[idx + 1].strip().lower()
    raw = sys.stdin.buffer.read().decode('utf-8-sig', errors='replace').strip()
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        return 0
    out, is_ag = evaluate(data, tool_arg=tool_arg)
    if out:
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode('utf-8'))
    elif is_ag:
        sys.stdout.buffer.write(b'{}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write(f'ask_options_guard 例外放行：{exc!r}\n')
        sys.exit(0)
