#!/usr/bin/env bash
set -euo pipefail

REPO_ZIP="https://github.com/sam80104/ob-ai-relay/archive/refs/heads/main.zip"
VAULT_PATH="${1:-}"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "找不到 Python，請先安裝 Python 3.10 以上版本。" >&2
  exit 1
fi

if [ -z "$VAULT_PATH" ]; then
  for candidate in "$HOME/Documents/Obsidian Vault" "$HOME/Obsidian Vault" "$HOME/Documents/MyVault"; do
    if [ -d "$candidate" ]; then
      VAULT_PATH="$candidate"
      break
    fi
  done
fi

if [ -z "$VAULT_PATH" ]; then
  read -r -p "請輸入你的 Obsidian Vault 完整路徑: " VAULT_PATH
fi

if [ -z "$VAULT_PATH" ]; then
  echo "未提供 Obsidian Vault 路徑。" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "正在下載 ob-ai-relay..."
curl -fsSL "$REPO_ZIP" -o "$TMP_DIR/repo.zip"
"$PY" -m zipfile -e "$TMP_DIR/repo.zip" "$TMP_DIR/src"
KIT_DIR="$(find "$TMP_DIR/src" -maxdepth 1 -type d -name 'ob-ai-relay*' | head -n 1)"
if [ -z "$KIT_DIR" ]; then
  echo "解壓失敗：找不到 ob-ai-relay 目錄。" >&2
  exit 1
fi

"$PY" "$KIT_DIR/setup.py" init "$VAULT_PATH" --codex-global
"$PY" "$KIT_DIR/setup.py" doctor "$VAULT_PATH"
