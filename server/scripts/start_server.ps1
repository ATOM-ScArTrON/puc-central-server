<#
Starts the central provisioning and gateway-sync server on Windows.

Required environment variables:
  MASTER_SERVER_SECRET_HEX
  MISSION_BROADCAST_KEY_HEX
  TLS_CERT_FILE
  TLS_KEY_FILE
  TLS_CA_FILE
  TLS_CA_KEY_FILE
  DATABASE_URL
  ADMIN_PASSWORD

Optional environment variables:
  SERVER_BIND          (default: 0.0.0.0)
  SERVER_PORT          (default: 8443)
  ADMIN_BIND           (default: 127.0.0.1)
  ADMIN_PORT           (default: 8444)

Set secrets and certificate paths outside the repository before running this
script. This script intentionally does not generate or print secret values.
#>

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Get-RequiredEnvironmentVariable([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required environment variable '$Name' is not set."
    }
    return $value
}

function Get-RequiredFile([string]$Name) {
    $path = Get-RequiredEnvironmentVariable $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "File configured by '$Name' was not found: $path"
    }
    return (Resolve-Path -LiteralPath $path).Path
}

$null = Get-RequiredEnvironmentVariable "MASTER_SERVER_SECRET_HEX"
$null = Get-RequiredEnvironmentVariable "MISSION_BROADCAST_KEY_HEX"
$null = Get-RequiredEnvironmentVariable "DATABASE_URL"
$null = Get-RequiredEnvironmentVariable "ADMIN_PASSWORD"
$env:TLS_CERT_FILE = Get-RequiredFile "TLS_CERT_FILE"
$env:TLS_KEY_FILE = Get-RequiredFile "TLS_KEY_FILE"
$env:TLS_CA_FILE = Get-RequiredFile "TLS_CA_FILE"
$env:TLS_CA_KEY_FILE = Get-RequiredFile "TLS_CA_KEY_FILE"

if (-not $env:ADMIN_USERNAME) { $env:ADMIN_USERNAME = "postgres" }
if (-not $env:SERVER_BIND) { $env:SERVER_BIND = "127.0.0.1" }
if (-not $env:SERVER_PORT) { $env:SERVER_PORT = "8443" }
if (-not $env:ADMIN_BIND) { $env:ADMIN_BIND = "127.0.0.1" }
if (-not $env:ADMIN_PORT) { $env:ADMIN_PORT = "8444" }

Write-Host "Starting device API on $($env:SERVER_BIND):$($env:SERVER_PORT)"
Write-Host "Starting admin UI on $($env:ADMIN_BIND):$($env:ADMIN_PORT)"
Write-Host "Database: configured PostgreSQL connection"
Write-Host "Press Ctrl+C to stop the server."

python -m server.main
