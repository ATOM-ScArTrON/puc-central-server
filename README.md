# PUC central server

## Development setup

The central service is a FastAPI application with a server-rendered Jinja2
admin UI and PostgreSQL persistence. Install PostgreSQL and create a database
and user matching `DATABASE_URL`, then install the Python dependencies from
`requirements-server.txt`.

To create a development TLS configuration, install OpenSSL and run this on
the server machine. Use the server's LAN address when the Pis are on another
machine:

```powershell
.\server\scripts\setup_server.ps1 -ServerHost 172.16.46.69
. .\runtime\server.env.ps1
.\server\scripts\start_server.ps1
```

The setup script creates development-only secrets, a self-signed CA, and a
server certificate. It does **not** pre-issue any device credentials --
every Pi obtains its own client identity by enrolling itself against the
running server (zero-touch enrollment). It also writes the server
environment file containing the PostgreSQL connection string, server
secrets, and certificate paths.

### Enrolling a Pi

On each Pi, configure `DEVICE_ID`, `PROVISION_SERVER_URL`, and `TLS_CA_FILE`
(the CA certificate only -- the Pi does not have a client cert yet), then run
the provisioning client:

```
python -m wearable.communications.provisioning_client
```

Since no local `TLS_CERT_FILE`/`TLS_KEY_FILE` exist yet, the client
generates its own keypair, builds a CSR for `DEVICE_ID`, and POSTs it to
`/api/enroll`. The server signs the CSR with its CA, registers the resulting
certificate's fingerprint as a new device, and returns the signed
certificate plus the provisioning payload. The client writes `client.crt`/
`client.key` locally and immediately re-registers over mTLS via
`/device/register` to confirm the identity works, storing the returned
mission keyset in `MISSION_KEYSET_PATH`.

This is the only way a device is created in the database -- there is no
manual "add device by fingerprint" path in the admin UI. Re-running
enrollment for the same `DEVICE_ID` updates its fingerprint (useful if a
Pi's local credentials are lost or replaced).

After enrolling, open the admin UI, find the device, and select its peers.
The server derives epoch-scoped pairwise keys and rotates the epoch when
peers change. A newly enrolled device is never a gateway by default -- grant
that role explicitly from the device's admin page after enrollment.

The gateway sync option can then upload queued records to the central
server once a Pi has peers and a mission keyset.

Use `-Force` only when replacing the entire local development setup:

```powershell
.\server\scripts\setup_server.ps1 -Force -ServerHost 172.16.46.69
```

The generated `runtime/` directory is ignored by Git. Do not use the generated
CA, credentials, or secrets in production. Change the development admin
password before exposing the admin UI.

After starting the server, open `https://127.0.0.1:8444/admin` in a browser.
The server creates its PostgreSQL schema automatically on startup. The device
API (including `/api/enroll`) is served on port 8443, while the admin UI uses
administrator authentication on port 8444.

A key-epoch rotation affects all active peer keys, so re-provision every
active Pi after changing peers, revoking a device, or starting a new epoch.
