"""FunASR meeting-transcription pipeline.

Loads paraformer-zh (ASR) + fsmn-vad (VAD) + ct-punc (punctuation) + cam++ (speaker
diarization) once, then exposes `transcribe(audio_path)` returning a list of
`{speaker, start, end, text}` dicts plus a markdown formatter.

Optionally post-processes Simplified Chinese output to Traditional (Taiwan
phrase variant) via OpenCC.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from funasr import AutoModel
from opencc import OpenCC

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    speaker: int
    start: float  # seconds
    end: float    # seconds
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
        }


class Pipeline:
    def __init__(
        self,
        device: str = "cuda",
        max_single_segment_ms: int = 60_000,
        opencc_config: str = "s2twp",
    ) -> None:
        logger.info("Loading FunASR models on %s ...", device)
        self.model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": max_single_segment_ms},
            punc_model="ct-punc",
            spk_model="cam++",
            device=device,
            disable_update=True,
        )
        # s2twp = Simplified -> Traditional (Taiwan) with phrase replacement.
        self._converter = OpenCC(opencc_config)
        logger.info("FunASR models ready (opencc=%s).", opencc_config)

    def transcribe(
        self,
        audio_path: str | os.PathLike[str],
        batch_size_s: int = 300,
        batch_size_threshold_s: int = 60,
        hotword: str | None = None,
        traditional: bool = True,
    ) -> list[dict[str, Any]]:
        path = str(Path(audio_path).expanduser().resolve())
        kwargs: dict[str, Any] = {
            "input": path,
            "batch_size_s": batch_size_s,
            "batch_size_threshold_s": batch_size_threshold_s,
        }
        if hotword:
            kwargs["hotword"] = hotword

        raw = self.model.generate(**kwargs)
        results = [s.to_dict() for s in _flatten_segments(raw)]
        if traditional:
            convert = self._converter.convert
            for r in results:
                r["text"] = convert(r["text"])
        return results


def _flatten_segments(raw: Any) -> Iterable[Segment]:
    """FunASR returns `[{text, sentence_info: [{text, spk, start, end}, ...]}]`.

    `start`/`end` are in milliseconds. We normalize to seconds and unify into a
    flat segment list. If `sentence_info` is missing (no spk model), fall back
    to a single segment per result.
    """
    if not raw:
        return
    for item in raw:
        sentences = item.get("sentence_info") if isinstance(item, dict) else None
        if sentences:
            for s in sentences:
                yield Segment(
                    speaker=int(s.get("spk", 0)),
                    start=float(s.get("start", 0)) / 1000.0,
                    end=float(s.get("end", 0)) / 1000.0,
                    text=(s.get("text") or "").strip(),
                )
        elif isinstance(item, dict) and item.get("text"):
            yield Segment(speaker=0, start=0.0, end=0.0, text=item["text"].strip())


def format_as_markdown(segments: list[dict[str, Any]], title: str = "Transcript") -> str:
    lines = [f"# {title}", ""]
    for seg in segments:
        ts = f"[{_fmt_ts(seg['start'])} → {_fmt_ts(seg['end'])}]"
        lines.append(f"- **Speaker {seg['speaker']}** {ts}  {seg['text']}")
    return "\n".join(lines) + "\n"


def format_for_llm(segments: list[dict[str, Any]]) -> str:
    """LLM-friendly format: consecutive same-speaker segments merged into one
    turn, headed by `[Speaker N · MM:SS]` where the time is the turn's start.

    Designed for feeding into a summarization prompt. Optimized for low token
    overhead while preserving who-said-what and rough temporal anchors.
    """
    if not segments:
        return ""

    turns: list[dict[str, Any]] = []
    for seg in segments:
        if turns and turns[-1]["speaker"] == seg["speaker"]:
            turns[-1]["text"] += seg["text"]
            turns[-1]["end"] = seg["end"]
        else:
            turns.append({
                "speaker": seg["speaker"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
            })

    lines: list[str] = []
    for t in turns:
        lines.append(f"[Speaker {t['speaker']} · {_fmt_mmss(t['start'])}]")
        lines.append(t["text"].strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _fmt_ts(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_mmss(seconds: float) -> str:
    """MM:SS where minutes can grow past 60 unbounded (e.g. 92:15 for 1h32m15s).

    Compact and unambiguous; LLMs handle this without confusion.
    """
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"
