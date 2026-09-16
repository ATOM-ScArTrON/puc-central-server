# PUC central server

## Development setup

`server/start_server.ps1` only validates configuration and starts the server. To
create a local development configuration, install OpenSSL and run:

```powershell
.\server\setup_server.ps1
.\runtime\server.env.ps1
.\server\start_server.ps1
```

The setup script creates development-only secrets, a self-signed CA, a server
certificate, a client certificate, and an empty device registry under
`runtime/`. The generated client certificate and key are available under
`runtime\tls\` for mutual-TLS client testing.

Use `-Force` only when replacing the existing local development credentials:

```powershell
.\server\setup_server.ps1 -Force
```

The generated `runtime/` directory is ignored by Git. Do not use the generated
certificates or secrets in production.
