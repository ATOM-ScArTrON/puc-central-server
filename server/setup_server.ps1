<#
Prepares a local development installation of the central server.

This script creates:
  runtime\server.env.ps1       Environment loader for start_server.ps1
  runtime\device_registry.json Starter device registry
  runtime\tls\                 Development CA, server, and client PEM files

The generated credentials and certificates are for development only. Do not
use them in production or commit the runtime directory.
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot "runtime"
$tlsRoot = Join-Path $runtimeRoot "tls"
$envFile = Join-Path $runtimeRoot "server.env.ps1"
$registryFile = Join-Path $runtimeRoot "device_registry.json"

function Require-Command([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command '$Name' was not found in PATH. Install OpenSSL and try again."
    }
    return $command.Source
}

function Invoke-OpenSsl([string]$OpenSsl, [string[]]$Arguments) {
    & $OpenSsl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "OpenSSL failed with exit code $LASTEXITCODE."
    }
}

function New-HexSecret([int]$Length) {
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

if (Test-Path -LiteralPath $runtimeRoot) {
    $existing = Get-ChildItem -LiteralPath $runtimeRoot -Force -ErrorAction SilentlyContinue
    if ($existing -and -not $Force) {
        throw "Runtime directory already contains files. Use -Force only if you intend to replace the development setup."
    }
}

$openssl = Require-Command "openssl"
New-Item -ItemType Directory -Force -Path $tlsRoot | Out-Null

$caKey = Join-Path $tlsRoot "ca.key"
$caCert = Join-Path $tlsRoot "ca.crt"
$serverKey = Join-Path $tlsRoot "server.key"
$serverCsr = Join-Path $tlsRoot "server.csr"
$serverCert = Join-Path $tlsRoot "server.crt"
$clientKey = Join-Path $tlsRoot "client.key"
$clientCsr = Join-Path $tlsRoot "client.csr"
$clientCert = Join-Path $tlsRoot "client.crt"
$serverExt = Join-Path $tlsRoot "server.ext"
$clientExt = Join-Path $tlsRoot "client.ext"

Invoke-OpenSsl $openssl @("genrsa", "-out", $caKey, "4096")
Invoke-OpenSsl $openssl @("req", "-x509", "-new", "-nodes", "-key", $caKey, "-sha256", "-days", "3650", "-out", $caCert, "-subj", "/CN=PUC Central Server Development CA")

@'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
'@ | Set-Content -LiteralPath $serverExt -Encoding ascii

Invoke-OpenSsl $openssl @("genrsa", "-out", $serverKey, "2048")
Invoke-OpenSsl $openssl @("req", "-new", "-key", $serverKey, "-out", $serverCsr, "-subj", "/CN=localhost")
Invoke-OpenSsl $openssl @("x509", "-req", "-in", $serverCsr, "-CA", $caCert, "-CAkey", $caKey, "-CAcreateserial", "-out", $serverCert, "-days", "825", "-sha256", "-extfile", $serverExt)

@'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
'@ | Set-Content -LiteralPath $clientExt -Encoding ascii

Invoke-OpenSsl $openssl @("genrsa", "-out", $clientKey, "2048")
Invoke-OpenSsl $openssl @("req", "-new", "-key", $clientKey, "-out", $clientCsr, "-subj", "/CN=puc-development-client")
Invoke-OpenSsl $openssl @("x509", "-req", "-in", $clientCsr, "-CA", $caCert, "-CAkey", $caKey, "-CAcreateserial", "-out", $clientCert, "-days", "825", "-sha256", "-extfile", $clientExt)

$masterSecret = New-HexSecret 32
$broadcastKey = New-HexSecret 16

if (-not (Test-Path -LiteralPath $registryFile) -or $Force) {
    '{"epoch_id":1,"epoch_start_time":0,"devices":{},"sync_log_path":"runtime/server_sync.jsonl"}' |
        Set-Content -LiteralPath $registryFile -Encoding utf8
}

@'
$env:MASTER_SERVER_SECRET_HEX = '__MASTER_SECRET__'
$env:MISSION_BROADCAST_KEY_HEX = '__BROADCAST_KEY__'
$env:TLS_CERT_FILE = '__TLS_CERT__'
$env:TLS_KEY_FILE = '__TLS_KEY__'
$env:TLS_CA_FILE = '__TLS_CA__'
$env:DEVICE_REGISTRY_PATH = '__REGISTRY__'
$env:SERVER_BIND = '127.0.0.1'
$env:SERVER_PORT = '8443'
'@ |
    ForEach-Object {
        $_.Replace('__MASTER_SECRET__', $masterSecret).
            Replace('__BROADCAST_KEY__', $broadcastKey).
            Replace('__TLS_CERT__', $serverCert).
            Replace('__TLS_KEY__', $serverKey).
            Replace('__TLS_CA__', $caCert).
            Replace('__REGISTRY__', $registryFile)
    } |
    Set-Content -LiteralPath $envFile -Encoding utf8

Remove-Item -LiteralPath $serverCsr, $clientCsr, $serverExt, $clientExt -Force
Get-ChildItem -LiteralPath $tlsRoot -Filter "*.srl" -File | Remove-Item -Force

Write-Host "Development server setup complete."
Write-Host "Load configuration in this PowerShell session with:"
Write-Host "  .\runtime\server.env.ps1"
Write-Host "Then start the server with:"
Write-Host "  .\server\start_server.ps1"
Write-Host "Client certificate: $clientCert"
