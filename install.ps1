param(
    [string]$VaultPath = ""
)

$ErrorActionPreference = "Stop"
$RepoZip = "https://github.com/sam80104/ob-ai-relay/archive/refs/heads/main.zip"

function Resolve-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    throw "找不到 Python，請先安裝 Python 3.10 以上版本。"
}

if (-not $VaultPath) {
    $candidates = @(
        (Join-Path $HOME "Documents\Obsidian Vault"),
        (Join-Path $HOME "Obsidian Vault"),
        (Join-Path $HOME "Documents\MyVault")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $VaultPath = $c
            break
        }
    }
    if (-not $VaultPath) {
        $VaultPath = Read-Host "請輸入你的 Obsidian Vault 完整路徑（例如 C:\Users\name\Documents\MyVault）"
    }
}

$VaultPath = $VaultPath.Trim('"').Trim("'")
if (-not $VaultPath) { throw "未提供 Obsidian Vault 路徑。" }

$py = Resolve-Python
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ob-ai-relay-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
$zipFile = Join-Path $tmpRoot "repo.zip"
New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

try {
    Write-Host "正在下載 ob-ai-relay..."
    Invoke-WebRequest -Uri $RepoZip -OutFile $zipFile -UseBasicParsing
    Expand-Archive -Path $zipFile -DestinationPath $tmpRoot -Force
    $kitDir = Get-ChildItem -Path $tmpRoot -Directory | Where-Object { $_.Name -like "ob-ai-relay*" } | Select-Object -First 1
    if (-not $kitDir) { throw "解壓失敗：找不到 ob-ai-relay 目錄。" }

    & $py -X utf8 (Join-Path $kitDir.FullName "setup.py") init $VaultPath --codex-global
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $py -X utf8 (Join-Path $kitDir.FullName "setup.py") doctor $VaultPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    if (Test-Path $tmpRoot) {
        Remove-Item -Path $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
