<#
ReviveOS developer environment bootstrap (Windows PowerShell 5.1 compatible, ASCII only).

Usage (execution policy blocks unsigned scripts by default):
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
  . .\tools\dev_env.ps1

What it does:
  - Prepends portable git (.tools\git), uv and workspace-local pnpm to PATH
  - Points uv cache/python dirs inside the workspace (sandbox-writable)
  - Exports REVIVE_GIT_BIN so revive_core / revive_agents can locate git

Host facts (see docs/dev-environment.md):
  - No system git; portable MinGit is installed under .tools\git
  - uv lives in %USERPROFILE%\.local\bin\uv.exe and is not on PATH
  - registry.npmjs.org is unreachable in this sandbox; .npmrc pins registry.npmmirror.com
  - Docker CLI exists but the sandbox blocks named pipes, so the daemon is unreachable;
    run Docker acceptance tests from a terminal outside the sandbox.
#>

$ErrorActionPreference = 'Continue'
$ReviveRoot = Split-Path -Parent $PSScriptRoot
if (-not $ReviveRoot) { $ReviveRoot = (Get-Location).Path }

function Add-RevivePath([string]$Candidate) {
    if ($Candidate -and (Test-Path $Candidate) -and ($env:PATH -notlike "*$Candidate*")) {
        $env:PATH = "$Candidate;$env:PATH"
    }
}

# --- git (portable) ---
$gitCmd = Join-Path $ReviveRoot '.tools\git\cmd'
Add-RevivePath $gitCmd
$gitExe = Join-Path $gitCmd 'git.exe'
if (Test-Path $gitExe) {
    $env:REVIVE_GIT_BIN = $gitExe
    Write-Host "[dev_env] git: $gitExe" -ForegroundColor Green
} else {
    Write-Host "[dev_env] portable git missing at $gitExe (set REVIVE_GIT_BIN manually)" -ForegroundColor Yellow
}

# --- uv ---
$uvExe = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (Test-Path $uvExe) {
    Add-RevivePath (Split-Path -Parent $uvExe)
    $env:UV_CACHE_DIR = Join-Path $ReviveRoot '.uv-cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $ReviveRoot '.uv-python'
    $env:UV_LINK_MODE = 'copy'
    Write-Host "[dev_env] uv: $uvExe" -ForegroundColor Green
} else {
    Write-Host "[dev_env] uv not found at $uvExe" -ForegroundColor Yellow
}

# --- pnpm (workspace-local) ---
$pnpmCjs = Join-Path $ReviveRoot '.tools\pnpm\node_modules\pnpm\bin\pnpm.cjs'
if (Test-Path $pnpmCjs) {
    function global:pnpm { & node $pnpmCjs @args }
    $env:PNPM_STORE_DIR = Join-Path $ReviveRoot '.tools\pnpm-store'
    $env:npm_config_cache = Join-Path $ReviveRoot '.tools\npm-cache'
    $env:PNPM_HOME = Join-Path $ReviveRoot '.tools\pnpm-home'
    $env:ELECTRON_CACHE = Join-Path $ReviveRoot '.tools\electron-cache'
    $env:ELECTRON_BUILDER_CACHE = Join-Path $ReviveRoot '.tools\electron-builder-cache'
    Add-RevivePath (Join-Path $ReviveRoot '.tools\pnpm\node_modules\.bin')
    Write-Host "[dev_env] pnpm function registered -> $pnpmCjs" -ForegroundColor Green
} else {
    Write-Host "[dev_env] pnpm not installed at $pnpmCjs" -ForegroundColor Yellow
}

# --- venv ---
$venvPython = Join-Path $ReviveRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $env:REVIVE_VENV_PYTHON = $venvPython
    Write-Host "[dev_env] venv python: $venvPython" -ForegroundColor Green
} else {
    Write-Host "[dev_env] .venv missing; run uv sync --all-packages first" -ForegroundColor Yellow
}

Write-Host "[dev_env] REVIVE_ROOT=$ReviveRoot" -ForegroundColor Cyan