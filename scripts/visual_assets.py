#!/usr/bin/env python3
"""Deterministic tools for Claude's B-DISCOVER, independent of TTS collection.

No model calls: Claude supplies queries, selected sources, visual review and
allocations. Collection stays pending; only coverage uses measured narration.
All episode paths are relative; shared assets are copied, never linked to a
different episode. Old inventory files remain readable.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

import media_download
import media_probe
import media_search
import validate_episode

ROOT = Path(__file__).resolve().parents[1]
ASSET_TYPES = ("video", "photo", "advertisement", "brochure", "document", "magazine_scan", "map", "chart")


class VisualError(RuntimeError):
    pass


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def atomic_json(path, doc):
    data = json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".pending")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def file_lock(path):
    """Single writer, including Windows. An OS lock is released after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise VisualError("Another visual operation is active; retry after it finishes") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def inside(root, relative):
    value = Path(relative)
    result = (root / value).resolve()
    if value.is_absolute() or not result.is_relative_to(root.resolve()):
        raise VisualError("Managed media path must stay inside its episode/library")
    return result


def copy_verified(src, dest, expected):
    if sha(src) != expected:
        raise VisualError("Source checksum changed; refusing stale media/evidence")
    if dest.exists():
        if sha(dest) != expected:
            raise VisualError("Destination contains different data; refusing overwrite")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=dest.parent, suffix=".pending")
    os.close(fd)
    try:
        shutil.copyfile(src, name)
        if sha(name) != expected:
            raise VisualError("Source changed while copying")
        os.replace(name, dest)
    finally:
        Path(name).unlink(missing_ok=True)


def finite_positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def schema_check(doc):
    try:
        import jsonschema
    except ImportError:
        raise VisualError("jsonschema is required; install requirements.txt before visual collection") from None
    try:
        jsonschema.validate(doc, load(ROOT / "schemas/asset_inventory.json"))
    except jsonschema.ValidationError as exc:
        raise VisualError(f"Invalid asset inventory: {exc.message}") from None
    ids = [a["asset_id"] for a in doc["assets"]]
    if len(ids) != len(set(ids)):
        raise VisualError("Duplicate asset_id")
    report = validate_episode.Report()
    # Empty targets here intentionally validate assets/segments only.
    validate_episode.validate_block_coverage_gate({**doc, "block_coverage": []}, {}, {}, False, report)
    if report.errors:
        raise VisualError("; ".join(report.errors))


def validate_files(doc, base):
    """Managed bytes and inspection provenance; legacy unmanaged entries untouched."""
    for asset in doc.get("assets", []):
        if "source_sha256" not in asset:
            continue
        path = inside(base, asset["local_path"])
        if not path.is_file() or sha(path) != asset["source_sha256"]:
            raise VisualError(f"{asset['asset_id']}: source missing/changed; inspection is stale")
        evidence = asset.get("inspection_evidence", [])
        for frame in evidence:
            file = inside(base, frame["frame_path"])
            if not file.is_file() or sha(file) != frame["sha256"]:
                raise VisualError(f"{asset['asset_id']}: inspection evidence missing/changed")
        if asset.get("verification_method") == "visually_inspected":
            if asset.get("inspected_source_sha256") != asset["source_sha256"] or not evidence:
                raise VisualError("Visual review must be bound to this source and actual evidence")
            viewed = set(asset.get("viewed_evidence", []))
            available = {frame["frame_path"] for frame in evidence}
            if not viewed or not viewed <= available:
                raise VisualError("Visual review must identify viewed evidence")
            for segment in asset.get("usable_segments", []):
                if not any(f["frame_path"] in viewed and
                           segment["start_sec"] <= f.get("timestamp_sec", -1) < segment["end_sec"]
                           for f in evidence):
                    raise VisualError("Usable segment has no viewed frame inside its range")


def validate_managed_inventory(doc, episode):
    if doc.get("script_manifest_sha256") and sha(episode / "script_manifest.json") != doc["script_manifest_sha256"]:
        raise VisualError("Visual inventory belongs to a different locked script")
    if doc.get("script_manifest_sha256") and sha(episode / "master_script.md") != load(episode / "script_manifest.json")["script_sha256"]:
        raise VisualError("Locked master script changed after visual collection")
    if doc.get("tts_manifest_sha256") and sha(episode / "tts_manifest.json") != doc["tts_manifest_sha256"]:
        raise VisualError("Audio selection changed; recompute visual coverage before editing/rendering")
    validate_files(doc, episode)


