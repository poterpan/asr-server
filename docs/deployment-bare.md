# Bare deployment (single host, LAN-only)

The simplest path: run uvicorn directly, expose its port to your local network,
done. Suitable when the server runs in a trusted environment (home lab, office
LAN behind firewall) and clients live on the same network.

## Prerequisites

- A Linux host (or WSL2 with systemd) with an NVIDIA GPU (≥8 GB VRAM).
- NVIDIA driver installed at the OS level. **Inside WSL2 do NOT install the
  driver** — it's surfaced from Windows.
- `nvidia-smi` works.
- `ffmpeg` is on `$PATH` (`apt install ffmpeg`).
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

## Install

```bash
git clone https://github.com/<your-fork>/asr-server.git
cd asr-server/server

cp .env.example .env
echo "FUNASR_API_KEY=$(openssl rand -hex 32)" >> .env
chmod 600 .env

uv sync
```

## First run + smoke test

```bash
uv run python test_smoke.py
```

This downloads ~1 GB of models to `~/.cache/modelscope/` on first run, loads
them onto the GPU, runs a 5-second sine through the full pipeline, asserts
GPU memory is being used. Expected to print `SMOKE TEST OK` after ~30s
(models cached) or several minutes (first-time download, depending on
bandwidth — modelscope is hosted in China).

## Run

For local-only:

```bash
set -a; . ./.env; set +a
uv run uvicorn server:app --host 127.0.0.1 --port 8920
```

Open `http://127.0.0.1:8920/`.

For LAN access:

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8920
```

> ⚠️ **Bind to `0.0.0.0` only after you have set `FUNASR_API_KEY`.** Without a
> key, anyone who can reach the port can burn your GPU. The server logs a
> startup warning when this is the case, but doesn't refuse to start.

Then on a LAN client, hit `http://<host-lan-ip>:8920/`.

## Persistent process options

| Option | Pros | Cons |
|---|---|---|
| `tmux` / `screen` session | trivial, zero setup | dies when host reboots |
| `systemd` unit | survives reboots, restart-on-fail, logs to `journalctl` | needs root, slightly more setup |
| `nohup ... &` | simplest survival | hard to monitor / restart |

### tmux

```bash
tmux new-session -d -s funasr \
  "cd $HOME/asr-server/server && set -a && . ./.env && set +a \
   && uv run uvicorn server:app --host 0.0.0.0 --port 8920"
```

Reattach with `tmux attach -t funasr`; `Ctrl-b d` to detach.

### systemd

See [`docs/funasr-server.service`](funasr-server.service) for a template. Edit
`User=`, `WorkingDirectory=`, `ExecStart=` paths to match your install, then:

```bash
sudo cp docs/funasr-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now funasr-server
sudo systemctl status funasr-server
journalctl -u funasr-server -f    # tail logs
```

## Firewall (optional, recommended)

If your host's firewall is on (e.g. `ufw`), allow the port:

```bash
sudo ufw allow from <lan-cidr> to any port 8920 proto tcp
# example: sudo ufw allow from 192.168.1.0/24 to any port 8920 proto tcp
```

Don't `ufw allow 8920` blanket — that opens it to anything reaching the host,
which depending on your network may include the public Internet.

## Common issues

| Symptom | Likely cause |
|---|---|
| `CUDA not available` from `test_smoke.py` | Driver / CUDA mismatch. `nvidia-smi` works in user shell? Inside WSL? |
| Job stuck in `running` | Watch `journalctl -u funasr-server -f` (or tmux pane). Likely a model load issue or OOM. |
| Modelscope download hangs / very slow | China-hosted; campus / corporate networks may throttle. Consider a pre-warmed cache (download on a machine with better bandwidth, then `rsync` `~/.cache/modelscope` over). |
| Web UI loads, "Copy" fails with "clipboard blocked" | You're on plain HTTP. `navigator.clipboard` requires a secure context. See [deployment-cloudflared.md](deployment-cloudflared.md) for an HTTPS path. |
