$ErrorActionPreference = "Stop"

$ProjectPath = $PSScriptRoot
$backend = Join-Path $ProjectPath "backend"
$frontend = Join-Path $ProjectPath "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Ambiente virtual nao encontrado. Execute .\atualizar_projeto.ps1 primeiro."
}

if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    throw "Dependencias do frontend nao encontradas. Execute .\atualizar_projeto.ps1 primeiro."
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $npmCommand) {
    throw "npm nao encontrado."
}

function Stop-PortProcess([int]$Port) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($processId in $processIds) {
            if ($processId -and $processId -ne $PID) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        # Ignora se a porta já estiver livre ou o cmdlet não estiver disponível.
    }
}

Write-Host ""
Write-Host "Encerrando servidores antigos, se existirem..." -ForegroundColor DarkGray
Stop-PortProcess 8000
Stop-PortProcess 5173
Start-Sleep -Milliseconds 700

Write-Host "Iniciando backend..." -ForegroundColor Cyan

$backendArgs = @(
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
    "--reload"
)

Start-Process `
    -FilePath $python `
    -WorkingDirectory $backend `
    -ArgumentList $backendArgs

Start-Sleep -Seconds 2

Write-Host "Iniciando frontend..." -ForegroundColor Cyan

$frontendArgs = @(
    "run",
    "dev",
    "--",
    "--host",
    "127.0.0.1"
)

Start-Process `
    -FilePath $npmCommand.Source `
    -WorkingDirectory $frontend `
    -ArgumentList $frontendArgs

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "API docs: http://127.0.0.1:8000/docs" -ForegroundColor Cyan

Start-Process "http://127.0.0.1:5173"
