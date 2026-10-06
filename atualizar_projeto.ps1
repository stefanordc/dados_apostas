$ErrorActionPreference = "Stop"

$ProjectPath = $PSScriptRoot
$ZipPath = Join-Path $ProjectPath "download.zip"
$backend = Join-Path $ProjectPath "backend"
$frontend = Join-Path $ProjectPath "frontend"
$envPath = Join-Path $backend ".env"
$legacyEnvPath = Join-Path $ProjectPath ".env"

Write-Host ""
Write-Host "Atualizando projeto em:" -ForegroundColor Cyan
Write-Host $ProjectPath -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $ZipPath)) {
    throw "download.zip nao encontrado em $ProjectPath"
}

$envBackup = $null

if (Test-Path -LiteralPath $envPath) {
    $envBackup = Get-Content -LiteralPath $envPath -Raw
    Write-Host ".env existente sera preservado." -ForegroundColor DarkGray
}
elseif (Test-Path -LiteralPath $legacyEnvPath) {
    $envBackup = Get-Content -LiteralPath $legacyEnvPath -Raw
    Write-Host ".env anterior encontrado e sera migrado." -ForegroundColor DarkGray
}

$temp = Join-Path $env:TEMP ("backtest_apostas_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null

try {
    Write-Host "Extraindo download.zip..." -ForegroundColor Cyan
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $temp -Force

    Get-ChildItem -LiteralPath $temp -Force | ForEach-Object {
        $dest = Join-Path $ProjectPath $_.Name

        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Copy-Item -Path (Join-Path $_.FullName "*") -Destination $dest -Recurse -Force
        }
        else {
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        }
    }

    New-Item -ItemType Directory -Force -Path $backend | Out-Null

    if ($null -ne $envBackup) {
        Set-Content -LiteralPath $envPath -Value $envBackup -Encoding UTF8
    }
    elseif (-not (Test-Path -LiteralPath $envPath)) {
        throw "backend\.env nao encontrado. O atualizador nao solicita senha. Preserve o .env existente da instalacao anterior."
    }

    $venvPython = Join-Path $backend ".venv\Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Criando ambiente virtual Python..." -ForegroundColor Cyan

        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -m venv (Join-Path $backend ".venv")
        }
        elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv (Join-Path $backend ".venv")
        }
        else {
            throw "Python nao encontrado."
        }

        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao criar o ambiente virtual."
        }
    }
    else {
        Write-Host ".venv ja existe; reutilizando." -ForegroundColor DarkGray
    }

    Write-Host "Instalando/atualizando backend..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip." }

    & $venvPython -m pip install -r (Join-Path $backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar backend." }

    Write-Host "Inicializando banco principal..." -ForegroundColor Cyan
    Push-Location $backend
    try {
        & $venvPython ".\scripts\init_db.py"
        if ($LASTEXITCODE -ne 0) { throw "Falha ao inicializar banco principal." }

        Write-Host "Validando historico_jogos..." -ForegroundColor Cyan
        & $venvPython ".\scripts\inspect_history_schema.py"
        if ($LASTEXITCODE -ne 0) { throw "Falha na validacao de historico_jogos." }
    }
    finally {
        Pop-Location
    }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm nao encontrado. Instale o Node.js LTS e execute novamente."
    }

    Write-Host "Instalando/atualizando frontend..." -ForegroundColor Cyan
    Push-Location $frontend
    try {
        & npm install
        if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar frontend." }
    }
    finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "ATUALIZACAO CONCLUIDA" -ForegroundColor Green
    Write-Host "Execute: powershell -ExecutionPolicy Bypass -File `".\iniciar.ps1`"" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $temp) {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
