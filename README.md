# ob-ai-relay

**模型會一直換，但你的任務正本、習慣與交接流程不會被綁死。**

這是一套給 Obsidian 使用者與多 AI 工具（Claude Code、Codex、Antigravity）共用的極簡工作台套件。不需安裝額外資料庫或同步伺服器，零第三方 Python 相依（只需 Python 3.10 以上），30 秒裝進任何本機 Obsidian Vault。

## 最簡單安裝法（30 秒）：直接把網址貼給你的 AI

只要把本頁網址 **`https://github.com/sam80104/ob-ai-relay`** 貼給任何支援本機資料夾的 AI（Claude Code、Codex、Antigravity），對它說：

> **幫我安裝這個到我的 Obsidian Vault：https://github.com/sam80104/ob-ai-relay**

<details>
<summary>給 AI 執行的標準安裝步驟（AI 讀到這裡就會直接做完）</summary>

1. 下載 `https://github.com/sam80104/ob-ai-relay/archive/refs/heads/main.zip`（或 `git clone https://github.com/sam80104/ob-ai-relay.git`）到暫存目錄。
2. 確認使用者的 Obsidian Vault 路徑（若有多個或找不到再用選項詢問）。
3. 執行以下兩行指令（不覆蓋使用者既有筆記）：
   ```bash
   python setup.py init "<使用者的 Vault 路徑>" --codex-global
   python setup.py doctor "<使用者的 Vault 路徑>"
   ```
4. 確認 `doctor` 回傳全部 `[OK]` 後刪除暫存下載檔，向使用者回報已完成安裝並附上「開工／繼續／收工」四句口令。

</details>

## 單行指令安裝（免 git，貼進終端機即可）

- **Windows PowerShell**：
  ```powershell
  irm https://raw.githubusercontent.com/sam80104/ob-ai-relay/main/install.ps1 | iex
  ```
- **macOS / Linux**：
  ```bash
  curl -fsSL https://raw.githubusercontent.com/sam80104/ob-ai-relay/main/install.sh | bash
  ```

## 四大核心價值

| 模組 | 解決什麼痛點 | 設計機制 |
| --- | --- | --- |
| **OB 唯一正本任務卡＋Bases 看板** | 待辦散落各處、不同軟體同步常鬧雙胞或刪除後復活 | 所有待辦只存在 `任務系統/專案/*/任務卡/*.md` 的 `status`；附 `tasks.py stray` 檢查第二來源，不做了改 `取消`（永不復活） |
| **三家 AI 無縫即時交接** | 一家 AI 用完額度或想換模型時，必須重頭解釋上下文 | 改檔後 Stop Hook 提醒寫入 `.ai/logs/handoff-live.md`（最多 15 筆），下一家 AI 一開啟就透過 `SessionStart` 載入，說「繼續」直接接 |
| **統一溝通與選項決策護欄** | AI 常常在純文字裡丟開放式問題要人盲選，或突然切回英文 | 強制三家 AI「能做就做到底；要拍板必先寫背景前因後果，再給推薦排序選項與原因代價」，並用 `ask_options_guard.py` 與 `zh_guard.py` 機械把關 |
| **實戰開工／收工工作流** | 每天打開電腦不知道先做哪一件，下班沒結算隔天全忘光 | 開工鎖定「今天最多 3 件＋第一步」並存 `am` 快照；收工結算完成度、未完成歸零、提煉最多 3 條經驗與減法 |

## 手動安裝與體檢

```bash
git clone https://github.com/sam80104/ob-ai-relay.git
cd ob-ai-relay
python setup.py init "/path/to/your/Obsidian Vault" --codex-global
python setup.py doctor "/path/to/your/Obsidian Vault"
```

> 安裝程式預設**不會覆蓋**你 Vault 裡已有的同名檔案，對現有筆記 100% 安全。想先預覽會建立哪些檔案，可加上 `--dry-run`。

### （選配）在 Obsidian 開啟一鍵按鈕

在 Obsidian「設定 → 第三方外掛」安裝 **Meta Bind** 後，每張任務卡標題底下就會出現一鍵切換狀態按鈕（完成／取消／今天／明天／本週／等別人），不用手改 YAML。

## 日常四句口令

對 Claude Code、Codex 或 Antigravity 任何一家直接說：

| 口令 | AI 會幫你做什麼 |
| --- | --- |
| **「開工」** | 讀早報與昨天未完成 → 幫你挑出今天最多 3 件與 2 分鐘第一步 → 存開工快照 |
| **「繼續」** | 讀取 `.ai/logs/handoff-live.md` 最近兩筆跨 AI 紀錄，直接接手上一家做到一半的任務 |
| **「收工」** | 結算今天完成度 → 把沒做完的「今天」卡歸零落回明天／本週 → 產出日報與「明天第一件」 |
| **「把 XX 取消／完成」** | 直接更新任務卡正本的 `status`，不再出現在待辦清單中 |

## 授權

MIT License
