# 构建单文件 Windows 图形界面 exe。
# 用法（在项目目录）：powershell -NoProfile -ExecutionPolicy Bypass -File .\build_gui_exe.ps1
# 需要本机 Python 3.10+，并安装：python -m pip install pyinstaller pillow PyQt5
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw 'Python 3 was not found on PATH. Install Python 3.10+ first.'
}

& $python -c "import PyInstaller, PyQt5, PIL" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Missing build dependencies. Run: python -m pip install pyinstaller pillow PyQt5'
}

$svg = Join-Path $root 'dafeiyu_gui\assets\app.svg'
$ico = Join-Path $root 'dafeiyu_gui\assets\app.ico'
if (-not (Test-Path -LiteralPath $ico) -or
    (Get-Item -LiteralPath $svg).LastWriteTimeUtc -gt (Get-Item -LiteralPath $ico).LastWriteTimeUtc) {
    & $python (Join-Path $root 'tools\make_gui_icon.py')
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
}

$exePath = Join-Path $root '大肥鱼控制台.exe'
if (Test-Path -LiteralPath $exePath) {
    Remove-Item -LiteralPath $exePath -Force
}
$workPath = Join-Path $root 'build\gui-exe'
New-Item -ItemType Directory -Path $workPath -Force | Out-Null

$assetPath = Join-Path $root 'dafeiyu_gui\assets'
$addData = "${assetPath};dafeiyu_gui/assets"

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onefile',
    '--windowed',
    '--name', '大肥鱼控制台',
    '--icon', $ico,
    '--add-data', $addData,
    '--hidden-import', 'PyQt5.QtSvg',
    '--distpath', $root,
    '--workpath', $workPath,
    '--specpath', $workPath,
    (Join-Path $root 'dafeiyu_gui_launcher.py')
)

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Expected exe was not created: $exePath"
}
$sizeMb = [math]::Round((Get-Item -LiteralPath $exePath).Length / 1MB, 1)
Write-Host "Built: $exePath ($sizeMb MB)"
