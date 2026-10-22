param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw '端口需在1024至65535之间。' }
$projectDirectory = Split-Path -Parent $PSScriptRoot
$dataDirectory = if ($env:FACTORYPULSE_DATA_DIR) { $env:FACTORYPULSE_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'FactoryPulse\data' }
$recordPath = Join-Path $dataDirectory "service-$Port.json"
if (-not (Test-Path -LiteralPath $recordPath)) { throw '没有本启动脚本的服务记录，不会停止未知进程。' }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($record.project_directory) -ne [IO.Path]::GetFullPath($projectDirectory) -or [int]$record.port -ne $Port) { throw '启动记录与当前项目不一致，未停止任何进程。' }
$rootProcess = Get-Process -Id ([int]$record.process_id) -ErrorAction SilentlyContinue
if (-not $rootProcess) { Write-Output '记录的服务进程已经退出。'; return }
$recordedStart = [DateTimeOffset]::Parse($record.started_at).UtcDateTime
if ([Math]::Abs(($rootProcess.StartTime.ToUniversalTime() - $recordedStart).TotalSeconds) -gt 1) { throw '进程编号已被其他程序复用，未停止任何进程。' }
$processRecords = @(Get-CimInstance Win32_Process)
$rootRecord = $processRecords | Where-Object ProcessId -eq $rootProcess.Id
if (-not $rootRecord -or $rootRecord.CommandLine -notlike '*uvicorn backend.main:app*' -or $rootRecord.ExecutablePath -ne $record.python_executable) { throw '服务身份与启动记录不符，未停止任何进程。' }
function Stop-FactoryPulseProcess([int]$taskProcessId) {
    foreach ($childRecord in $processRecords | Where-Object ParentProcessId -eq $taskProcessId) {
        $liveChild = Get-Process -Id ([int]$childRecord.ProcessId) -ErrorAction SilentlyContinue
        if ($liveChild -and [Math]::Abs(($liveChild.StartTime.ToUniversalTime() - $childRecord.CreationDate.ToUniversalTime()).TotalSeconds) -le 1) {
            Stop-FactoryPulseProcess ([int]$childRecord.ProcessId)
        }
    }
    Stop-Process -Id $taskProcessId -ErrorAction Stop
}
Stop-FactoryPulseProcess ([int]$record.process_id)
Write-Output "已停止记录中的 FactoryPulse 服务（端口 $Port）。再次启动前应确认端口已释放。"
