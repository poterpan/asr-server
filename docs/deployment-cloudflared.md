# Cloudflare Tunnel + Access deployment

Goal: expose the server at `https://asr.example.com/` (your domain), gated by
Cloudflare Access SSO. No direct exposure of the GPU host's IP, no port
forwarding, automatic HTTPS, and the web UI's clipboard API works (it
requires a secure context).

This guide assumes:
- You have a domain hosted on Cloudflare.
- You have a Cloudflare ZeroTrust account (free tier covers up to 50 users).
- The server runs and is reachable from another machine on your LAN — i.e.,
  you've already finished [bare deployment](deployment-bare.md) up to the
  "Run" step (binding `0.0.0.0:8920` is fine here; we'll keep it that way).

## Architecture

```
[Browser] ──HTTPS──► [Cloudflare edge] ──Access SSO──► [tunnel]
                                                          │
                                                          ▼
                                            [cloudflared host on your LAN]
                                                          │
                                                          ▼
                                                  [funasr-server :8920]
```

The `cloudflared` agent can run on the same host as the server, or on a
different machine that can reach the server over LAN (e.g., a router, a NAS,
a separate small VM). This guide assumes it's on a separate device on the
same subnet, but the steps are identical otherwise.

## Step 1 — Install cloudflared

If you haven't yet:

```bash
# Linux x86_64
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
```

(For routers / non-x86 platforms, see [Cloudflare's docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).)

## Step 2 — Create a tunnel (dashboard-managed)

In the Cloudflare ZeroTrust dashboard:

1. **Networks → Tunnels → Create a tunnel**
2. Pick **Cloudflared** type, name it (e.g. `asr-tunnel`), Save.
3. Cloudflare shows you a one-line install command — copy and run it on the
   `cloudflared` host. This installs `cloudflared` as a system service and
   registers it with the tunnel.
4. Wait for the connector to show up as **Healthy**.

Skip this step if you already have a working tunnel and just want to add a
new service to it.

## Step 3 — Add the service as a Public Hostname

In the tunnel's detail page, find the **Published Application Routes** tab
(formerly called "Public Hostnames"; Cloudflare renamed this in late 2025).

> Some dashboards still show the legacy "Public Hostnames" name. The flow is
> identical.

Add a route:

| Field | Value |
|---|---|
| Subdomain | `asr` (or your choice) |
| Domain | `example.com` (your Cloudflare-hosted domain) |
| Path | (leave empty) |
| Service Type | `HTTP` |
| URL | `<funasr-server-host>:8920` (an IP or hostname the cloudflared host can reach) |

Save. Cloudflare auto-creates the `asr.example.com` CNAME record.

DNS propagates within ~30 seconds. At this point `https://asr.example.com/`
is reachable **publicly** — protect it next.

## Step 4 — Access policy

`Cloudflare ZeroTrust → Access → Applications → Add an application → Self-hosted`:

| Field | Value |
|---|---|
| Application name | `funasr-server` |
| Session Duration | `24 hours` (or to taste) |
| Application domain | Subdomain=`asr`, Domain=`example.com` |

On the next step, **add a policy**:
- Action: **Allow**
- Selector: **Emails** → your account email
  (or **Emails ending in** for a whole domain, **WARP**, etc.)

Finish with defaults; **Add application**.

Optional: in the cloudflared route from Step 3, you can now go back and
enable **"Require Cloudflare Access JWT"** + select the application you just
created. This makes `cloudflared` re-validate the token at the connector,
adding a defense-in-depth layer. Keep it off until Step 4 fully works to
avoid debugging two layers at once.

## Step 5 — Test

Open `https://asr.example.com/` in any browser. You should see:

1. Cloudflare Access login page.
2. Email magic-link / OTP / SSO depending on your IdP setup.
3. Redirect back to the FunASR web UI.

If the user doesn't match the policy, Access blocks them with a 403-style
page — your origin is never touched.

## What about the API key?

You can drop `FUNASR_API_KEY` once Access is in front, **but only if you also
restrict direct LAN access** to the GPU host's `:8920`. Otherwise an
attacker on your LAN bypasses Access entirely by hitting the IP directly.
The safest combination:

- Keep `FUNASR_API_KEY` set (defense-in-depth for the LAN side).
- Optionally bind the server to `127.0.0.1` and put `cloudflared` on the
  same host so the tunnel is the only path. This costs you the ability to
  reach the server from other LAN devices directly.

## Calling the API programmatically (CLI / scripts)

Cloudflare Access blocks unauthenticated requests, including from CLI tools.
Two options:

### Option A — Service Tokens

`Access → Service Auth → Service Tokens → Create Service Token`. You get
`CF-Access-Client-Id` and `CF-Access-Client-Secret`. Add them to your
application's policy (allow rule for "Service Token: <name>").

```bash
curl https://asr.example.com/health \
  -H "CF-Access-Client-Id: <id>.access" \
  -H "CF-Access-Client-Secret: <secret>"
```

### Option B — `cloudflared access login`

```bash
cloudflared access login https://asr.example.com
# follow the browser login, it caches a JWT
cloudflared access curl https://asr.example.com/health
```

`cloudflared access curl` wraps `curl` with the cached JWT.

Use service tokens for unattended scripts, `access login` for interactive
human use on a workstation.

## Limits & gotchas

- **Request body size**: Cloudflare limits HTTP request bodies to 100 MB on
  Free / Pro plans. A 2-hour m4a meeting is typically 30–80 MB; uncompressed
  WAV is not. Compress before upload, or split.
- **Idle timeouts**: Cloudflare disconnects idle HTTP connections after
  ~100 s. The server's polling-based job pattern is fine (every-3s requests
  reset the clock); long-poll / SSE on a single connection is not.
- **WebSockets**: supported through Cloudflare Tunnel; this server doesn't
  use them today.
