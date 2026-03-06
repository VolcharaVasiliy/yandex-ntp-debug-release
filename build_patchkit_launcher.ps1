param(
    [switch]$Clean
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

    if ($env:PYTHON_EXE -and (Test-PythonExe $env:PYTHON_EXE)) {
        return $env:PYTHON_EXE
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
$releaseRoot = $PSScriptRoot
$projectRoot = Split-Path $releaseRoot -Parent
$launcherScript = Join-Path $releaseRoot "patchkit_launcher.py"
$scriptsDir = Join-Path $releaseRoot "scripts"
$outputExe = Join-Path $releaseRoot "PatchKit Launcher.exe"
$buildRoot = Join-Path $projectRoot "dist\patchkit_launcher_build"
$workPath = Join-Path $buildRoot "work"
$specPath = Join-Path $buildRoot "spec"

if (-not (Test-Path $launcherScript)) {
    throw "Launcher script not found: $launcherScript"
}

if (-not (Test-Path $scriptsDir)) {
    throw "Scripts directory not found: $scriptsDir"
}

if ($Clean) {
    Remove-Item -Path $workPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $specPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $outputExe -Force -ErrorAction SilentlyContinue
}

& $py -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    & $py -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

New-Item -Path $workPath -ItemType Directory -Force | Out-Null
New-Item -Path $specPath -ItemType Directory -Force | Out-Null

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "PatchKit Launcher",
    "--distpath", $releaseRoot,
    "--workpath", $workPath,
    "--specpath", $specPath,
    "--add-data", "$scriptsDir;scripts",
    $launcherScript
)

& $py @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path $outputExe)) {
    throw "PyInstaller finished without producing: $outputExe"
}

Write-Host "Built launcher:"
Write-Host $outputExe
