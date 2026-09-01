#!/usr/bin/env python3
"""Continuous Gemini narration chunks; never invent block-level timings.

The API runs in a killable subprocess. Chunk WAVs and receipts are content scoped;
only measured, checksum-verified complete files are reusable. No API keys in JSON.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave

import media_probe

RATE = 24000
HARD_CAP_SEC = 120.0
VERSION = 1
APPROVED_PROMPT = """Read the following Thai transcript exactly as written.
Sound like a knowledgeable automotive storyteller speaking naturally to an interested friend.
Medium energy, relaxed but engaged. Keep the speech moving forward with connected phrasing.
Do not sound like a newsreader, announcer, audiobook narrator, advertisement, or formal documentary voice.
Do not over-enunciate. Do not deliberately emphasize every important word.
Use subtle natural variation in pitch and rhythm. Keep pauses short and conversational.
The delivery should feel spontaneous even though the wording must remain exact.
Pronounce English vehicle names clearly without disturbing the surrounding Thai."""
CONTINUITY = """This is a continuous section of a longer narration.
Do not introduce the segment as a new beginning or restart the performance at each paragraph.
Paragraph endings are not conclusions. Do not use a concluding cadence unless the actual text clearly concludes the story.
Maintain the same conversational energy throughout.
Read only the transcript below, not these instructions."""


class ChunkError(RuntimeError):
    pass


class RateLimited(ChunkError):
    """The API refused a request for a transient or daily usage limit.

    This is deliberately distinct from ordinary chunk failures: continuing to
    submit the remaining chunks only burns more quota and obscures resume.
    """
    pass


class OversizedAudio(ChunkError):
    pass


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def clean_text(text):
    """Only the approved punctuation changes, on a derived speech-input copy."""
    text = re.sub(r"^\s*Caption\s*\(Thesis\)\s*:\s*", "", text)
    return re.sub(r"\s+", " ", text.replace("“", "").replace("”", "").replace("—", ", ")).strip()


def config(raw):
    cfg = {
        "provider": "gemini-tts", "model": raw.get("model", "gemini-3.1-flash-tts-preview"),
        "voice": raw.get("voice", "Charon"), "style_instruction": raw.get("style_instruction", APPROVED_PROMPT),
        "continuity_instruction": CONTINUITY, "target_sec": float(raw.get("target_sec", 95)),
        "estimate_chars_per_sec": float(raw.get("estimate_chars_per_sec", 14)),
        "hard_cap_sec": HARD_CAP_SEC, "sample_rate": RATE, "renderer_version": VERSION,
    }
    if not 75 <= cfg["target_sec"] <= 100:
        raise ChunkError("target_sec must be between 75 and 100; audio hard cap is always 120s")
    if not math.isfinite(cfg["estimate_chars_per_sec"]) or not 1 <= cfg["estimate_chars_per_sec"] <= 30:
        raise ChunkError("estimate_chars_per_sec must be finite and between 1 and 30")
    if not all(isinstance(cfg[k], str) and cfg[k].strip() for k in ("model", "voice", "style_instruction")):
        raise ChunkError("model, voice and style_instruction must be nonempty strings")
    return cfg


def sentence_parts(text):
    # Whitespace in Thai is NOT proof of a sentence boundary. Never hard-split
    # characters, Thai repetition marks, abbreviations or decimal numbers.
    cuts = []
    for match in re.finditer(r"[!?。！？](?:\s+|$)|\.(?:\s+|$)", text):
        if text[match.start()] == "." and match.end() < len(text):
            token = text[:match.start() + 1].split()[-1]
            if re.fullmatch(r"(?:[A-Za-z]\.)+", token) or token.lower() in {
                "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.",
            }:
                continue
        cuts.append(match.end())
    cuts = [0] + cuts + ([len(text)] if not cuts or cuts[-1] != len(text) else [])
    return [(a, b, text[a:b].strip()) for a, b in zip(cuts, cuts[1:]) if text[a:b].strip()]


def make_chunk(units, cfg):
    text = "\n\n".join(u["text"] for u in units)
    return {
        "chunk_id": "chunk_" + digest(units)[:16], "units": units,
        "block_ids": list(dict.fromkeys(u["block_id"] for u in units)),
        "text": text, "text_sha256": digest(text.encode()),
        "estimated_duration_sec": round(sum(len(u["text"]) for u in units) / cfg["estimate_chars_per_sec"], 3),
        "status": "pending",
    }


def plan_chunks(sm, cfg):
    blocks = sm.get("blocks", [])
    ids = [b.get("block_id") for b in blocks]
    if not blocks or any(not isinstance(b, str) or not b for b in ids) or len(set(ids)) != len(ids):
        raise ChunkError("Script must contain nonempty, unique block IDs")
    units = []
    for block in blocks:
        text = clean_text(block["narration_text"])
        if not text:
            raise ChunkError(f"{block['block_id']}: speech input is empty after punctuation cleanup")
        parts = [(0, len(text), text)]
        if len(text) / cfg["estimate_chars_per_sec"] > cfg["target_sec"]:
            parts = sentence_parts(text)
        for start, end, part in parts:
            if len(part) / cfg["estimate_chars_per_sec"] > HARD_CAP_SEC:
                raise ChunkError(f"{block['block_id']}: a sentence exceeds the conservative 120s estimate; "
                                 "no safe sentence boundary found. Refusing to cut words or send an over-budget request.")
            units.append({"block_id": block["block_id"], "start_char": start, "end_char": end, "text": part})
    chunks, pending, size = [], [], 0
    budget = cfg["target_sec"] * cfg["estimate_chars_per_sec"]
    for unit in units:
        combined = size + len(unit["text"])
        # Target is soft: prefer two neighboring paragraphs around 105s over
        # two isolated 50s performances, but never plan beyond the 120s cap.
        closer = abs(combined - budget) < abs(size - budget)
        if pending and combined > budget and (not closer or combined > HARD_CAP_SEC * cfg["estimate_chars_per_sec"]):
            chunks.append(make_chunk(pending, cfg))
            pending, size = [], 0
        pending.append(unit)
        size += len(unit["text"])
    if pending:
        chunks.append(make_chunk(pending, cfg))
    return chunks


def split_chunk(chunk, cfg):
    units = chunk["units"]
    if len(units) == 1:
        unit = units[0]
        parts = sentence_parts(unit["text"])
        if len(parts) < 2:
            raise ChunkError(f"{chunk['chunk_id']}: overlong audio has no safe sentence/block split; "
                             "completed chunks preserved, alignment remains blocked")
        units = [{**unit, "start_char": unit["start_char"] + a,
                  "end_char": unit["start_char"] + b, "text": t} for a, b, t in parts]
    total = sum(len(u["text"]) for u in units)
    split = min(range(1, len(units)), key=lambda i: abs(sum(len(u["text"]) for u in units[:i]) - total / 2))
    return [make_chunk(units[:split], cfg), make_chunk(units[split:], cfg)]


def worker():
    """One isolated SDK request; key comes only from this process's environment."""
    try:
        from google import genai
        data = json.load(sys.stdin)
        cfg = data["config"]
        with genai.Client(api_key=os.environ["GEMINI_API_KEY"]) as client:
            response = client.interactions.create(
                model=cfg["model"], input=cfg["style_instruction"] + "\n\n" + CONTINUITY + "\n\n" + data["text"],
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": cfg["voice"]}]},
            )
        status = getattr(response, "status", None)
        if status != "completed":
            raise ChunkError("Interaction did not complete")
        audio = response.output_audio
        if audio is None or not audio.data:
            raise ChunkError("Missing audio")
        if getattr(audio, "channels", None) not in (None, 1) or getattr(audio, "sample_rate", None) not in (None, RATE):
            raise ChunkError("Unexpected audio sample rate or channel count")
        mime = getattr(audio, "mime_type", None)
        if mime is not None and mime.split(";", 1)[0].lower() not in ("audio/l16", "audio/pcm", "audio/raw"):
            raise ChunkError("Expected raw PCM, not encoded audio")
        raw = base64.b64decode(audio.data, validate=True) if isinstance(audio.data, str) else audio.data
        print(json.dumps({"pcm": base64.b64encode(raw).decode("ascii")}))
        return 0
    except Exception as exc:
        # Never forward an SDK exception body or URL, which could contain a key.
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return 1


