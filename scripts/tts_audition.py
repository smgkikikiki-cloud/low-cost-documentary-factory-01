#!/usr/bin/env python3
"""Voice audition for Google Cloud Chirp 3: HD -- listen before switching the
channel's production voice.

Renders ONE real narration block with several candidate voices so they can be
compared on the actual script, not on a demo sentence. It is deliberately inert
with respect to production:

  * it NEVER writes tts_manifest.json
  * it NEVER writes into episodes/<id>/audio/ (output goes under
    episodes/<id>/temp/audition/, and the tool refuses to run if the resolved
    output directory is inside audio/)
  * it NEVER modifies master_script.md or script_manifest.json

The narration text is used exactly as it appears in script_manifest.json: no
rewriting, no re-punctuation, no inserted pause markup. That is the point of the
first audition -- to hear whether Chirp 3's native Thai prosody already reads the
locked script naturally at speaking_rate 1.0. Pause control, if it turns out to
be needed at all, is a separate later pass.

Voice names are VERIFIED against Google's live catalog (list_voices) before any
synthesis, so a name copied from documentation that isn't actually offered for
this locale fails immediately with the real list rather than producing a
confusing API error.

Authentication is Application Default Credentials only -- no API keys, no
service-account paths, no project IDs live in this repository.

CLI usage:
    # what Thai voices does Google actually offer right now?
    python scripts/tts_audition.py list-voices --language-code th-TH
    python scripts/tts_audition.py list-voices --language-code th-TH --chirp3-only --gender MALE

    # audition the default three Thai male Chirp 3 HD voices on a real block
    python scripts/tts_audition.py audition episodes/ForeignCarsTH_land-cruiser-70

    # a specific block, specific voices
    python scripts/tts_audition.py audition episodes/ForeignCarsTH_land-cruiser-70 \\
        --block-id block_004 \\
        --voice th-TH-Chirp3-HD-Charon --voice th-TH-Chirp3-HD-Orus
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_paths  # noqa: E402
import tts_render  # noqa: E402

DEFAULT_LANGUAGE_CODE = "th-TH"

# Three MALE Chirp 3: HD voices, from Google's published Chirp 3: HD voice table
# (voice name format "<locale>-<model>-<voice>", e.g. th-TH-Chirp3-HD-Charon;
# th-TH is in the Chirp 3: HD language-availability list). These are only a
# starting point -- audition_block() verifies every name against list_voices()
# before synthesizing, so a catalog change surfaces as a clear error with the
# real available names rather than a wrong guess.
DEFAULT_MALE_CHIRP3_VOICES = (
    "th-TH-Chirp3-HD-Charon",
    "th-TH-Chirp3-HD-Fenrir",
    "th-TH-Chirp3-HD-Orus",
)


class AuditionError(RuntimeError):
    pass


def pick_block(episode_dir: Path, block_id: str = None) -> dict:
    """Return one real block from script_manifest.json, read-only.

    With no --block-id, picks the first block with a reasonable amount of prose
    (long enough to actually judge prosody on) and falls back to the first block.
    """
    sm_path = Path(episode_dir) / "script_manifest.json"
    if not sm_path.exists():
        raise AuditionError(f"No script_manifest.json in {episode_dir} -- run `ingest` first.")
    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    blocks = sm.get("blocks", [])
    if not blocks:
        raise AuditionError(f"script_manifest.json in {episode_dir} has no blocks.")

    if block_id:
        for b in blocks:
            if b.get("block_id") == block_id:
                return b
        raise AuditionError(
            f"No block {block_id!r} in {sm_path}. Available: "
            f"{', '.join(b.get('block_id', '?') for b in blocks[:10])}..."
        )

    for b in blocks:
        if len((b.get("narration_text") or "").strip()) >= 120:
            return b
    return blocks[0]


def verify_voices(voices, language_code: str) -> None:
    """Fail before synthesizing if any requested voice isn't in Google's live
    catalog for this locale. Prevents auditioning a name that only exists in a
    blog post.
    """
    catalog = tts_render.list_google_voices(language_code)
    available = {v["name"] for v in catalog}
    missing = [v for v in voices if v not in available]
    if missing:
        chirp3 = sorted(n for n in available if "Chirp3" in n)
        raise AuditionError(
            f"These voice name(s) are not offered for {language_code}: {', '.join(missing)}\n"
            f"  Chirp 3 voices actually available for {language_code} right now:\n    "
            + ("\n    ".join(chirp3) if chirp3 else "(none)")
        )


def audition_block(
    episode_dir: Path, block: dict, voices, language_code: str = DEFAULT_LANGUAGE_CODE,
    speaking_rate: float = 1.0, out_dir: Path = None,
    timeout_sec: float = tts_render.DEFAULT_SYNTHESIS_TIMEOUT_SEC,
    verify: bool = True,
) -> list:
    """Synthesize `block`'s narration once per voice into out_dir. Returns the list
    of written paths. Touches nothing else in the episode.
    """
    episode_dir = Path(episode_dir)
    out_dir = Path(out_dir) if out_dir else episode_paths.audition_dir(episode_dir)

    # Hard guard: an audition must never be able to land in production audio, where
    # a later resume could pick it up as if it were rendered narration.
    audio_root = episode_paths.audio_dir(episode_dir).resolve()
    resolved_out = out_dir.resolve()
    if resolved_out == audio_root or audio_root in resolved_out.parents:
        raise AuditionError(
            f"Refusing to write auditions into the production audio directory ({resolved_out}). "
            f"Pick an --out-dir outside {audio_root}."
        )

    text = (block.get("narration_text") or "").strip()
    if not text:
        raise AuditionError(f"Block {block.get('block_id')!r} has no narration_text to audition.")

    if verify:
        verify_voices(voices, language_code)

    out_dir.mkdir(parents=True, exist_ok=True)
    block_id = block.get("block_id", "block")
    written = []
    for i, voice in enumerate(voices, start=1):
        cfg = tts_render.resolve_tts_config({
            "provider": tts_render.PROVIDER_GOOGLE,
            "voice": voice,
            "language_code": language_code,
            "speaking_rate": speaking_rate,
            "input_mode": "text",   # native text, no pause markup, no rewriting
        })
        short_voice = voice.split("-")[-1]
        out_path = out_dir / f"{block_id}__{short_voice}__rate{speaking_rate:.2f}.mp3"
        tag = f"[{i}/{len(voices)}] {voice}"
        print(f"{tag} generating...", flush=True)
        try:
            tts_render._synthesize(cfg, text, out_path, timeout_sec)
        except tts_render.TTSRenderError as e:
            print(f"{tag} FAILED: {e}", flush=True)
            continue
        duration = tts_render._measure(out_path)
        if duration is None:
            print(f"{tag} FAILED: rendered audio could not be measured", flush=True)
            tts_render._discard_partial(out_path)
            continue
        print(f"{tag} generated {duration:.1f}s -> {out_path}", flush=True)
        written.append(out_path)
    return written


def _cmd_list_voices(args) -> int:
    voices = tts_render.list_google_voices(args.language_code)
    if args.chirp3_only:
        voices = [v for v in voices if "Chirp3" in v["name"]]
    if args.gender:
        voices = [v for v in voices if v["ssml_gender"].upper() == args.gender.upper()]
    if not voices:
        print(f"No matching voices for {args.language_code}.")
        return 1
    print(f"{len(voices)} voice(s) for {args.language_code}:")
    for v in voices:
        print(f"  {v['name']:<36} {v['ssml_gender']:<8} {v['natural_sample_rate_hertz']} Hz")
    return 0


def _cmd_audition(args) -> int:
    episode_dir = Path(args.episode_dir)
    block = pick_block(episode_dir, args.block_id)
    voices = args.voice or list(DEFAULT_MALE_CHIRP3_VOICES)

    text = (block.get("narration_text") or "").strip()
    print(f"Auditioning {block.get('block_id')} of {episode_dir} "
          f"({len(text)} chars) at speaking_rate={args.speaking_rate:.2f}, native text, no pause markup.")
    print(f"  voices: {', '.join(voices)}")

    written = audition_block(
        episode_dir, block, voices,
        language_code=args.language_code, speaking_rate=args.speaking_rate,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        timeout_sec=args.timeout, verify=not args.no_verify,
    )
    if not written:
        print("No audition files were produced.", file=sys.stderr)
        return 1
    print(f"\n{len(written)} audition file(s) written (production audio and tts_manifest.json untouched):")
    for p in written:
        print(f"  {p}")
    return 0


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-voices", help="Print Google's live voice catalog for a locale")
    p_list.add_argument("--language-code", default=DEFAULT_LANGUAGE_CODE)
    p_list.add_argument("--chirp3-only", action="store_true")
    p_list.add_argument("--gender", default=None, help="MALE / FEMALE / NEUTRAL")

    p_aud = sub.add_parser("audition", help="Render one real narration block with several candidate voices")
    p_aud.add_argument("episode_dir")
    p_aud.add_argument("--block-id", default=None, help="Default: the first block with substantial prose")
    p_aud.add_argument("--voice", action="append", default=None,
                       help=f"Repeatable. Default: {', '.join(DEFAULT_MALE_CHIRP3_VOICES)}")
    p_aud.add_argument("--language-code", default=DEFAULT_LANGUAGE_CODE)
    p_aud.add_argument("--speaking-rate", type=float, default=1.0)
    p_aud.add_argument("--out-dir", default=None, help="Default: <episode_dir>/temp/audition")
    p_aud.add_argument("--timeout", type=float, default=tts_render.DEFAULT_SYNTHESIS_TIMEOUT_SEC)
    p_aud.add_argument("--no-verify", action="store_true",
                       help="Skip the list_voices name check (not recommended)")

    args = parser.parse_args()
    try:
        if args.command == "list-voices":
            return _cmd_list_voices(args)
        return _cmd_audition(args)
    except (AuditionError, tts_render.TTSRenderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
