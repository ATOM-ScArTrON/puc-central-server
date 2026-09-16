<#
Prepares a local development installation of the central server.

This creates one CA/server identity and one client identity per DeviceId.
Future devices should be added with new_device.ps1; do not regenerate the CA
or server credentials just to add a Pi.
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string]$ServerHost = "127.0.0.1",
    [string[]]$DeviceIds = @("Pi-A", "Pi-B")
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot "runtime"
$tlsRoot = Join-Path $runtimeRoot "tls"
$devicesRoot = Join-Path $runtimeRoot "devices"
$envFile = Join-Path $runtimeRoot "server.env.ps1"

function Require-Command([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { throw "Required command '$Name' was not found in PATH. Install OpenSSL and try again." }
    return $command.Source
}

function Invoke-OpenSsl([string]$OpenSsl, [string[]]$Arguments) {
    & $OpenSsl @Arguments
    if ($LASTEXITCODE -ne 0) { throw "OpenSSL failed with exit code $LASTEXITCODE." }
}

function New-HexSecret([int]$Length) {
    $bytes = New-Object byte[] $Length
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Assert-DeviceIds([string[]]$Ids) {
    if (-not $Ids -or $Ids.Count -lt 1) { throw "At least one device ID is required." }
    $normalized = @($Ids | ForEach-Object { $_.Trim() })
    if (($normalized | Select-Object -Unique).Count -ne $normalized.Count) { throw "Device IDs must be unique." }
    foreach ($id in $normalized) {
        if ($id -notmatch '^[A-Za-z0-9._-]+$') { throw "Invalid device ID '$id'. Use letters, numbers, '.', '_' or '-'." }
    }
    return $normalized
}

function Get-SafeDeviceName([string]$DeviceId) { return ($DeviceId -replace '[^A-Za-z0-9._-]', '_') }

if (Test-Path -LiteralPath $runtimeRoot) {
    $existing = Get-ChildItem -LiteralPath $runtimeRoot -Force -ErrorAction SilentlyContinue
    if ($existing -and -not $Force) {
        throw "Runtime directory already contains files. Use -Force only to replace the development setup."
    }
}

$ids = Assert-DeviceIds $DeviceIds
$openssl = Require-Command "openssl"
if ($Force -and (Test-Path -LiteralPath $devicesRoot)) {
    Remove-Item -LiteralPath $devicesRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $tlsRoot, $devicesRoot | Out-Null
if ($Force) {
    Remove-Item -LiteralPath (Join-Path $tlsRoot "client.key"), (Join-Path $tlsRoot "client.crt") -Force -ErrorAction SilentlyContinue
}

$caKey = Join-Path $tlsRoot "ca.key"
$caCert = Join-Path $tlsRoot "ca.crt"
$serverKey = Join-Path $tlsRoot "server.key"
$serverCsr = Join-Path $tlsRoot "server.csr"
$serverCert = Join-Path $tlsRoot "server.crt"
$serverExt = Join-Path $tlsRoot "server.ext"

$serverSan = "DNS:localhost,IP:127.0.0.1"
$parsedAddress = $null
if ([System.Net.IPAddress]::TryParse($ServerHost, [ref]$parsedAddress)) {
    if ($ServerHost -ne "127.0.0.1") { $serverSan += ",IP:$ServerHost" }
} elseif ($ServerHost -ne "localhost") { $serverSan += ",DNS:$ServerHost" }

Invoke-OpenSsl $openssl @("genrsa", "-out", $caKey, "4096")
Invoke-OpenSsl $openssl @("req", "-x509", "-new", "-nodes", "-key", $caKey, "-sha256", "-days", "3650", "-out", $caCert, "-subj", "/CN=DOP Central Server Development CA")

@"
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$serverSan
"@ | Set-Content -LiteralPath $serverExt -Encoding ascii

Invoke-OpenSsl $openssl @("genrsa", "-out", $serverKey, "2048")
Invoke-OpenSsl $openssl @("req", "-new", "-key", $serverKey, "-out", $serverCsr, "-subj", "/CN=$ServerHost")
Invoke-OpenSsl $openssl @("x509", "-req", "-in", $serverCsr, "-CA", $caCert, "-CAkey", $caKey, "-CAcreateserial", "-out", $serverCert, "-days", "825", "-sha256", "-extfile", $serverExt)

$clientExt = Join-Path $tlsRoot "client.ext"
@'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
'@ | Set-Content -LiteralPath $clientExt -Encoding ascii

$registryDevices = [ordered]@{}
foreach ($deviceId in $ids) {
    $deviceRoot = Join-Path $devicesRoot (Get-SafeDeviceName $deviceId)
    New-Item -ItemType Directory -Force -Path $deviceRoot | Out-Null
    $clientKey = Join-Path $deviceRoot "client.key"
    $clientCsr = Join-Path $deviceRoot "client.csr"
    $clientCert = Join-Path $deviceRoot "client.crt"

    Invoke-OpenSsl $openssl @("genrsa", "-out", $clientKey, "2048")
    Invoke-OpenSsl $openssl @("req", "-new", "-key", $clientKey, "-out", $clientCsr, "-subj", "/CN=$deviceId")
    Invoke-OpenSsl $openssl @("x509", "-req", "-in", $clientCsr, "-CA", $caCert, "-CAkey", $caKey, "-CAcreateserial", "-out", $clientCert, "-days", "825", "-sha256", "-extfile", $clientExt)
    Copy-Item -LiteralPath $caCert -Destination (Join-Path $deviceRoot "ca.crt") -Force

    $fingerprintOutput = (& $openssl x509 -in $clientCert -noout -fingerprint -sha256)
    $fingerprint = (($fingerprintOutput -split "=", 2)[1] -replace ":", "").ToLowerInvariant()
    $peers = @($ids | Where-Object { $_ -ne $deviceId })
    $registryDevices[$deviceId] = [ordered]@{ fingerprint = $fingerprint; peers = $peers; gateway = $true }

    @'
#!/usr/bin/env bash
export DOP_DEVICE_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export DEVICE_ID='__DEVICE_ID__'
export PEER_ID=''
export PROVISION_SERVER_URL='https://__SERVER_HOST__:8443'
export TLS_CA_FILE="$DOP_DEVICE_DIR/ca.crt"
export TLS_CERT_FILE="$DOP_DEVICE_DIR/client.crt"
export TLS_KEY_FILE="$DOP_DEVICE_DIR/client.key"
export MISSION_KEYSET_PATH="$HOME/.wearable_mission_keyset.json"
export GATEWAY_ENABLED='1'
'@ | ForEach-Object {
        $_.Replace('__DEVICE_ID__', $deviceId).Replace('__SERVER_HOST__', $ServerHost)
    } | Set-Content -LiteralPath (Join-Path $deviceRoot "device.env.sh") -Encoding ascii

    Remove-Item -LiteralPath $clientCsr -Force
}

$registry = [ordered]@{ epoch_id = 0; epoch_start_time = 0; devices = $registryDevices }
$registry | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runtimeRoot "device_registry.json") -Encoding utf8

$masterSecret = New-HexSecret 32
$broadcastKey = New-HexSecret 16
@'
$env:MASTER_SERVER_SECRET_HEX = '__MASTER_SECRET__'
$env:MISSION_BROADCAST_KEY_HEX = '__BROADCAST_KEY__'
$env:DATABASE_URL = 'postgresql://postgres:bits%40123@127.0.0.1:5432/puc'
$env:ADMIN_USERNAME = 'postgres'
$env:ADMIN_PASSWORD = 'bits@123'
$env:TLS_CERT_FILE = '__TLS_CERT__'
$env:TLS_KEY_FILE = '__TLS_KEY__'
$env:TLS_CA_FILE = '__TLS_CA__'
$env:SERVER_BIND = '0.0.0.0'
$env:SERVER_PORT = '8443'
$env:ADMIN_BIND = '127.0.0.1'
$env:ADMIN_PORT = '8444'
'@ | ForEach-Object {
    $_.Replace('__MASTER_SECRET__', $masterSecret).Replace('__BROADCAST_KEY__', $broadcastKey).Replace('__TLS_CERT__', $serverCert).Replace('__TLS_KEY__', $serverKey).Replace('__TLS_CA__', $caCert)
} | Set-Content -LiteralPath $envFile -Encoding utf8

Remove-Item -LiteralPath $serverCsr, $serverExt, $clientExt -Force
Get-ChildItem -LiteralPath $tlsRoot -Filter "*.srl" -File | Remove-Item -Force

Write-Host "Development server setup complete."
Write-Host "Generated devices: $($ids -join ', ')"
Write-Host "Load server configuration with: . .\runtime\server.env.ps1"
Write-Host "Enroll each printed device fingerprint in the admin UI."
