"""Generic, offline visual pipeline tests. Real ffmpeg/ffprobe media and render;
only external search/download are mocked. No Gemini requests or credentials.
"""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import visual_assets as v
import media_probe
import media_download
import media_search
import render_episode
import run_episode


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
class Visuals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixtures.cleanup)
        cls.video = Path(cls.fixtures.name) / "source.mp4"
        cls.photo = Path(cls.fixtures.name) / "source.png"
        for dest, extra in ((cls.video, ["-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p"]),
                            (cls.photo, ["-frames:v", "1", "-threads", "1"])):
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                            *extra, str(dest)], check=True, capture_output=True, timeout=30)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.lib = self.root / "shared"
        self.ep = self.episode("IndustryTH_semiconductors", "โรงงานเซมิคอนดักเตอร์")

    def episode(self, name, subject):
        ep = self.root / name
        ep.mkdir()
        (ep / "master_script.md").write_text(f"# {subject}\n\nตอนแรก\n\nตอนต่อมา\n", encoding="utf-8")
        v.atomic_json(ep / "script_manifest.json", {
            "episode_id": name, "channel_id": name.split("_")[0], "script_sha256": v.sha(ep / "master_script.md"),
            "title": subject, "language": "th", "status": "locked", "source_script_path": "master_script.md",
            "blocks": [{"block_id": "block_001", "narration_text": "ตอนแรก", "source_refs": []},
                       {"block_id": "block_002", "narration_text": "ตอนต่อมา", "source_refs": []}]})
        for file, field in (("tts_manifest", "blocks"), ("edit_plan", "clips")):
            v.atomic_json(ep / f"{file}.json", {"episode_id": name, "status": "pending", field: []})
        v.atomic_json(ep / "asset_inventory.json", {"episode_id": name, "status": "pending", "assets": [], "block_coverage": []})
        return ep

    def ws(self, ep=None):
        return v.Workspace(ep or self.ep, self.lib)

    def reviewed(self, photo=False):
        asset = self.ws().add("photo" if photo else "video", file=self.photo if photo else self.video)
        aid = asset["asset_id"]
        evidence = self.ws().inspect(aid)["frames_to_view"]
        review = {"subject": "Factory / โรงงาน", "description": "Test source actually inspected",
                  "exact_subject_match": True, "visual_quality": "high", "reusable": True,
                  "tags": ["factory", "โรงงาน"], "viewed_evidence": [f["frame_path"] for f in evidence]}
        if not photo:
            review["usable_segments"] = [{"segment_id": aid + "_s1", "start_sec": 0, "end_sec": 2}]
        return self.ws().review(aid, review)

    def audio(self):
        folder = self.ep / "audio/fixture"
        folder.mkdir(parents=True, exist_ok=True)
        entries = []
        for bid in ("block_001", "block_002"):
            path = folder / (bid + ".wav")
            with wave.open(str(path), "wb") as stream:
                stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\x00\x00" * 24000)
            entries.append({"block_id": bid, "audio_path": path.relative_to(self.ep).as_posix(), "duration_sec": 1.0})
        v.atomic_json(self.ep / "tts_manifest.json", {"episode_id": self.ep.name, "status": "generated", "blocks": entries})

    def plan(self, asset, second=1):
        allocation = {"asset_id": asset["asset_id"], "planned_sec": 1, "relevance": "contextual"}
        if asset["asset_type"] == "video":
            allocation["segment_id"] = asset["usable_segments"][0]["segment_id"]
        return [{"block_id": "block_001", "allocations": [allocation]},
                {"block_id": "block_002", "allocations": [{**allocation, "planned_sec": second}] if second else []}]

    def test_collection_before_tts_no_key_no_narration_edits(self):
        before = {f: (self.ep / f).read_bytes() for f in ("master_script.md", "script_manifest.json", "tts_manifest.json", "edit_plan.json")}
        with patch.dict(os.environ, {}, clear=True):
            self.reviewed()
        state = self.ws().status()
        self.assertEqual((state["collection"], state["reviewed"], state["inventory_status"]), ("AVAILABLE", 1, "pending"))
        self.assertIn("TTS REQUIRED", state["timing_state"])
        for file, content in before.items():
            self.assertEqual((self.ep / file).read_bytes(), content)
        self.assertEqual(v.load(self.ep / "asset_inventory.json")["block_coverage"], [])

    def test_repeat_import_is_idempotent_and_types_cannot_drift(self):
        a = self.ws().add("video", file=self.video)
        self.assertEqual(self.ws().add("video", file=self.video), a)
        with self.assertRaises(v.VisualError):
            self.ws().add("photo", file=self.video)
        self.assertEqual(len(self.ws().doc["assets"]), 1)

    def test_extracted_frames_do_not_verify_the_source(self):
        asset = self.ws().add("video", file=self.video)
        result = self.ws().inspect(asset["asset_id"])
        self.assertTrue(result["frames_to_view"])
        asset = self.ws().asset(asset["asset_id"])
        self.assertEqual(asset["verification_method"], "unverified")
        self.assertFalse(asset["exact_subject_match"])
        self.assertEqual(asset["usable_segments"], [])

    def test_review_requires_real_viewed_evidence(self):
        a = self.ws().add("video", file=self.video)
        before = (self.ep / "asset_inventory.json").read_bytes()
        with self.assertRaises(v.VisualError):
            self.ws().review(a["asset_id"], {"subject": "test", "description": "test", "viewed_evidence": ["fake.jpg"]})
        self.assertEqual((self.ep / "asset_inventory.json").read_bytes(), before)

    def test_invalid_segments_and_unviewed_ranges_are_rejected(self):
        a = self.reviewed()
        for start, end in ((-1, 1), (0, 3), (1.8, 1.9), (1, 1)):
            with self.subTest(start=start, end=end), self.assertRaises(v.VisualError):
                self.ws().review(a["asset_id"], {"subject": "test", "description": "test", "viewed_evidence": a["viewed_evidence"],
                    "usable_segments": [{"segment_id": "bad", "start_sec": start, "end_sec": end}]})

    def test_stills_supported_and_rights_not_invented(self):
        a = self.reviewed(photo=True)
        self.assertEqual(a["license"], "unknown")
        self.assertNotIn("duration_sec", a)
        self.audio()
        self.assertTrue(self.ws().coverage(self.plan(a))["b_edit_allowed"])

    def test_reuse_across_topics_and_channels_is_portable(self):
        a = self.reviewed()
        published = self.ws().publish(a["asset_id"])
        ep2 = self.episode("HistoryEN_trade-routes", "Trade routes")
        reused = self.ws(ep2).reuse(a["asset_id"])
        self.assertFalse(reused["exact_subject_match"])
        self.assertEqual(reused["verification_method"], "visually_inspected")
        self.assertEqual(reused["usable_segments"], a["usable_segments"])
        v.validate_files({"assets": [reused]}, ep2)
        # Independent copies survive deletion/mutation in the original episode.
        (self.ep / a["local_path"]).write_bytes(b"changed original")
        v.validate_files({"assets": [reused]}, ep2)
        v.validate_files({"assets": [published]}, self.lib)
        self.assertTrue(all(not Path(f["frame_path"]).is_absolute() for f in reused["inspection_evidence"]))

    def test_publish_is_idempotent_and_keyword_search_supports_thai(self):
        a = self.reviewed()
        self.ws().publish(a["asset_id"])
        self.ws().publish(a["asset_id"])
        self.assertEqual(len(self.ws().index()["assets"]), 1)
        with patch.object(media_search, "search_video_candidates", side_effect=AssertionError("network called")):
            found = self.ws().search("โรงงาน", local_only=True)
        self.assertEqual(found["library"][0]["asset_id"], a["asset_id"])
        self.assertTrue(found["library"][0]["cache_usable"])

    def test_unverified_asset_cannot_be_published(self):
        a = self.ws().add("video", file=self.video)
        with self.assertRaises(v.VisualError):
            self.ws().publish(a["asset_id"])

    def test_changed_source_or_frame_invalidates_review(self):
        a = self.reviewed()
        frame = self.ep / a["inspection_evidence"][0]["frame_path"]
        frame.write_bytes(b"changed")
        with self.assertRaisesRegex(v.VisualError, "evidence"):
            self.ws().status()

    def test_changed_source_rejected_before_reinspection(self):
        a = self.reviewed()
        (self.ep / a["local_path"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(v.VisualError, "source missing/changed"):
            self.ws().inspect(a["asset_id"])

    def test_corrupt_shared_cache_not_reported_usable_or_silently_replaced(self):
        a = self.reviewed()
        shared = self.ws().publish(a["asset_id"])
        (self.lib / shared["local_path"]).write_bytes(b"corrupt")
        self.assertFalse(self.ws().library_search("factory")[0]["cache_usable"])
        ep2 = self.episode("CarsTH_trucks", "Trucks")
        with self.assertRaises(v.VisualError):
            self.ws(ep2).reuse(a["asset_id"])

    def test_search_is_cached_and_does_not_download_candidates(self):
        with patch.object(media_search, "search_video_candidates", return_value=[{"title": "โรงงาน", "webpage_url": "https://example.org/video"}]) as search:
            with patch.object(media_download, "download_video", side_effect=AssertionError("download called")):
                self.ws().search("โรงงาน")
                self.assertTrue(self.ws().search("โรงงาน")["cached"])
                self.ws().search("โรงงาน", refresh=True)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(self.ws().doc["assets"], [])

    def test_failed_search_can_retry(self):
        with patch.object(media_search, "search_video_candidates", side_effect=media_search.MediaSearchError("offline")):
            with self.assertRaises(media_search.MediaSearchError):
                self.ws().search("factory")
        with patch.object(media_search, "search_video_candidates", return_value=[]) as search:
            self.ws().search("factory")
        search.assert_called_once()

    def test_selected_download_resumes_without_second_request(self):
        def download(url, dest):
            dest.mkdir(parents=True)
            path = dest / "source.mp4"
            shutil.copyfile(self.video, path)
            return {"local_path": str(path)}
        with patch.object(media_download, "download_video", side_effect=download) as fetch:
            a = self.ws().add("video", url="https://example.org/selected")
            self.assertEqual(self.ws().add("video", url="https://example.org/selected"), a)
        fetch.assert_called_once()

    def test_download_receipt_recovers_after_probe_failure(self):
        def download(url, dest):
            dest.mkdir(parents=True)
            shutil.copyfile(self.video, dest / "source.mp4")
            return {"local_path": str(dest / "source.mp4")}
        with patch.object(media_download, "download_video", side_effect=download) as fetch:
            with patch.object(media_probe, "probe", side_effect=media_probe.MediaProbeError("temporary")):
                with self.assertRaises(media_probe.MediaProbeError):
                    self.ws().add("video", url="https://example.org/selected")
            self.ws().add("video", url="https://example.org/selected")
        fetch.assert_called_once()

    def test_path_traversal_and_embedded_credentials_rejected(self):
        for path in ("../secret", str(self.root / "outside")):
            with self.assertRaises(v.VisualError):
                v.inside(self.ep, path)
        for url in ("file:///tmp/source", "https://user:secret@example.org/source", "--config-location"):
            with self.assertRaises(v.VisualError):
                self.ws().add("video", url=url)

    def test_script_identity_change_rejected(self):
        self.ws().add("video", file=self.video)
        sm = v.load(self.ep / "script_manifest.json")
        sm["blocks"][0]["narration_text"] = "changed"
        v.atomic_json(self.ep / "script_manifest.json", sm)
        with self.assertRaisesRegex(v.VisualError, "another locked script"):
            self.ws()

    def test_master_change_blocks_downstream_integrity_check(self):
        self.ws().add("video", file=self.video)
        doc = v.load(self.ep / "asset_inventory.json")
        (self.ep / "master_script.md").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(v.VisualError, "master script changed"):
            v.validate_managed_inventory(doc, self.ep)

    def test_coverage_requires_audio_and_preserves_pending_inventory(self):
        a = self.reviewed()
        before = (self.ep / "asset_inventory.json").read_bytes()
        with self.assertRaisesRegex(v.VisualError, "TTS REQUIRED"):
            self.ws().coverage(self.plan(a))
        self.assertEqual((self.ep / "asset_inventory.json").read_bytes(), before)

    def test_missing_audio_does_not_hide_collection_readiness(self):
        self.audio()
        (self.ep / "audio/fixture/block_001.wav").unlink()
        state = self.ws().status()
        self.assertEqual(state["collection"], "AVAILABLE")
        self.assertIn("COVERAGE NOT READY", state["timing_state"])

    def test_gemini_gate_blocks_coverage_but_not_collection(self):
        self.audio()
        v.atomic_json(self.ep / "tts_chunks.json", {"manifest_path": "missing.json", "alignment_status": "required"})
        a = self.reviewed()
        with self.assertRaises(v.VisualError):
            self.ws().coverage(self.plan(a))
        self.assertEqual(self.ws().status()["reviewed"], 1)

    def test_coverage_uses_measured_times_and_reports_real_gaps(self):
        a = self.reviewed()
        self.audio()
        result = self.ws().coverage(self.plan(a, second=0))
        self.assertFalse(result["b_edit_allowed"])
        self.assertEqual(result["block_coverage"][1]["coverage_status"], "critical_gap")
        reopened = self.ws().reopen()
        self.assertTrue(Path(reopened["previous_coverage"]).is_file())
        self.assertEqual(reopened["assets_preserved"], 1)
        result = self.ws().coverage(self.plan(a))
        self.assertTrue(result["b_edit_allowed"])
        self.assertEqual([b["target_visual_sec"] for b in result["block_coverage"]], [1, 1])

    def test_coverage_rejects_guessed_targets_unknown_blocks_and_infinite_allocations(self):
        a = self.reviewed()
        self.audio()
        bad = self.plan(a)
        bad[0]["target_visual_sec"] = 99
        plans = [bad, self.plan(a)[:1], self.plan(a) + self.plan(a)[:1], self.plan(a, float("nan"))]
        for plan in plans:
            with self.subTest(plan=plan), self.assertRaises(v.VisualError):
                self.ws().coverage(plan)

    def test_coverage_rejects_forged_audio_duration(self):
        a = self.reviewed()
        self.audio()
        tts = v.load(self.ep / "tts_manifest.json")
        tts["blocks"][0]["duration_sec"] = 0.1
        v.atomic_json(self.ep / "tts_manifest.json", tts)
        with self.assertRaisesRegex(v.VisualError, "does not match"):
            self.ws().coverage(self.plan(a))

    def test_audio_switch_invalidates_existing_coverage(self):
        a = self.reviewed()
        self.audio()
        self.ws().coverage(self.plan(a))
        tts = v.load(self.ep / "tts_manifest.json")
        tts["blocks"].reverse()
        v.atomic_json(self.ep / "tts_manifest.json", tts)
        with self.assertRaisesRegex(v.VisualError, "Audio selection changed"):
            self.ws().status()
        self.assertEqual(run_episode.compute_status(self.ep), "B-DISCOVER REQUIRED")
        with self.assertRaisesRegex(render_episode.RenderError, "Audio selection changed"):
            render_episode.render_episode(self.ep)

    def test_no_collection_changes_after_edit_plan(self):
        a = self.reviewed()
        v.atomic_json(self.ep / "edit_plan.json", {"episode_id": self.ep.name, "status": "planned", "clips": []})
        with self.assertRaises(v.VisualError):
            self.ws().inspect(a["asset_id"])
        with self.assertRaises(v.VisualError):
            self.ws().reopen()

    def test_real_end_to_end_visual_render(self):
        a = self.reviewed()
        self.audio()
        self.ws().coverage(self.plan(a))
        clips = [{"clip_id": f"clip_{i}", "block_id": f"block_{i+1:03}", "asset_id": a["asset_id"],
                  "segment_id": a["usable_segments"][0]["segment_id"],
                  "timeline_start_sec": i, "timeline_end_sec": i + 1,
                  "source_start_sec": i, "source_end_sec": i + 1} for i in range(2)]
        v.atomic_json(self.ep / "edit_plan.json", {"episode_id": self.ep.name, "status": "planned", "clips": clips})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(run_episode.run_validate(self.ep, True), 0)
        result = render_episode.render_episode(self.ep)
        info = media_probe.probe(str(result))
        self.assertEqual((info["width"], info["height"]), (1920, 1080))
        self.assertAlmostEqual(info["duration_sec"], 2, delta=0.15)


class Helpers(unittest.TestCase):
    def test_sampling_rejects_invalid_values_without_spawning(self):
        for args in ((float("nan"), 25, 1), (10, 0, 1), (10, 1000, 1), (10, 25, 0), (10, 25, float("inf"))):
            with self.subTest(args=args), self.assertRaises(media_probe.MediaProbeError):
                media_probe.compute_sample_interval(*args)

    def test_invalid_windows_rejected(self):
        for start, end in ((-1, 2), (3, 2), (0, 11), (float("nan"), 2)):
            with patch.object(media_probe, "probe", return_value={"duration_sec": 10}):
                with self.subTest(start=start, end=end), self.assertRaises(media_probe.MediaProbeError):
                    media_probe.fine_contact_sheet("video", start, end, "out")

    def test_same_process_second_writer_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".visual.lock"
            with v.file_lock(path):
                with self.assertRaises(v.VisualError), v.file_lock(path):
                    pass
            with v.file_lock(path):
                pass

    def test_download_recognizes_existing_yt_dlp_output(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "cached.mp4"
            video.write_bytes(b"existing")
            completed = subprocess.CompletedProcess([], 0, str(video) + "\n", "")
            with patch.object(media_download, "_require_yt_dlp"), patch.object(media_download.subprocess, "run", return_value=completed) as run:
                result = media_download.download_video("https://example.org/test", folder)
            self.assertEqual(result["filename"], "cached.mp4")
            self.assertIn("after_move:filepath", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_cli_commands_are_registered(self):
        with patch.object(sys, "argv", ["run_episode.py", "visual", "--help"]), redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as exit_code:
                run_episode.main()
        self.assertEqual(exit_code.exception.code, 0)
        self.assertIn("coverage", out.getvalue())


if __name__ == "__main__":
    unittest.main()
