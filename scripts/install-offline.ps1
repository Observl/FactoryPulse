param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$Wheelhouse,
    [string]$RequirementsFile
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$environmentDirectory = Join-Path $projectDirectory '.venv'
$installationMarker = Join-Path $projectDirectory '.factorypulse-install-incomplete'
if (Test-Path -LiteralPath $installationMarker) { throw '上次离线安装未完成。请保留错误信息，在新的项目目录修正依赖后安装；不能继续使用半成品环境。' }
if (Test-Path -LiteralPath $environmentDirectory) {
    throw '已有 .venv 运行环境，未执行安装或覆盖。升级请先备份业务数据，在新的项目目录安装并完成验收。'
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExecutable -ErrorAction Stop).Path
$wheelDirectory = (Resolve-Path -LiteralPath $Wheelhouse -ErrorAction Stop).Path
$requirementsPath = if ($RequirementsFile) { (Resolve-Path -LiteralPath $RequirementsFile -ErrorAction Stop).Path } else { Join-Path $projectDirectory 'backend\requirements.txt' }
if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) { throw '依赖清单文件不存在。' }
$requirementLines = @(Get-Content -LiteralPath $requirementsPath | ForEach-Object { ($_ -split '#',2)[0].Trim() } | Where-Object { $_ })
$requirementPattern = '^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9_,.-]+\])?(?:\s*(?:===|==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!_-]+(?:\s*,\s*(?:===|==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!_-]+)*)?$'
if (-not $requirementLines.Count -or @($requirementLines | Where-Object { $_ -notmatch $requirementPattern }).Count) {
    throw '离线依赖清单只接受包名及版本约束，不能包含URL、嵌套清单、安装选项或本地路径。'
}
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw 'Python路径必须指向已安装的python.exe。' }
if (-not (Test-Path -LiteralPath $wheelDirectory -PathType Container)) { throw '离线依赖路径必须为目录。' }
if (-not (Get-ChildItem -LiteralPath $wheelDirectory -Filter '*.whl' -File | Select-Object -First 1)) {
    throw '目录中没有离线wheel依赖包，请先在联网准备电脑收集匹配目标Windows及Python版本的全部依赖。'
}
& $pythonPath -I -c 'import sys,struct; assert sys.platform == "win32", "需要Windows运行环境"; assert sys.version_info >= (3,11), "需要Python 3.11或更高版本"; assert struct.calcsize("P")==8, "需要64位Python"; print(sys.version)'
if ($LASTEXITCODE -ne 0) { throw 'Python运行环境检查失败，尚未创建项目环境。' }
& $pythonPath -I (Join-Path $projectDirectory 'backend\build_artifact.py') (Join-Path $projectDirectory 'dist')
if ($LASTEXITCODE -ne 0) { throw '本地服务版界面构建检查失败，尚未创建项目环境。' }
New-Item -ItemType File -Path $installationMarker -ErrorAction Stop | Out-Null
try {
    & $pythonPath -I -m venv $environmentDirectory
    if ($LASTEXITCODE -ne 0) { throw '不能创建虚拟环境，请检查Python venv组件、目录权限与磁盘空间。' }
    $installedPython = Join-Path $environmentDirectory 'Scripts\python.exe'
    # --isolated ignores user pip configuration; --no-index forbids registry lookup.
    & $installedPython -I -m pip --isolated --disable-pip-version-check install --no-index --only-binary=:all: --find-links $wheelDirectory -r $requirementsPath
    if ($LASTEXITCODE -ne 0) { throw '离线依赖安装失败；请检查是否收集了完整且匹配Python版本与Windows架构的wheel包。不会自动联网补齐。' }
    & $installedPython -I -m pip --isolated --disable-pip-version-check check
    if ($LASTEXITCODE -ne 0) { throw '依赖一致性检查失败，不能启动业务服务。' }
    & $installedPython -I -c 'import fastapi,uvicorn,pydantic,multipart,openpyxl,httpx,xgboost,shap,numpy,ortools,keyring; print("后端依赖加载通过")'
    if ($LASTEXITCODE -ne 0) { throw '后端依赖加载失败，请检查运行库和目标平台兼容性。' }
    Remove-Item -LiteralPath $installationMarker -ErrorAction Stop
    Write-Output '本地运行环境安装与依赖检查完成。尚未启动服务，也未修改业务数据库。'
    Write-Output '下一步：设置业务数据目录，运行 scripts/start-local.ps1，再完成隔离流程与恢复验收。'
} catch {
    Write-Warning '安装未完成。保留新建环境供排查，不自动删除目录。请在修正依赖后使用新的项目目录重新安装；不要把本次结果当作安装成功。'
    throw
}