class Workspace:
    def __init__(self, episode, library=None):
        self.episode = Path(episode).resolve()
        self.library = Path(library or ROOT / "asset_library").resolve()
        self.sm_path = self.episode / "script_manifest.json"
        self.script = load(self.sm_path)
        self.script_hash = sha(self.sm_path)
        master = self.episode / "master_script.md"
        if self.script.get("status") != "locked" or sha(master) != self.script["script_sha256"]:
            raise VisualError("Expected an unchanged, locked master script")
        self.path = self.episode / "asset_inventory.json"
        self.doc = load(self.path) if self.path.exists() else {
            "episode_id": self.script["episode_id"], "status": "pending", "assets": [], "block_coverage": []}
        if self.doc["episode_id"] != self.script["episode_id"]:
            raise VisualError("Inventory episode_id does not match the script")
        if self.doc.get("script_manifest_sha256", self.script_hash) != self.script_hash:
            raise VisualError("Inventory belongs to another locked script; refusing reuse")
        schema_check(self.doc)

    def save(self):
        if sha(self.sm_path) != self.script_hash or sha(self.episode / "master_script.md") != self.script["script_sha256"]:
            raise VisualError("Locked script changed during this operation")
        self.doc["script_manifest_sha256"] = self.script_hash
        schema_check(self.doc)
        atomic_json(self.path, self.doc)

    def mutable(self):
        edit = self.episode / "edit_plan.json"
        if self.doc.get("block_coverage") or self.doc["status"] != "pending" or (
                edit.exists() and (load(edit).get("clips") or load(edit).get("status") != "pending")):
            raise VisualError("Coverage/edit plan already exists; refusing to invalidate it silently")

    def asset(self, aid):
        asset = next((a for a in self.doc["assets"] if a["asset_id"] == aid), None)
        if asset is None:
            raise VisualError(f"Unknown asset_id: {aid}")
        validate_files({"assets": [asset]}, self.episode)
        return asset

    def index(self):
        path = self.library / "index.json"
        result = load(path) if path.exists() else {"library_version": 1, "assets": []}
        if result.get("library_version") != 1 or not isinstance(result.get("assets"), list):
            raise VisualError("Unsupported asset library index")
        return result

    def library_search(self, query):
        words = query.casefold().split()
        result = []
        for asset in self.index()["assets"]:
            haystack = " ".join(str(asset.get(k, "")) for k in ("subject", "description", "tags", "source_title")).casefold()
            if all(word in haystack for word in words):
                candidate = deepcopy(asset)
                candidate["cache_usable"] = False
                if asset.get("source_sha256"):
                    try:
                        validate_files({"assets": [asset]}, self.library)
                        candidate["cache_usable"] = True
                    except (VisualError, OSError):
                        pass
                result.append(candidate)
        return result

    def search(self, query, max_results=5, local_only=False, refresh=False):
        if not query.strip() or not 1 <= max_results <= 20:
            raise VisualError("Supply a query and max_results between 1 and 20")
        result = {"library": self.library_search(query), "candidates": [], "cached": False}
        if local_only:
            return result
        identity = json.dumps([query, max_results], ensure_ascii=False)
        key = hashlib.sha256(identity.encode()).hexdigest()
        path = self.episode / "media/search" / (key + ".json")
        if path.exists() and not refresh:
            result.update(candidates=load(path)["candidates"], cached=True)
        else:
            candidates = media_search.search_video_candidates(query, max_results)
            atomic_json(path, {"query": query, "candidates": candidates})
            result["candidates"] = candidates
        return result

    def _transfer(self, asset, source_root, dest_root):
        """Portable per-episode copies, including the evidence actually reviewed."""
        validate_files({"assets": [asset]}, source_root)
        if not re.fullmatch(r"asset_[a-f0-9]{16}", asset["asset_id"]):
            raise VisualError("Legacy entry requires local re-import before managed reuse")
        result = deepcopy(asset)
        src = inside(source_root, asset["local_path"])
        relative = f"media/raw/{asset['asset_id']}/{src.name}"
        copy_verified(src, inside(dest_root, relative), asset["source_sha256"])
        result["local_path"] = relative
        mapping = {}
        for frame in result.get("inspection_evidence", []):
            old = frame["frame_path"]
            src = inside(source_root, old)
            relative = f"media/inspection/{asset['asset_id']}/{frame['sha256']}{src.suffix}"
            copy_verified(src, inside(dest_root, relative), frame["sha256"])
            mapping[old] = relative
            frame["frame_path"] = relative
        result["viewed_evidence"] = list(dict.fromkeys(mapping[p] for p in result.get("viewed_evidence", [])))
        return result

    def reuse(self, aid):
        self.mutable()
        if any(a["asset_id"] == aid for a in self.doc["assets"]):
            return self.asset(aid)
        source = next((a for a in self.index()["assets"] if a["asset_id"] == aid), None)
        if source is None or not source.get("source_sha256"):
            raise VisualError("Shared asset is missing or not managed; import/inspect its local file first")
        asset = self._transfer(source, self.library, self.episode)
        # Inspection transfers; exact relevance to a NEW episode does not.
        asset["exact_subject_match"] = False
        self.doc["assets"].append(asset)
        self.save()
        return asset

    def add(self, asset_type, url=None, file=None):
        self.mutable()
        if asset_type not in ASSET_TYPES or bool(url) == bool(file):
            raise VisualError("Choose an asset type and exactly one of --url / --file")
        if url:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
                raise VisualError("Use a public HTTP(S) source URL without embedded credentials")
            for existing in self.doc["assets"]:
                if existing.get("source_url") == url:
                    if existing["asset_type"] != asset_type:
                        raise VisualError("Source already imported with a different asset type")
                    return self.asset(existing["asset_id"])
            for cached in self.index()["assets"]:
                if cached.get("source_url") == url and cached.get("source_sha256"):
                    if cached["asset_type"] != asset_type:
                        raise VisualError("Shared source has a different asset type")
                    return self.reuse(cached["asset_id"])
            key = hashlib.sha256(url.encode()).hexdigest()
        else:
            file = Path(file).resolve()
            key = sha(file)
        aid = "asset_" + key[:16]
        if any(a["asset_id"] == aid for a in self.doc["assets"]):
            existing = self.asset(aid)
            if existing["asset_type"] != asset_type:
                raise VisualError("Source already imported with a different asset type")
            return existing
        dest = self.episode / "media/raw" / aid
        if file:
            path = dest / ("source" + file.suffix.lower())
            copy_verified(file, path, key)
        else:
            receipt = dest / "download.json"
            if receipt.exists():
                record = load(receipt)
                path = inside(dest, record["filename"])
                if record["url"] != url or sha(path) != record["sha256"]:
                    raise VisualError("Download receipt/source mismatch; refusing overwrite")
            else:
                fetched = (media_download.download_video(url, dest) if asset_type == "video"
                           else media_download.download_direct_asset(url, dest))
                path = Path(fetched["local_path"])
                if not path.resolve().is_relative_to(dest.resolve()):
                    raise VisualError("Downloader returned a path outside its destination")
                atomic_json(receipt, {"url": url, "filename": path.name, "sha256": sha(path)})
        info = media_probe.probe(str(path))
        if not info.get("width") or not info.get("height"):
            raise VisualError("Not a decodable visual asset; PDF documents need a raster page image first")
        if asset_type == "video" and not finite_positive(info.get("duration_sec")):
            raise VisualError("Video has no measured duration")
        asset = {"asset_id": aid, "asset_type": asset_type, "subject": "Awaiting visual review",
                 "description": "Downloaded/imported; content not yet visually inspected",
                 "exact_subject_match": False, "access_status": "read_full",
                 "verification_method": "unverified", "visual_quality": "unknown", "reusable": False,
                 "license": "unknown", "local_path": path.relative_to(self.episode).as_posix(),
                 "source_sha256": sha(path), "tags": []}
        if url:
            asset["source_url"] = url
        if asset_type == "video":
            asset.update(duration_sec=info["duration_sec"], usable_segments=[])
        self.doc["assets"].append(asset)
        self.save()
        return asset

    def inspect(self, aid, start=None, end=None):
        self.mutable()
        asset = self.asset(aid)
        if not asset.get("source_sha256"):
            raise VisualError("Legacy asset: import the source with visual add first")
        source = inside(self.episode, asset["local_path"])
        if (start is None) != (end is None):
            raise VisualError("Supply both --start and --end, or neither")
        if asset["asset_type"] == "video":
            out = self.episode / "media/inspection"
            frames = (media_probe.coarse_contact_sheet(str(source), str(out)) if start is None else
                      media_probe.fine_contact_sheet(str(source), start, end, str(out)))
        else:
            if start is not None:
                raise VisualError("A still image has no source time window")
            frames = [{"frame_path": str(source)}]
        records = []
        for frame in frames:
            p = Path(frame["frame_path"])
            records.append({**frame, "frame_path": p.relative_to(self.episode).as_posix(), "sha256": sha(p)})
        by_path = {f["frame_path"]: f for f in asset.get("inspection_evidence", [])}
        by_path.update({f["frame_path"]: f for f in records})
        asset["inspection_evidence"] = list(by_path.values())
        if sha(source) != asset["source_sha256"]:
            raise VisualError("Source changed during inspection")
        self.save()
        return {"asset_id": aid, "frames_to_view": records,
                "note": "Generating frames is NOT visual verification. Claude must view them and submit a review."}

    def review(self, aid, review):
        self.mutable()
        asset = self.asset(aid)
        allowed = {"subject", "description", "exact_subject_match", "visual_quality", "usable_segments",
                   "license", "reusable", "tags", "viewed_evidence", "notes", "date_or_period", "source_title"}
        if not {"subject", "description", "viewed_evidence"} <= review.keys() or review.keys() - allowed:
            raise VisualError("Review requires subject, description, viewed_evidence and only documented review fields")
        asset.update(deepcopy(review), verification_method="visually_inspected",
                     inspected_source_sha256=asset.get("source_sha256"))
        schema_check(self.doc)
        validate_files({"assets": [asset]}, self.episode)
        self.save()
        return asset

    def publish(self, aid):
        asset = self.asset(aid)
        if asset["verification_method"] != "visually_inspected" or not asset.get("reusable"):
            raise VisualError("Only explicitly reviewed, reusable assets can enter the shared cache")
        if not asset.get("source_sha256"):
            raise VisualError("Legacy asset requires managed import and inspection")
        with file_lock(self.library / ".visual.lock"):
            index = self.index()
            shared = self._transfer(asset, self.episode, self.library)
            shared["exact_subject_match"] = False
            matches = [a for a in index["assets"] if a["asset_id"] == aid]
            if matches and matches[0].get("source_sha256") != shared["source_sha256"]:
                raise VisualError("Shared asset identity collision")
            index["assets"] = [a for a in index["assets"] if a["asset_id"] != aid] + [shared]
            atomic_json(self.library / "index.json", index)
        return shared

    def timings(self):
        from tts_gemini_chunks import alignment_gate
        gate = alignment_gate(self.episode)
        if gate:
            raise VisualError(f"{gate}; collection is allowed, coverage/B-EDIT is blocked")
        path = self.episode / "tts_manifest.json"
        if not path.exists():
            raise VisualError("TTS REQUIRED; collection is allowed")
        timing_hash = sha(path)
        tts = load(path)
        report = validate_episode.Report()
        durations, complete = validate_episode.validate_tts_manifest(
            tts, {b["block_id"]: b for b in self.script["blocks"]}, report)
        if not complete or report.errors or tts.get("episode_id") != self.script["episode_id"]:
            raise VisualError("TTS REQUIRED; every block needs a measured duration")
        for block in tts["blocks"]:
            if not finite_positive(block.get("duration_sec")):
                raise VisualError("Non-finite or non-positive narration duration")
            measured = media_probe.probe(str(inside(self.episode, block["audio_path"]))).get("duration_sec")
            if not finite_positive(measured) or abs(measured - block["duration_sec"]) > 0.05:
                raise VisualError("Narration file does not match its measured duration")
        if sha(path) != timing_hash:
            raise VisualError("Audio selection changed during measurement; retry coverage")
        return durations, timing_hash

    def coverage(self, plan):
        edit_path = self.episode / "edit_plan.json"
        if edit_path.exists() and (load(edit_path).get("clips") or load(edit_path).get("status") != "pending"):
            raise VisualError("An edit plan already exists; refusing to replace its coverage")
        durations, tts_hash = self.timings()
        if not isinstance(plan, list) or any(not isinstance(p, dict) or set(p) != {"block_id", "allocations"} for p in plan):
            raise VisualError("Coverage input is a list of {block_id, allocations}; no guessed target times")
        ids = [p["block_id"] for p in plan]
        if len(ids) != len(set(ids)) or set(ids) != set(durations):
            raise VisualError("Supply exactly one allocation entry per script block, including empty gaps")
        entries = {p["block_id"]: p for p in plan}
        coverage = []
        for block in self.script["blocks"]:
            bid = block["block_id"]
            allocations = entries[bid]["allocations"]
            if not isinstance(allocations, list):
                raise VisualError("allocations must be a list")
            for alloc in allocations:
                if not isinstance(alloc, dict) or not finite_positive(alloc.get("planned_sec")):
                    raise VisualError("Allocation duration must be finite and positive")
                if self.asset(alloc.get("asset_id"))["verification_method"] != "visually_inspected":
                    raise VisualError("Only visually inspected assets may be allocated")
            total = sum(a["planned_sec"] for a in allocations)
            ratio = total / durations[bid]
            coverage.append({"block_id": bid, "target_visual_sec": durations[bid], "planned_visual_sec": total,
                             "coverage_ratio": ratio, "coverage_status": validate_episode._expected_coverage_status(ratio),
                             "allocations": allocations})
        proposed = {**self.doc, "block_coverage": coverage, "status": "gathered", "tts_manifest_sha256": tts_hash}
        schema_check(proposed)
        report = validate_episode.Report()
        gate = validate_episode.validate_block_coverage_gate(proposed, durations, durations, True, report)
        if report.errors:
            raise VisualError("; ".join(report.errors))
        proposed["status"] = "gathered" if gate else "pending"
        validate_managed_inventory(proposed, self.episode)
        self.doc = proposed
        self.save()
        return {"status": self.doc["status"], "b_edit_allowed": gate, "block_coverage": coverage}

    def reopen(self):
        edit = self.episode / "edit_plan.json"
        if edit.exists() and (load(edit).get("clips") or load(edit).get("status") != "pending"):
            raise VisualError("An edit plan exists; reopening would invalidate it")
        # Explicit recovery action for more discovery after a partial coverage pass.
        # Preserve the old allocation plan so Claude can reuse it after filling gaps.
        key = hashlib.sha256(json.dumps(self.doc, sort_keys=True).encode()).hexdigest()[:16]
        backup = self.episode / "media/coverage_history" / (key + ".json")
        atomic_json(backup, self.doc)
        self.doc.update(status="pending", block_coverage=[])
        self.doc.pop("tts_manifest_sha256", None)
        self.save()
        return {"collection": "AVAILABLE", "previous_coverage": str(backup), "assets_preserved": len(self.doc["assets"])}

    def status(self):
        validate_managed_inventory(self.doc, self.episode)
        try:
            self.timings()
            timing_state = "MEASURED BLOCK TIMINGS READY"
        except (VisualError, media_probe.MediaProbeError, OSError) as exc:
            timing_state = f"COVERAGE NOT READY: {exc}"
        return {"episode_id": self.script["episode_id"], "collection": "AVAILABLE",
                "assets": len(self.doc["assets"]),
                "reviewed": sum(a["verification_method"] == "visually_inspected" for a in self.doc["assets"]),
                "timing_state": timing_state, "inventory_status": self.doc["status"],
                "script_manifest": str(self.sm_path), "agent_instructions": "agents/agent_b_archive_visual_editor.md"}


