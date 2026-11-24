#!/usr/bin/env python3
"""三家 AI 共用繁體中文 Stop Hook（Claude Code、Codex、Antigravity 零相依版本）。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

STRIP = re.compile(
    r'```[\s\S]*?```|`[^`\n]*`|https?://\S+|[A-Za-z]:[\\/][^\s，。]*|[\w.-]+/[\w./-]+|\b[\w-]+\.(?:ts|js|mjs|py|md|json|jsonc|html|css)\b'
)
CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')
LATIN = re.compile(r'[A-Za-z]')
ASK = '【繁中檢查】這段回覆主要是英文。請改用台灣繁體中文重寫給使用者看的內容（專有名詞可附英文對照），再繼續。'


def is_english_heavy(text: str) -> bool:
    body = STRIP.sub(' ', text or '')
    latin = len(LATIN.findall(body))
    cjk = len(CJK.findall(body))
    return latin >= 80 and cjk < latin / 4


def _ag_last_text(transcript_path: str) -> str:
    p = Path(transcript_path)
    if not transcript_path or not p.is_file():
        return ''
    last = ''
    try:
        for ln in p.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and (r.get('role') == 'assistant' or 'assistant' in str(r.get('type', ''))):
                t = r.get('text') or r.get('response') or r.get('content')
                if isinstance(t, str) and t.strip():
                    last = t
    except OSError:
        return ''
    return last


def _is_codex_worker(transcript_path: str) -> bool:
    p = Path(transcript_path)
    if not transcript_path or not p.is_file():
        return False
    try:
        first = p.read_text(encoding='utf-8', errors='replace').splitlines()[0]
        row = json.loads(first)
        src = str(((row.get('payload') or {}) if row.get('type') == 'session_meta' else {}).get('source') or '')
        return src == 'exec' or src.startswith('subagent')
    except Exception:
        return False


def evaluate(data: dict) -> tuple[dict, bool]:
    is_ag = 'conversationId' in data or 'terminationReason' in data
    if data.get('stop_hook_active') or data.get('continuationActive'):
        return {}, is_ag
    if is_ag:
        term = str(data.get('terminationReason') or '')
        if term and term != 'NO_TOOL_CALL':
            return {}, True
        last = _ag_last_text(str(data.get('transcriptPath') or ''))
        if is_english_heavy(last):
            return {'decision': 'continue', 'reason': ASK}, True
        return {}, True

    if _is_codex_worker(str(data.get('transcript_path') or '')):
        return {}, False
    if is_english_heavy(str(data.get('last_assistant_message') or '')):
        return {'decision': 'block', 'reason': ASK}, False
    return {}, False


def main() -> int:
    raw = sys.stdin.buffer.read().decode('utf-8-sig', errors='replace').strip()
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        return 0
    out, is_ag = evaluate(data)
    if out:
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode('utf-8'))
    elif is_ag:
        sys.stdout.buffer.write(b'{}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write(f'zh_guard 例外放行：{exc!r}\n')
        sys.exit(0)
