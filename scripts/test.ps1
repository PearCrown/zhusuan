$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location $projectRoot
try {
    & $pythonPath -X utf8 manage.py test --settings=config.test_settings --keepdb --noinput @args
    if ($LASTEXITCODE -ne 0) { throw '测试未通过，请查看上方结果。' }
} finally { Pop-Location }
