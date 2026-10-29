$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath "env.example" -Destination ".env"
    Write-Host "已创建 .env，请按需修改 SESSION_SECRET。"
}

if ((-not (Test-Path -LiteralPath ".gitignore")) -and (Test-Path -LiteralPath "gitignore.txt")) {
    Copy-Item -LiteralPath "gitignore.txt" -Destination ".gitignore"
}

python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

