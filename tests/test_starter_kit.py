import datetime
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
SETUP_PY = KIT_ROOT / 'setup.py'

PRIVATE_TERMS = (
    'Users\\sam80',
    'Users/sam80',
    'C:\\Users\\sam80',
    '誠澄',
    '花千樹',
    '林琮翰',
    '曾文玲',
    '菜鳥救星',
    '命理',
    '郵輪',
    'vault-git',
    'chatgpt-bridge',
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestStarterKit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / 'MyVault'
        self.vault.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_init_and_doctor_on_fresh_vault(self):
        r1 = subprocess.run(
            [sys.executable, '-X', 'utf8', str(SETUP_PY), 'init', str(self.vault)],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        self.assertTrue((self.vault / 'AGENTS.md').is_file())
        self.assertTrue((self.vault / '任務系統' / '任務看板.base').is_file())
        self.assertTrue((self.vault / '.claude' / 'settings.json').is_file())
        self.assertTrue((self.vault / '.agents' / 'hooks.json').is_file())
        self.assertTrue((self.vault / '.ai' / 'codex-hooks.sample.json').is_file())
        for skill in ('daily-start', 'daily-wrap', 'decision-options'):
            self.assertTrue((self.vault / '.agents' / 'skills' / skill / 'SKILL.md').is_file())
            self.assertTrue((self.vault / '.claude' / 'skills' / skill / 'SKILL.md').is_file())

        r2 = subprocess.run(
            [sys.executable, '-X', 'utf8', str(SETUP_PY), 'doctor', str(self.vault)],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn('全部通過', r2.stdout)

    def test_init_never_overwrites_existing_user_files(self):
        custom = '# My Custom Rules\nKeep me untouched.\n'
        (self.vault / 'AGENTS.md').write_text(custom, encoding='utf-8')
        r = subprocess.run(
            [sys.executable, '-X', 'utf8', str(SETUP_PY), 'init', str(self.vault)],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual((self.vault / 'AGENTS.md').read_text(encoding='utf-8'), custom)

    def test_tasks_cli_full_lifecycle(self):
        subprocess.run(
            [sys.executable, '-X', 'utf8', str(SETUP_PY), 'init', str(self.vault)],
            check=True, capture_output=True,
        )
        tasks_py = self.vault / '.ai' / 'scripts' / 'tasks.py'
        run_tasks = lambda *a: subprocess.run(
            [sys.executable, '-X', 'utf8', str(tasks_py), '--vault', str(self.vault), *a],
            capture_output=True, text=True, encoding='utf-8', timeout=20,
        )

        self.assertEqual(run_tasks('new', '寫週報', '--project', '工作', '--owner', '我', '--status', '今天', '--next', '開草稿').returncode, 0)
        self.assertEqual(run_tasks('new', '看合約', '--project', '工作', '--owner', '我', '--status', '今天', '--next', '開 PDF').returncode, 0)
        self.assertEqual(run_tasks('snapshot', '--kind', 'am').returncode, 0)
        self.assertEqual(run_tasks('card', '寫週報', '--status', '完成').returncode, 0)
        self.assertEqual(run_tasks('card', '看合約', '--status', '取消').returncode, 0)

        listed = run_tasks('list')
        self.assertNotIn('寫週報', listed.stdout)
        self.assertNotIn('看合約', listed.stdout)

        # 第二來源待辦檢查
        stray_page = self.vault / '任務系統' / '筆記.md'
        stray_page.write_text('- [ ] 散落待辦\n', encoding='utf-8')
        self.assertEqual(run_tasks('stray').returncode, 1)
        stray_page.unlink()
        self.assertEqual(run_tasks('stray').returncode, 0)

        wrap = run_tasks('wrap-draft')
        self.assertEqual(wrap.returncode, 0)
        today_str = datetime.date.today().isoformat()
        daily = (self.vault / '.ai' / 'logs' / 'daily' / f'{today_str}.md').read_text(encoding='utf-8')
        self.assertIn('寫週報', daily)

    def test_live_handoff_and_session_brief_without_git(self):
        subprocess.run(
            [sys.executable, '-X', 'utf8', str(SETUP_PY), 'init', str(self.vault)],
            check=True, capture_output=True,
        )
        lh = load_module('kit_lh', self.vault / '.ai' / 'hooks' / 'live_handoff.py')
        sb = load_module('kit_sb', self.vault / '.ai' / 'hooks' / 'session_brief.py')

        # 剛初始化後純問答不誤觸
        self.assertEqual(lh.evaluate_stop({'conversationId': 'c0', 'terminationReason': 'NO_TOOL_CALL'}, 'ag', self.vault), {})

        # 修改工作檔（無 git 目錄退路）後未寫交接，觸發一次提醒
        note = self.vault / '任務系統' / '專案' / '範例專案' / '筆記.md'
        note.write_text('updated\n', encoding='utf-8')
        now = time.time() + 10
        os.utime(note, (now, now))

        sid = f'ag-{time.time_ns()}'
        out_ag = lh.evaluate_stop({'conversationId': sid, 'terminationReason': 'NO_TOOL_CALL'}, 'ag', self.vault, now_ts=now)
        self.assertEqual(out_ag.get('decision'), 'continue')
        # 同對話第二次放行
        self.assertEqual(lh.evaluate_stop({'conversationId': sid, 'terminationReason': 'NO_TOOL_CALL'}, 'ag', self.vault, now_ts=now), {})

        # Claude 格式
        sid_c = f'cl-{time.time_ns()}'
        out_cl = lh.evaluate_stop({'session_id': sid_c}, 'claude', self.vault, now_ts=now)
        self.assertEqual(out_cl.get('decision'), 'block')

        # 補寫交接後三家早報皆看得到
        lh.append_entry(self.vault, 'Antigravity', '整理工作台', '完成架構', '筆記.md', '換 Codex 接手驗收')
        today = datetime.date.today()
        ag_ctx = json.loads(sb.render('', self.vault, today, fmt='ag'))['injectSteps'][0]['systemMessage']['systemMessage']
        cdx_ctx = json.loads(sb.render('', self.vault, today, fmt='codex'))['hookSpecificOutput']['additionalContext']
        cl_ctx = json.loads(sb.render('startup', self.vault, today, fmt='claude'))['hookSpecificOutput']['additionalContext']
        for ctx in (ag_ctx, cdx_ctx, cl_ctx):
            self.assertIn('換 Codex 接手驗收', ctx)
            self.assertIn('體驗三家 AI 接力與開工流程', ctx)

    def test_ask_options_and_zh_guards_all_three_tools(self):
        subprocess.run(
            [sys.executable, '-X', 'utf8', str(SETUP_PY), 'init', str(self.vault)],
            check=True, capture_output=True,
        )
        aog = load_module('kit_aog', self.vault / '.ai' / 'hooks' / 'ask_options_guard.py')
        zh = load_module('kit_zh', self.vault / '.ai' / 'hooks' / 'zh_guard.py')

        # ask_options_guard: Claude / AG / Codex
        out_cl, _ = aog.evaluate({'last_assistant_message': '請你決定要哪個？'}, 'claude')
        self.assertEqual(out_cl.get('decision'), 'block')

        ag_tr = self.vault / 'ag_tr.jsonl'
        ag_tr.write_text(json.dumps({'role': 'assistant', 'text': '要你決定 A 還是 B？'}, ensure_ascii=False), encoding='utf-8')
        out_ag, is_ag = aog.evaluate({'conversationId': '1', 'terminationReason': 'NO_TOOL_CALL', 'transcriptPath': str(ag_tr)}, 'ag')
        self.assertTrue(is_ag)
        self.assertEqual(out_ag.get('decision'), 'continue')

        out_cdx_bad, _ = aog.evaluate({'last_assistant_message': '請你決定選 A 或 B？'}, 'codex')
        self.assertEqual(out_cdx_bad.get('decision'), 'block')
        out_cdx_ok, _ = aog.evaluate({'last_assistant_message': '1. （推薦）A\n2. B\n請你決定要哪個？'}, 'codex')
        self.assertEqual(out_cdx_ok, {})

        # zh_guard: 英文回覆被擋、繁中放行
        eng = 'This entire explanation is written in plain English without traditional Chinese characters at all so it should be blocked.'
        out_zh_cl, _ = zh.evaluate({'last_assistant_message': eng})
        self.assertEqual(out_zh_cl.get('decision'), 'block')
        out_zh_ok, _ = zh.evaluate({'last_assistant_message': '這是一段繁體中文說明，已處理完成。'})
        self.assertEqual(out_zh_ok, {})

    def test_no_private_data_leaked(self):
        leaks = []
        for p in KIT_ROOT.rglob('*'):
            if p.is_dir() or '__pycache__' in p.parts or p.name == 'test_starter_kit.py':
                continue
            try:
                text = p.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            for term in PRIVATE_TERMS:
                if term.lower() in text.lower():
                    leaks.append((p.relative_to(KIT_ROOT).as_posix(), term))
        self.assertEqual(leaks, [], f'發現私密詞彙外洩：{leaks}')

    def test_one_line_installers_present_and_pointed_to_repo(self):
        ps1 = (KIT_ROOT / 'install.ps1').read_text(encoding='utf-8')
        sh = (KIT_ROOT / 'install.sh').read_text(encoding='utf-8')
        self.assertIn('https://github.com/sam80104/ob-ai-relay/archive/refs/heads/main.zip', ps1)
        self.assertIn('https://github.com/sam80104/ob-ai-relay/archive/refs/heads/main.zip', sh)


if __name__ == '__main__':
    unittest.main()