# worker() already limits itself to the SDK exception's CLASS NAME on failure --
# never the exception body or a URL, either of which could embed a key. These are
# well-known, non-sensitive google.api_core/genai exception names, so a short,
# actionable hint for the common ones costs nothing in secret-safety.
_KNOWN_ERROR_HINTS = {
    "RateLimitError": "likely a rate limit or quota (HTTP 429) -- retry the same command later; "
                      "the saved chunks will resume without re-synthesizing",
    "ResourceExhausted": "likely a rate limit or quota (HTTP 429) -- "
                          "preview TTS models often have very low per-minute limits; "
                          "see https://ai.google.dev/gemini-api/docs/rate-limits and your usage tier in AI Studio",
    "PermissionDenied": "likely an auth/billing problem (HTTP 403) -- "
                         "check GEMINI_API_KEY and that billing/the model is enabled for this API key's project",
    "Unauthenticated": "likely an invalid or missing API key (HTTP 401)",
    "InvalidArgument": "likely a bad request parameter (HTTP 400) -- check model/voice names against the live catalog",
    "NotFound": "likely an unknown model or voice name (HTTP 404)",
    "DeadlineExceeded": "the SDK's own request deadline was hit inside the worker (separate from --timeout)",
}

_RATE_LIMIT_ERROR_NAMES = {"RateLimitError", "ResourceExhausted", "TooManyRequests", "QuotaExceeded"}


