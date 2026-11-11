# Jarvis bootstrap (Windows). Quiet, idempotent, fails loudly instead of looping.
#   .\bootstrap.ps1            normal start (installs only what is missing/changed)
#   .\bootstrap.ps1 -Console   start with a visible console for debugging
param([switch]$Console)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root
$LogDir = Join-Path $env:LOCALAPPDATA "JarvisAI\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$SetupLog = Join-Path $LogDir "setup.log"

function Fail($msg) {
    Write-Host "`n[ERROR] $msg" -ForegroundColor Red
    if (Test-Path $SetupLog) { Write-Host "--- last lines of $SetupLog ---"; Get-Content $SetupLog -Tail 15 }
    Read-Host "Press Enter to close"
    exit 1
}
function Run($exe, $argList, $what) {
    # runs quietly, appends output to setup.log, stops on a non-zero exit code
    "`n>>> $what : $exe $argList" | Add-Content $SetupLog
    $p = Start-Process -FilePath $exe -ArgumentList $argList -Wait -PassThru -NoNewWindow `
         -RedirectStandardOutput "$LogDir\_o.txt" -RedirectStandardError "$LogDir\_e.txt"
    Get-Content "$LogDir\_o.txt","$LogDir\_e.txt" -ErrorAction SilentlyContinue | Add-Content $SetupLog
    if ($p.ExitCode -ne 0) { Fail "$what failed (exit code $($p.ExitCode))." }
}

Write-Host "Starting Jarvis..." -ForegroundColor Cyan

# 1. Python 3.11 or 3.12 only (mediapipe / pyaudio wheels do not exist for newer versions)
$Py = $null
foreach ($v in "3.12","3.11") {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py "-$v" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = @("py","-$v"); break }
    }
}
if (-not $Py) {
    Write-Host "Python 3.12 not found - installing for this user only..." -ForegroundColor Yellow
    $inst = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" -OutFile $inst
    Start-Process $inst -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1" -Wait
    $env:Path = [Environment]::GetEnvironmentVariable("Path","User") + ";" + [Environment]::GetEnvironmentVariable("Path","Machine")
    $Py = @("py","-3.12")
    & py -3.12 -c "import sys" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "Python 3.12 install did not finish. Install it from python.org, then run this again." }
}

# 2. Virtual environment (recreated if it was built with the wrong Python)
$Venv   = Join-Path $Root ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$VenvPyW = Join-Path $Venv "Scripts\pythonw.exe"
if (Test-Path $VenvPy) {
    $ver = & $VenvPy -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
    if ($ver -notin @("3.11","3.12")) { Write-Host "Rebuilding .venv (was Python $ver)" -ForegroundColor Yellow; Remove-Item -Recurse -Force $Venv }
}
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    Run $Py[0] (($Py[1..($Py.Length-1)] + @("-m","venv",".venv")) -join " ") "create venv"
}

# 3. Dependencies - only when requirements.txt changed
$Stamp = Join-Path $Venv ".req_hash"
$Hash  = (Get-FileHash (Join-Path $Root "requirements.txt") -Algorithm SHA256).Hash
if ((-not (Test-Path $Stamp)) -or ((Get-Content $Stamp -Raw).Trim() -ne $Hash)) {
    Write-Host "Installing dependencies (first run takes a few minutes; details in $SetupLog)..." -ForegroundColor Cyan
    Run $VenvPy "-m pip install --upgrade pip wheel -q --disable-pip-version-check" "upgrade pip"
    Run $VenvPy "-m pip install -r requirements.txt -q --disable-pip-version-check" "install requirements"
    Set-Content $Stamp $Hash
}

# 4. Playwright browsers - once
$PwStamp = Join-Path $Venv ".playwright_done"
if (-not (Test-Path $PwStamp)) {
    Write-Host "Installing browser component (one time)..." -ForegroundColor Cyan
    try { Run $VenvPy "-m playwright install chromium" "playwright"; Set-Content $PwStamp "ok" }
    catch { Write-Host "Browser component skipped (browser control will be unavailable)." -ForegroundColor Yellow }
}

# 5. Node.js is optional (Spotify MCP server only)
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Note: Node.js not installed - Spotify control will be unavailable. Get it from nodejs.org if you want it." -ForegroundColor Yellow
}

# 6. Launch
if ($Console) {
    & $VenvPy (Join-Path $Root "main.py") --startup
} else {
    $exe = if (Test-Path $VenvPyW) { $VenvPyW } else { $VenvPy }
    Start-Process -FilePath $exe -ArgumentList "main.py --startup" -WorkingDirectory $Root
    Write-Host "Started. Logs: $LogDir\app.log" -ForegroundColor Green
    Start-Sleep -Seconds 2
}
