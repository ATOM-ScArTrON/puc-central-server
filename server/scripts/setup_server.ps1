<#
Prepares a local development installation of the central server: creates the
CA and server TLS identity only. Devices get their own client identity via
zero-touch enrollment (POST /api/enroll from the Pi) — this script no longer
pre-generates per-device certificates or a device registry.
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string]$ServerHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot "runtime"
$tlsRoot = Join-Path $runtimeRoot "tls"
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

if (Test-Path -LiteralPath $runtimeRoot) {
    $existing = Get-ChildItem -LiteralPath $runtimeRoot -Force -ErrorAction SilentlyContinue
    if ($existing -and -not $Force) {
        throw "Runtime directory already contains files. Use -Force only to replace the development setup."
    }
}

$openssl = Require-Command "openssl"
New-Item -ItemType Directory -Force -Path $tlsRoot | Out-Null

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
$env:TLS_CA_KEY_FILE = '__TLS_CA_KEY__'
$env:SERVER_BIND = '0.0.0.0'
$env:SERVER_PORT = '8443'
$env:ADMIN_BIND = '127.0.0.1'
$env:ADMIN_PORT = '8444'
'@ | ForEach-Object {
    $_.Replace('__MASTER_SECRET__', $masterSecret).Replace('__BROADCAST_KEY__', $broadcastKey).Replace('__TLS_CERT__', $serverCert).Replace('__TLS_KEY__', $serverKey).Replace('__TLS_CA__', $caCert).Replace('__TLS_CA_KEY__', $caKey)
} | Set-Content -LiteralPath $envFile -Encoding utf8

Remove-Item -LiteralPath $serverCsr, $serverExt -Force

Write-Host "Development server setup complete (CA + server identity only)."
Write-Host "Load server configuration with: . .\runtime\server.env.ps1"
Write-Host "Devices enroll themselves via POST /api/enroll when they first run the provisioning client."