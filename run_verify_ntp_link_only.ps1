param(
    [string]$YandexRoot = (Join-Path $env:LOCALAPPDATA "Yandex\YandexBrowser"),
    [string]$AppVersion = ""
)

function Resolve-Python {
    function Test-PythonExe([string]$ExePath) {
        if (-not $ExePath -or -not (Test-Path $ExePath)) {
            return $false
        }
        $versionOut = & $ExePath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $versionOut) {
            return $false
        }
        $major = [int](($versionOut.ToString().Split("."))[0])
        return ($major -ge 3)
    }

    if ($env:PYTHON_EXE -and (Test-Path $env:PYTHON_EXE)) {
        if (Test-PythonExe $env:PYTHON_EXE) {
            return $env:PYTHON_EXE
        }
    }

    $fallback = "F:\DevTools\Python311\python.exe"
    if (Test-PythonExe $fallback) {
        return $fallback
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and (Test-PythonExe $pythonCmd.Source)) {
        return $pythonCmd.Source
    }

    throw "Python not found. Install Python or set PYTHON_EXE to python.exe path."
}

$py = Resolve-Python
$script = Join-Path $PSScriptRoot "scripts\verify_ntp_link_only.py"

if (-not (Test-Path $script)) {
    throw "Script not found: $script"
}

$args = @(
    $script,
    "--yandex-root", $YandexRoot
)

if ($AppVersion) {
    $args += @("--app-version", $AppVersion)
}

& $py @args
exit $LASTEXITCODE
