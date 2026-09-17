<#
Issue one additional Pi client certificate without replacing the CA, server
certificate, master secret, or existing device credentials.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DeviceId,
    [string]$ServerHost = "127.0.0.1",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
if ($DeviceId -notmatch '^[A-Za-z0-9._-]+$') { throw "Invalid device ID. Use letters, numbers, '.', '_' or '-'." }
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot "runtime"
$tlsRoot = Join-Path $runtimeRoot "tls"
$deviceRoot = Join-Path (Join-Path $runtimeRoot "devices") $DeviceId
$openssl = (Get-Command openssl -ErrorAction Stop).Source

foreach ($file in @("ca.key", "ca.crt")) {
    if (-not (Test-Path -LiteralPath (Join-Path $tlsRoot $file) -PathType Leaf)) {
        throw "Missing runtime TLS file: $file. Run setup_server.ps1 first."
    }
}
if ((Test-Path -LiteralPath $deviceRoot) -and -not $Force) {
    throw "Device directory already exists. Use -Force only to replace this device identity."
}
New-Item -ItemType Directory -Force -Path $deviceRoot | Out-Null
$ext = Join-Path $deviceRoot "client.ext"
@'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
'@ | Set-Content -LiteralPath $ext -Encoding ascii

function Invoke-OpenSsl([string[]]$Arguments) {
    & $openssl @Arguments
    if ($LASTEXITCODE -ne 0) { throw "OpenSSL failed with exit code $LASTEXITCODE." }
}

$key = Join-Path $deviceRoot "client.key"
$csr = Join-Path $deviceRoot "client.csr"
$cert = Join-Path $deviceRoot "client.crt"
Invoke-OpenSsl @("genrsa", "-out", $key, "2048")
Invoke-OpenSsl @("req", "-new", "-key", $key, "-out", $csr, "-subj", "/CN=$DeviceId")
Invoke-OpenSsl @("x509", "-req", "-in", $csr, "-CA", (Join-Path $tlsRoot "ca.crt"), "-CAkey", (Join-Path $tlsRoot "ca.key"), "-CAcreateserial", "-out", $cert, "-days", "825", "-sha256", "-extfile", $ext)
Copy-Item -LiteralPath (Join-Path $tlsRoot "ca.crt") -Destination (Join-Path $deviceRoot "ca.crt") -Force
Remove-Item -LiteralPath $csr, $ext -Force
Get-ChildItem -LiteralPath $tlsRoot -Filter "*.srl" -File | Remove-Item -Force

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
    $_.Replace('__DEVICE_ID__', $DeviceId).Replace('__SERVER_HOST__', $ServerHost)
} | Set-Content -LiteralPath (Join-Path $deviceRoot "device.env.sh") -Encoding ascii

Write-Host "Created credentials for $DeviceId in $deviceRoot"
Write-Host "Fingerprint:"
& $openssl x509 -in $cert -noout -fingerprint -sha256
Write-Host "Add that fingerprint in the admin UI, create peer links, then run Pi provisioning."
