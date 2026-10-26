param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw '端口需在1024至65535之间。' }
$projectDirectory = Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $projectDirectory '.factorypulse-install-incomplete')) {
    throw '离线安装未完成，不能启动半成品运行环境。请查看安装错误并在新的项目目录完成安装。'
}
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
$builtPage = Join-Path $projectDirectory 'dist\index.html'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw '缺少后端运行环境，请按部署说明安装依赖。' }
if (-not (Test-Path -LiteralPath $builtPage)) { throw '缺少前端构建文件，请先完成前端构建。' }
$buildCheck = & $pythonExecutable (Join-Path $projectDirectory 'backend\build_artifact.py') (Join-Path $projectDirectory 'dist')
if ($LASTEXITCODE -ne 0) { throw "本地界面校验失败：$buildCheck" }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "端口 $Port 已被占用，请停止旧服务或选择其他端口。" }
if (-not $env:FACTORYPULSE_DATA_DIR) { $env:FACTORYPULSE_DATA_DIR = Join-Path $env:LOCALAPPDATA 'FactoryPulse\data' }
$identityConfiguration = Join-Path $projectDirectory '.secrets\identity.json'
if (-not $env:FACTORYPULSE_IDENTITY_CONFIG -and (Test-Path -LiteralPath $identityConfiguration)) { $env:FACTORYPULSE_IDENTITY_CONFIG = $identityConfiguration }
$businessConfiguration = Join-Path $projectDirectory '.secrets\business.json'
if (-not $env:FACTORYPULSE_BUSINESS_CONFIG) { $env:FACTORYPULSE_BUSINESS_CONFIG = $businessConfiguration }
if (-not (Test-Path -LiteralPath $env:FACTORYPULSE_BUSINESS_CONFIG)) { throw '缺少 Cloudflare D1 业务配置；禁止创建或回退到本地数据库。' }
$env:FACTORYPULSE_AUTO_BACKUP = '0'
$runtimeTemporaryDirectory = Join-Path $env:FACTORYPULSE_DATA_DIR 'tmp'
New-Item -ItemType Directory -Path $runtimeTemporaryDirectory -Force | Out-Null
$env:TEMP = $runtimeTemporaryDirectory
$env:TMP = $runtimeTemporaryDirectory
$env:FACTORYPULSE_SERVE_UI = '1'
$env:FACTORYPULSE_UI_DIR = Join-Path $projectDirectory 'dist'
$env:FACTORYPULSE_ALLOWED_ORIGINS = "http://127.0.0.1:$Port,http://localhost:$Port"
$logDirectory = Join-Path $env:FACTORYPULSE_DATA_DIR 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$service = Start-Process -FilePath $pythonExecutable -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$Port" -WorkingDirectory $projectDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory "$stamp-out.log") -RedirectStandardError (Join-Path $logDirectory "$stamp-error.log") -PassThru
$launchRecord = @{ process_id=$service.Id; started_at=$service.StartTime.ToUniversalTime().ToString('o'); port=$Port; project_directory=$projectDirectory; python_executable=$pythonExecutable }
$launchRecord | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:FACTORYPULSE_DATA_DIR "service-$Port.json") -Encoding utf8
Write-Output "FactoryPulse 服务已发起启动：进程 $($service.Id)，地址 http://127.0.0.1:$Port。请查看日志确认启动结果。"
Write-Output "日志目录：$logDirectory"