def _worker_error_name(stderr: str):
    """Return only the worker's deliberately safe exception class name."""
    try:
        name = json.loads(stderr)["error"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return name if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,64}", name) else None


def _diagnose(stderr: str) -> str:
    """Turn the worker's safe {"error": "<ExceptionClassName>"} stderr line into a
    short, actionable suffix for the parent's ChunkError -- e.g. ": ResourceExhausted
    (likely a rate limit...)". Returns "" (a no-op suffix) for anything that isn't
    exactly that shape, so arbitrary/garbage subprocess stderr -- which could in
    principle contain leaked secret material from elsewhere -- is never echoed back.
    """
    name = _worker_error_name(stderr)
    if name is None:
        return ""
    hint = _KNOWN_ERROR_HINTS.get(name)
    return f": {name} ({hint})" if hint else f": {name}"


def request_pcm(cfg, text, timeout_sec):
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            input=json.dumps({"config": cfg, "text": text}), text=True, encoding="utf-8",
            capture_output=True, timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills and reaps the worker, unlike ThreadPoolExecutor.
        raise ChunkError(f"Gemini request exceeded {timeout_sec:g}s; worker terminated") from None
    if result.returncode:
        error = f"Gemini request failed{_diagnose(result.stderr)}. No upstream response logged."
        if _worker_error_name(result.stderr) in _RATE_LIMIT_ERROR_NAMES:
            raise RateLimited(error)
        raise ChunkError(error)
    try:
        return base64.b64decode(json.loads(result.stdout)["pcm"], validate=True)
    except (ValueError, KeyError, TypeError):
        raise ChunkError("Invalid PCM response from Gemini worker") from None


def measure_wav(path):
    try:
        with wave.open(str(path), "rb") as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, RATE, "NONE"):
                raise ChunkError("Unexpected WAV format")
            frames = stream.getnframes()
            if frames <= 0 or len(stream.readframes(frames)) != frames * 2:
                raise ChunkError("Empty or truncated WAV")
        duration = media_probe.probe(str(path)).get("duration_sec")
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ChunkError("Invalid ffprobe duration")
        if abs(duration - frames / RATE) > 0.01:
            raise ChunkError("WAV header and ffprobe duration disagree")
        if frames > RATE * HARD_CAP_SEC or duration > HARD_CAP_SEC:
            raise OversizedAudio(f"Measured audio exceeds {HARD_CAP_SEC:g}s")
        return duration
    except (wave.Error, EOFError, OSError, media_probe.MediaProbeError) as exc:
        raise ChunkError(f"Unusable WAV: {type(exc).__name__}") from None


def write_wav(path, pcm):
    if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
        raise ChunkError("PCM must be nonempty, complete 16-bit samples")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(pcm)
    return measure_wav(path)


