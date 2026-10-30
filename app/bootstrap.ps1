$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
function Find-Python311($launcherPath) {
    $ErrorActionPreference = 'Continue'
    $detected = & $launcherPath -3.11 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0) { return $detected }
}
function Test-Python($candidatePath) {
    $ErrorActionPreference = 'Continue'
    & $candidatePath -c 'import sys; sys.getwindowsversion(); raise SystemExit(0 if sys.version_info >= (3,11) else 1)' 2>$null
    return ($LASTEXITCODE -eq 0)
}
try {
    if (-not (Test-Path -LiteralPath $projectPython)) {
        $candidates = @()
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            $detected = Find-Python311 $launcher.Source
            if ($detected) { $candidates += $detected }
        }
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe')
        $candidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Python\pythoncore-*\python.exe') -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
        $candidates += Get-Command python.exe -All -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
        $basePython = $null
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            if (Test-Python $candidate) { $basePython = $candidate; break }
        }
        if (-not $basePython) { throw 'Install Python 3.11 or newer for Windows, then run ChapterBox again.' }
        Write-Host "Creating ChapterBox environment with $basePython"
        & $basePython -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the ChapterBox environment.' }
    }
    & $projectPython -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'ChapterBox Python environment is unavailable. No server changes were made.' }
    & $projectPython -c 'import sys,importlib.util; raise SystemExit(0 if importlib.util.find_spec(sys.argv[1]) else 1)' pypdf
    if ($LASTEXITCODE -ne 0) {
        $answer = Read-Host 'Install PDF dependency pypdf into ChapterBox .venv? [y/N] (No still allows TXT/EPUB)'
        if ($answer -eq 'y') {
            & $projectPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
            if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the connection and retry.' }
        }
    }
    & $projectPython -m app.main
    exit $LASTEXITCODE
} catch {
    Write-Host $_ -ForegroundColor Red
    exit 1
}
