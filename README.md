# PUC central server

## Development setup

The central service is a FastAPI application with a server-rendered Jinja2
admin UI and PostgreSQL persistence. Install PostgreSQL and create a database
and user matching `DATABASE_URL`, then install the Python dependencies from
`requirements.txt`.

To create a development TLS configuration for the current two Pis, install
OpenSSL and run this on the server machine. Use the server's LAN address when
the Pis are on another machine:

```powershell
.\server\scripts\setup_server.ps1 -ServerHost 172.16.46.69
. .\runtime\server.env.ps1
.\server\scripts\start_server.ps1
```

The setup script creates development-only secrets, a self-signed CA, a server
certificate, and one separate client certificate per device under
`runtime\devices\`. The default devices are `Pi-A` and `Pi-B`; more initial
devices can be supplied with `-DeviceIds Pi-A,Pi-B,Pi-C`. It also writes the
server environment file containing the PostgreSQL connection string, server
secrets, and certificate paths.

### Adding another Pi later

Do not rerun setup with `-Force` just to add a device. Issue one new client
identity while preserving the existing CA and device credentials:

```powershell
.\server\scripts\new_device.ps1 -DeviceId Pi-C -ServerHost 172.16.46.69
```

The generated directory under `runtime\devices\Pi-C` contains `client.crt`,
`client.key`, and `ca.crt`. Copy it to that Pi over a trusted channel. Add its
certificate fingerprint in the admin UI, then create peer links for whichever
devices it should communicate with.

After PostgreSQL is running, enroll the generated fingerprints in the admin UI
and select peers. The server derives epoch-scoped pairwise keys when each Pi
runs the provisioning client.

On each Pi, configure `DEVICE_ID`, `PROVISION_SERVER_URL`, `TLS_CA_FILE`,
`TLS_CERT_FILE`, and `TLS_KEY_FILE`, then run the provisioning client once. It
stores the returned mission keyset in `MISSION_KEYSET_PATH`. The gateway sync
option can then upload queued records to the central server.

Use `-Force` only when replacing the entire local development setup:

```powershell
.\server\scripts\setup_server.ps1 -Force -ServerHost 172.16.46.69
```

The generated `runtime/` directory is ignored by Git. Do not use the generated
certificates, credentials, or secrets in production. Change the development
admin password before exposing the admin UI.

After starting the server, open `https://127.0.0.1:8444/admin` in a browser.
The server creates its PostgreSQL schema automatically on startup. The device
API requires client certificates on port 8443, while the admin UI uses
administrator authentication on port 8444.

A key-epoch rotation affects all active peer keys, so provision every active
Pi after changing peers, revoking a device, or starting a new epoch.