@contextmanager
def episode_lock(episode):
    """OS lock releases on crash, including Windows; never requires stale-lock deletion."""
    with (episode / ".tts_chunks.lock").open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                # Windows byte-range locks prohibit reading the locked byte
                # through a second handle. Inspect file size without reading
                # content, then attempt the nonblocking lock at offset zero.
                stream.seek(0, 2)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ChunkError("Another Gemini render is active for this episode") from None
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ChunkError("Another Gemini render is active for this episode") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def render_chunks(episode, raw_config, *, timeout_sec=120, dry_run=False, request=None):
    episode = Path(episode).resolve()
    cfg = config(raw_config)
    if not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise ChunkError("Request timeout must be finite and positive")
    sm_path = episode / "script_manifest.json"
    sm_bytes = sm_path.read_bytes()
    sm = json.loads(sm_bytes)
    master = episode / "master_script.md"
    if not master.is_file() or digest(master.read_bytes()) != sm.get("script_sha256"):
        raise ChunkError("Locked master script hash does not match script_manifest.json")
    initial = plan_chunks(sm, cfg)
    fingerprint = "gemini-chunks_" + digest(cfg)[:16]
    source_hash = digest(sm_bytes)
    manifest_path = episode / "tts_chunks" / fingerprint / source_hash / "manifest.json"
    audio_dir = episode / "audio" / fingerprint / source_hash
    identity = {"version": VERSION, "episode_id": sm["episode_id"], "config": cfg,
                "script_manifest_sha256": source_hash, "script_sha256": sm["script_sha256"],
                "fingerprint": fingerprint}
    if dry_run:
        return {**identity, "status": "planned", "chunks": initial, "alignment_status": "required"}
    if shutil.which("ffprobe") is None:
        raise ChunkError("ffprobe is required; no files modified")
    if request is None:
        if sys.version_info < (3, 10):
            raise ChunkError("Gemini SDK requires Python 3.10 or newer; no files modified")
        if not os.environ.get("GEMINI_API_KEY"):
            raise ChunkError("GEMINI_API_KEY is missing; no files modified")
        try:
            from google import genai
        except ImportError:
            raise ChunkError("Install requirements.txt (google-genai); no files modified") from None
        request = request_pcm
    with episode_lock(episode):
        return _render_locked(episode, sm_path, master, identity, initial, manifest_path, audio_dir, request, timeout_sec)


