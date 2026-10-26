$ErrorActionPreference='Stop'
$projectDirectory=Split-Path -Parent $PSScriptRoot
$qaConfiguration=Get-Content -LiteralPath (Join-Path $projectDirectory '.secrets/acceptance-current.json') -Raw | ConvertFrom-Json
$qaManifest=Get-Content -LiteralPath (Join-Path $qaConfiguration.directory 'manifest.json') -Raw | ConvertFrom-Json
if($qaManifest.scope -ne 'isolated_cloudflare_acceptance'){throw 'Refusing to run acceptance against a non-test database'}
$qaOutput=Join-Path $projectDirectory 'outputs/full-acceptance'
$launchRecord=Join-Path $qaOutput 'server-process.json'
if(Test-Path -LiteralPath $launchRecord){
 $old=Get-Content -LiteralPath $launchRecord -Raw | ConvertFrom-Json
 foreach($pidValue in @($old.process_id,$old.child_id)){
  if($pidValue){
   $process=Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
   if($process.CommandLine -match 'uvicorn backend.main:app --host 127.0.0.1 --port 8001'){Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue}
  }
 }
}
$env:FACTORYPULSE_IDENTITY_CONFIG=Join-Path $qaConfiguration.directory 'identity.json'
$env:FACTORYPULSE_BUSINESS_CONFIG=Join-Path $qaConfiguration.directory 'business.json'
$env:FACTORYPULSE_DATA_DIR=Join-Path $qaOutput 'runtime'
$env:FACTORYPULSE_SERVE_UI='1';$env:FACTORYPULSE_UI_DIR=Join-Path $projectDirectory 'dist'
$env:FACTORYPULSE_ALLOWED_ORIGINS='http://127.0.0.1:8001,http://localhost:8001'
$env:TEMP=Join-Path $projectDirectory 'outputs/d1-live-qa/tmp';$env:TMP=$env:TEMP
Remove-Item Env:FACTORYPULSE_TEST_ALLOW_ANONYMOUS -ErrorAction SilentlyContinue
$service=Start-Process -FilePath (Join-Path $projectDirectory '.venv/Scripts/python.exe') -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8001' -WorkingDirectory $projectDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $qaOutput 'server-out.log') -RedirectStandardError (Join-Path $qaOutput 'server-error.log') -PassThru
$qaChild=Get-CimInstance Win32_Process -Filter "ParentProcessId=$($service.Id)" -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -match 'uvicorn backend.main:app --host 127.0.0.1 --port 8001'} | Select-Object -First 1
@{process_id=$service.Id;child_id=$qaChild.ProcessId} | ConvertTo-Json | Set-Content -LiteralPath $launchRecord
Write-Output 'Isolated D1 acceptance service starting on 127.0.0.1:8001'
