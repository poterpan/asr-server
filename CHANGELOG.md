# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-04

### Added
- Initial public release.
- FunASR pipeline: `paraformer-zh` (ASR) + `fsmn-vad` (VAD) + `ct-punc`
  (punctuation) + `cam++` (speaker diarization).
- OpenCC `s2twp` Simplified→Traditional Chinese (Taiwan phrase) conversion,
  toggleable per-request via `?traditional=true|false`.
- FastAPI server with Bearer-token authentication.
- In-memory job queue via `BackgroundTasks`; `POST /transcribe` is
  non-blocking, returns a `job_id` for polling.
- Three result formats:
  - `json` — programmatic, default
  - `md` — markdown with full per-segment timestamps, for human review
  - `llm` — same-speaker turns merged, coarse `MM:SS` anchors, for LLM
    summarization (~80% lower framing tokens vs. `md`)
- Single-file vanilla-JS web UI with drag-drop, polling status, result
  display, and copy / download buttons. No build step.
- Bearer-token storage in browser `localStorage`; never embedded in HTML.
- Smoke test (`test_smoke.py`) using a synthesized 5 s sine wave; verifies
  CUDA load and pipeline runs end-to-end.
- Deployment guides for bare LAN setup and Cloudflare Tunnel + Access SSO.
- systemd unit template.