def _render_locked(episode, sm_path, master, identity, initial, manifest_path, audio_dir, request, timeout_sec):
    cfg = identity["config"]
    manifest = {**identity, "status": "pending", "alignment_status": "required", "chunks": initial}
    if manifest_path.exists():
        saved = read_json(manifest_path)
        if any(saved.get(k) != v for k, v in identity.items()):
            raise ChunkError("Chunk manifest identity mismatch; refusing reuse")
        # Reconstruct text coverage after adaptive splits before trusting state.
        for block_id in dict.fromkeys(u["block_id"] for c in initial for u in c["units"]):
            expected = " ".join(u["text"] for c in initial for u in c["units"] if u["block_id"] == block_id)
            actual = " ".join(u["text"] for c in saved["chunks"] for u in c["units"] if u["block_id"] == block_id)
            if actual != expected:
                raise ChunkError("Saved chunks do not preserve the locked speech text")
        # Order and unit identities must stay monotonic, including split blocks.
        original_ids = list(dict.fromkeys(u["block_id"] for c in initial for u in c["units"]))
        seen = [u["block_id"] for c in saved["chunks"] for u in c["units"]]
        if list(dict.fromkeys(seen)) != original_ids or seen != sorted(seen, key=original_ids.index):
            raise ChunkError("Saved chunks changed block order")
        manifest = saved
    audio_dir.mkdir(parents=True, exist_ok=True)
    pointer = episode / "tts_chunks.json"
    atomic_json(pointer, {"manifest_path": manifest_path.relative_to(episode).as_posix(), "alignment_status": "required"})
    manifest["status"] = "pending"
    atomic_json(manifest_path, manifest)
    failures, index, rate_limited = [], 0, None
    while index < len(manifest["chunks"]):
        chunk = manifest["chunks"][index]
        rebuilt = make_chunk(chunk["units"], cfg)
        if any(chunk.get(k) != rebuilt[k] for k in ("chunk_id", "block_ids", "text", "text_sha256")):
            raise ChunkError("Chunk text/identity mismatch; refusing reuse")
        path = audio_dir / (chunk["chunk_id"] + ".wav")
        receipt_path = path.with_suffix(".receipt.json")
        receipt_identity = {"fingerprint": identity["fingerprint"], "script_manifest_sha256": identity["script_manifest_sha256"],
                            "text_sha256": chunk["text_sha256"], "chunk_id": chunk["chunk_id"]}
        duration, sha = None, None
        if path.exists() and receipt_path.exists():
            try:
                receipt = read_json(receipt_path)
                sha = digest(path.read_bytes())
                if any(receipt.get(k) != v for k, v in receipt_identity.items()) or receipt.get("audio_sha256") != sha:
                    raise ChunkError("Receipt/checksum mismatch")
                duration = measure_wav(path)
            except (ChunkError, ValueError, OSError):
                duration = None
        try:
            if duration is None:
                chunk["status"] = "pending"
                for key in ("audio_path", "audio_sha256", "duration_sec", "error", "deferred_reason"):
                    chunk.pop(key, None)
                atomic_json(manifest_path, manifest)
                print(f"{chunk['chunk_id']}: generating {len(chunk['block_ids'])} block(s)", flush=True)
                pcm = request(cfg, chunk["text"], timeout_sec)
                fd, tmp_name = tempfile.mkstemp(suffix=".wav", dir=audio_dir)
                os.close(fd)
                try:
                    duration = write_wav(Path(tmp_name), pcm)
                    sha = digest(Path(tmp_name).read_bytes())
                    # Receipt before rename: old/missing WAV cannot match new hash.
                    atomic_json(receipt_path, {**receipt_identity, "audio_sha256": sha, "duration_sec": duration})
                    os.replace(tmp_name, path)
                finally:
                    Path(tmp_name).unlink(missing_ok=True)
            chunk.update(status="generated", audio_path=path.relative_to(episode).as_posix(),
                         audio_sha256=sha, duration_sec=duration)
            chunk.pop("error", None)
            print(f"{chunk['chunk_id']}: measured {duration:.3f}s; checkpoint saved", flush=True)
        except OversizedAudio:
            try:
                children = split_chunk(chunk, cfg)
            except ChunkError as exc:
                chunk.update(status="failed", error=str(exc))
                failures.append((chunk["chunk_id"], str(exc)))
            else:
                manifest["chunks"][index:index + 1] = children
                atomic_json(manifest_path, manifest)
                continue
        except RateLimited as exc:
            # Keep this and every untouched chunk pending.  A 429 can be a
            # per-minute, burst, or daily limit; automatic fan-out/retries are
            # harmful in all three cases.  The next explicit invocation resumes.
            chunk.update(status="pending", deferred_reason=str(exc))
            chunk.pop("error", None)
            rate_limited = (chunk["chunk_id"], str(exc))
            atomic_json(manifest_path, manifest)
            print(f"RATE LIMITED: stopped at {chunk['chunk_id']}; remaining chunks were not attempted", flush=True)
            break
        except (ChunkError, OSError) as exc:
            chunk.update(status="failed", error=str(exc))
            failures.append((chunk["chunk_id"], str(exc)))
        atomic_json(manifest_path, manifest)
        index += 1
    if digest(sm_path.read_bytes()) != identity["script_manifest_sha256"] or digest(master.read_bytes()) != identity["script_sha256"]:
        raise ChunkError("Locked script changed during generation; output cannot be handed off")
    manifest["status"] = "generated" if not failures and rate_limited is None else "pending"
    atomic_json(manifest_path, manifest)
    return {"manifest": manifest, "manifest_path": manifest_path,
            "complete": not failures and rate_limited is None,
            "failures": failures, "rate_limited": rate_limited,
            "alignment_required": True}


def alignment_gate(episode):
    """Active chunks cannot authorize discovery using an older Edge manifest."""
    pointer = Path(episode) / "tts_chunks.json"
    if not pointer.exists():
        return None
    try:
        selected = read_json(pointer)
        relative = Path(selected["manifest_path"])
        path = (Path(episode) / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(Path(episode).resolve()):
            return "GEMINI CHUNKS INVALID"
        manifest = read_json(path)
        if digest((Path(episode) / "script_manifest.json").read_bytes()) != manifest["script_manifest_sha256"]:
            return "GEMINI CHUNKS STALE"
        if manifest.get("status") != "generated":
            return "GEMINI CHUNKS REQUIRED"
        return "BLOCK ALIGNMENT REQUIRED"
    except (OSError, ValueError, KeyError, TypeError):
        return "GEMINI CHUNKS INVALID"


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        raise SystemExit(worker())
    raise SystemExit("Use: python run_episode.py tts EPISODE --profile gemini-tts [--dry-run]")
