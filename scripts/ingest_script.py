#!/usr/bin/env python3
"""Deterministic ingestion of an externally-authored master_script.md into
script_manifest.json. NO LLM is used anywhere in this module.

The upstream OpenAI writer supplies a complete, editorially locked Thai documentary
script, typically shaped like:

    # Vehicle Name

    *one-line hook/deck*

    Narration paragraph...

    Narration paragraph... [Source Name](https://...)

This module never rewrites, summarizes, translates, or corrects the upstream prose.
It only performs mechanical structure extraction:

  1. The first Markdown H1 (`# ...`) becomes `title` metadata.
  2. If the single line immediately following the H1 is unambiguously ONE italic
     span (the whole line, after trimming, is wrapped in matching `*...*` or
     `_..._` with no other content), it becomes `optional_deck` metadata.
  3. Everything else is split into blocks on blank-line-separated paragraphs --
     the smallest clean deterministic block unit. No semantic story beats are
     invented; block formation does not look at content, only blank-line
     boundaries.
  4. Trailing citation-style Markdown links (`[Label](https://...)`) at the very
     END of a paragraph are stripped from the spoken text and recorded in
     source_refs instead, so TTS never reads a URL aloud. A link embedded
     mid-sentence ("According to [Motor1](url), the car...") is left completely
     untouched -- only a literal trailing citation marker is a citation. When in
     doubt, nothing is stripped: preserved spoken text always beats a guess.

CLI usage:
    python scripts/ingest_script.py \\
        --channel ForeignCarsTH --topic "Jeep Wrangler YJ" \\
        --script /path/to/master_script.md --episode-dir episodes/ForeignCarsTH_jeep-wrangler-yj

Also importable: parse_master_script(text) -> (title, optional_deck, blocks) for
callers (e.g. run_episode.py's `ingest` command) that already know the episode_id/
channel_id/paths and just need the parsing logic.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# A trailing citation link: "... sentence text [Label](https://url)" with only
# whitespace after the link to the end of the paragraph. Applied repeatedly so
# multiple consecutive trailing citations ("... text [A](u1) [B](u2)") all strip.
_TRAILING_LINK_RE = re.compile(r"\s*\[([^\]\n]+)\]\((https?://[^\s\)]+)\)\s*$")

# One whole line that is ENTIRELY a single italic span: *text* or _text_, nothing
# else on the line (no mixed formatting, no trailing prose).
_SOLE_ITALIC_LINE_RE = re.compile(r"^\*([^*\n]+)\*$|^_([^_\n]+)_$")

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")


def extract_trailing_source_refs(paragraph: str):
    """Strip trailing citation-style links from the end of a paragraph.

    Returns (narration_text, source_refs). Only links anchored to the literal end
    of the string (optionally followed by whitespace) are ever touched -- an
    inline link in the middle of a sentence is never modified, per the
    conservative-parsing requirement.
    """
    text = paragraph
    refs = []
    while True:
        m = _TRAILING_LINK_RE.search(text)
        if not m:
            break
        label, url = m.group(1), m.group(2)
        refs.append({"label": label.strip(), "url": url})
        text = text[: m.start()]
    refs.reverse()  # we stripped right-to-left; restore left-to-right reading order
    return text.rstrip(), refs


def parse_master_script(raw_text: str):
    """Pure parsing, no I/O. Returns (title, optional_deck, blocks) where blocks is
    a list of {"narration_text": str, "source_refs": [...]} without block_id
    assigned yet (the caller numbers them).
    """
    # Normalize line endings; don't otherwise touch whitespace inside prose.
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    title = None
    optional_deck = None
    consumed_lines = 0

    # 1. First H1, if it appears before any non-blank, non-heading content.
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx < len(lines):
        m = _H1_RE.match(lines[idx])
        if m:
            title = m.group(1)
            consumed_lines = idx + 1

            # 2. Optional deck: the next non-blank line, IF it is unambiguously one
            # whole italic span and nothing else.
            j = consumed_lines
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                candidate = lines[j].strip()
                dm = _SOLE_ITALIC_LINE_RE.match(candidate)
                if dm:
                    optional_deck = (dm.group(1) or dm.group(2)).strip()
                    consumed_lines = j + 1

    body = "\n".join(lines[consumed_lines:])

    # 3. Blank-line-separated paragraphs. Two-or-more consecutive newlines (after
    # normalizing accidental trailing whitespace on blank lines) separate blocks.
    raw_paragraphs = re.split(r"\n\s*\n+", body)

    blocks = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        # Collapse internal hard-wrapped single newlines into spaces -- a paragraph
        # is one spoken unit regardless of the upstream writer's line-wrap width.
        # This only touches whitespace, never words.
        para_joined = re.sub(r"[ \t]*\n[ \t]*", " ", para).strip()
        narration_text, source_refs = extract_trailing_source_refs(para_joined)
        blocks.append({"narration_text": narration_text, "source_refs": source_refs})

    return title, optional_deck, blocks


def parse_and_validate(script_path: Path):
    """Reads and parses script_path WITHOUT touching any episode directory.

    Call this BEFORE creating an episode directory: it's the only part of ingestion
    that can fail on malformed input (no H1 title, no narration paragraphs), so
    doing it first means a bad script never leaves a half-created, poisoned episode
    directory blocking a later retry with the same episode_id.

    Returns (raw_bytes, script_sha256, title, optional_deck, blocks) where blocks
    already have block_id assigned, in order. Raises SystemExit on malformed input.
    """
    raw_bytes = script_path.read_bytes()
    script_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    raw_text = raw_bytes.decode("utf-8")
    title, optional_deck, parsed_blocks = parse_master_script(raw_text)
    if not title:
        raise SystemExit(
            f"Could not find a Markdown H1 title (a line starting with '# ') at the top of {script_path}. "
            f"Ingestion requires the upstream script's title."
        )
    if not parsed_blocks:
        raise SystemExit(f"No narration paragraphs found in {script_path} after the title/deck.")

    blocks = []
    for i, b in enumerate(parsed_blocks, start=1):
        blocks.append({
            "block_id": f"block_{i:03d}",
            "narration_text": b["narration_text"],
            "source_refs": b["source_refs"],
        })

    return raw_bytes, script_sha256, title, optional_deck, blocks


def write_episode_files(
    episode_dir: Path,
    raw_bytes: bytes,
    script_sha256: str,
    title: str,
    optional_deck: str,
    blocks: list,
    episode_id: str,
    channel_id: str,
    language: str,
    topic: str = None,
) -> dict:
    """Writes master_script.md verbatim into episode_dir and returns the
    script_manifest dict (caller writes script_manifest.json itself). Assumes
    episode_dir already exists and parse_and_validate already succeeded -- this
    function itself should not raise on the content, only on disk/IO problems.
    """
    dest_script_path = episode_dir / "master_script.md"
    dest_script_path.write_bytes(raw_bytes)  # verbatim byte-for-byte copy, never re-serialized

    manifest = {
        "episode_id": episode_id,
        "channel_id": channel_id,
        "script_sha256": script_sha256,
        "title": title,
        "language": language,
        "status": "locked",
        "source_script_path": "master_script.md",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "blocks": blocks,
    }
    if topic:
        manifest["topic"] = topic
    if optional_deck:
        manifest["optional_deck"] = optional_deck

    return manifest


def ingest(
    script_path: Path,
    episode_dir: Path,
    episode_id: str,
    channel_id: str,
    language: str,
    topic: str = None,
) -> dict:
    """Convenience wrapper: parse_and_validate + write_episode_files, for simple
    callers where episode_dir is only created immediately before calling this (the
    CLI below). A caller managing atomicity across MULTIPLE files (like
    run_episode.py's `ingest` command, which also writes pending stubs) should call
    parse_and_validate() itself first and only create the episode directory after
    that succeeds -- see run_episode.py.
    """
    raw_bytes, script_sha256, title, optional_deck, blocks = parse_and_validate(script_path)
    episode_dir.mkdir(parents=True, exist_ok=True)
    return write_episode_files(
        episode_dir, raw_bytes, script_sha256, title, optional_deck, blocks,
        episode_id, channel_id, language, topic,
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", required=True, help="Path to master_script.md")
    parser.add_argument("--episode-dir", required=True, help="Episode directory to write master_script.md + script_manifest.json into")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--channel-id", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--topic", default=None)
    args = parser.parse_args()

    episode_dir = Path(args.episode_dir)
    # ingest() itself calls parse_and_validate() before ever touching episode_dir,
    # so a malformed script fails here without creating/poisoning the directory.
    manifest = ingest(
        script_path=Path(args.script),
        episode_dir=episode_dir,
        episode_id=args.episode_id,
        channel_id=args.channel_id,
        language=args.language,
        topic=args.topic,
    )
    out_path = episode_dir / "script_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out_path} ({len(manifest['blocks'])} blocks, sha256={manifest['script_sha256'][:12]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
