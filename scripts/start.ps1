$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按 README 安装项目独立环境。' }
Push-Location $projectRoot
try {
    & $pythonPath -X utf8 manage.py check
    if ($LASTEXITCODE -ne 0) { throw '配置检查失败。' }
    & $pythonPath -X utf8 manage.py check_db
    if ($LASTEXITCODE -ne 0) { throw '数据库检查失败。请先启动本地数据库。' }
    & $pythonPath -X utf8 manage.py runserver 127.0.0.1:8000 --noreload
} finally { Pop-Location }
