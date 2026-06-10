$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Could not find venv Python at $python"
}

$processes = @()

function Start-AppProcess {
    param(
        [string] $Name,
        [string[]] $Arguments
    )

    Write-Host "Starting $Name..."
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList $Arguments `
        -WorkingDirectory $root `
        -NoNewWindow `
        -PassThru

    $script:processes += $process
    return $process
}

function Stop-AppProcesses {
    foreach ($process in $script:processes) {
        if ($process -and -not $process.HasExited) {
            Write-Host "Stopping process $($process.Id)..."
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
    Start-AppProcess "FastAPI" @(
        "-m", "uvicorn",
        "backend.api:app",
        "--host", "127.0.0.1",
        "--port", "8000"
    ) | Out-Null

    Start-AppProcess "frontend" @(
        "-m", "http.server",
        "5173",
        "--directory", "frontend",
        "--bind", "127.0.0.1"
    ) | Out-Null

    Write-Host ""
    Write-Host "Courtvision is running:"
    Write-Host "  API:      http://127.0.0.1:8000"
    Write-Host "  API docs: http://127.0.0.1:8000/docs"
    Write-Host "  Frontend: http://127.0.0.1:5173"
    Write-Host ""
    Write-Host "Press Ctrl+C to stop both processes."

    while ($true) {
        Start-Sleep -Seconds 1

        foreach ($process in $processes) {
            if ($process.HasExited) {
                throw "A child process exited unexpectedly. Check the logs above."
            }
        }
    }
}
finally {
    Stop-AppProcesses
}