def add_parser(subparsers):
    parser = subparsers.add_parser("visual", help="Claude's reusable visual collection tools; no TTS/API key required")
    commands = parser.add_subparsers(dest="visual_action", required=True)
    for action in ("status", "search", "add", "inspect", "review", "publish", "reuse", "coverage", "reopen"):
        p = commands.add_parser(action)
        p.add_argument("episode", help="episode_id or path")
        if action == "search":
            p.add_argument("--query", required=True)
            p.add_argument("--max-results", type=int, default=5)
            p.add_argument("--local-only", action="store_true")
            p.add_argument("--refresh", action="store_true")
        elif action == "add":
            p.add_argument("--type", dest="asset_type", choices=ASSET_TYPES, required=True)
            source = p.add_mutually_exclusive_group(required=True)
            source.add_argument("--url")
            source.add_argument("--file")
        elif action in ("inspect", "review", "publish", "reuse"):
            p.add_argument("--asset", required=True)
            if action == "inspect":
                p.add_argument("--start", type=float)
                p.add_argument("--end", type=float)
            if action == "review":
                p.add_argument("--review", required=True, help="JSON review authored by Claude after viewing evidence")
        elif action == "coverage":
            p.add_argument("--plan", required=True, help="Claude's allocation JSON; targets are measured automatically")


def run(args, episode):
    try:
        with file_lock(Path(episode) / ".visual.lock"):
            workspace = Workspace(episode)
            action = args.visual_action
            if action == "status":
                result = workspace.status()
            elif action == "search":
                result = workspace.search(args.query, args.max_results, args.local_only, args.refresh)
            elif action == "add":
                result = workspace.add(args.asset_type, args.url, args.file)
            elif action == "inspect":
                result = workspace.inspect(args.asset, args.start, args.end)
            elif action == "review":
                result = workspace.review(args.asset, load(args.review))
            elif action == "publish":
                result = workspace.publish(args.asset)
            elif action == "reuse":
                result = workspace.reuse(args.asset)
            elif action == "reopen":
                result = workspace.reopen()
            else:
                result = workspace.coverage(load(args.plan))
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (VisualError, media_probe.MediaProbeError, media_search.MediaSearchError,
            media_download.MediaDownloadError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"visual error: {exc}")
        return 1
