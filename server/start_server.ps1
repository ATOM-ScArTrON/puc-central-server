<#
Starts the central provisioning and gateway-sync server on Windows.

Required environment variables:
  MASTER_SERVER_SECRET_HEX
  MISSION_BROADCAST_KEY_HEX
  TLS_CERT_FILE
  TLS_KEY_FILE
  TLS_CA_FILE

Optional environment variables:
  DEVICE_REGISTRY_PATH (default: .\device_registry.json)
  SERVER_BIND          (default: 0.0.0.0)
  SERVER_PORT          (default: 8443)

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
$env:TLS_CERT_FILE = Get-RequiredFile "TLS_CERT_FILE"
$env:TLS_KEY_FILE = Get-RequiredFile "TLS_KEY_FILE"
$env:TLS_CA_FILE = Get-RequiredFile "TLS_CA_FILE"

if (-not $env:DEVICE_REGISTRY_PATH) {
    $env:DEVICE_REGISTRY_PATH = Join-Path $projectRoot "device_registry.json"
}

if (-not (Test-Path -LiteralPath $env:DEVICE_REGISTRY_PATH -PathType Leaf)) {
    throw "Device registry was not found: $($env:DEVICE_REGISTRY_PATH)"
}

if (-not $env:SERVER_BIND) { $env:SERVER_BIND = "0.0.0.0" }
if (-not $env:SERVER_PORT) { $env:SERVER_PORT = "8443" }

Write-Host "Starting central server on $($env:SERVER_BIND):$($env:SERVER_PORT)"
Write-Host "Registry: $($env:DEVICE_REGISTRY_PATH)"
Write-Host "Press Ctrl+C to stop the server."

python -m server.central_server
