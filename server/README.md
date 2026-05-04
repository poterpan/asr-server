# server

The FunASR server runtime. See the [repository root README](../README.md) for
architecture, hardware requirements, deployment, and API docs.

## Layout

```
server/
├── pyproject.toml      # uv-managed; FunASR + PyTorch cu124 + FastAPI + OpenCC
├── uv.lock
├── pipeline.py         # AutoModel wrapper, OpenCC s2twp, output formatters
├── server.py           # FastAPI app, in-memory job store, BackgroundTasks
├── test_smoke.py       # synth-sine load + transcribe (no real audio needed)
├── .env.example
└── static/
    └── index.html      # vanilla-JS web UI; no build, no dependencies
```

## Run locally

```bash
cp .env.example .env
echo "FUNASR_API_KEY=$(openssl rand -hex 32)" >> .env
chmod 600 .env

uv sync
set -a; . ./.env; set +a
uv run uvicorn server:app --host 127.0.0.1 --port 8920
```

## Smoke test

```bash
uv run python test_smoke.py
```

First run downloads ~1 GB of models to `~/.cache/modelscope/`. Re-runs are fast.
