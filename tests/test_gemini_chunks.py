"""Paid endpoint mocked; real PCM/WAV, ffprobe, files and child-process timeout."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import ModuleType, SimpleNamespace
from contextlib import redirect_stderr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import tts_gemini_chunks as g
import tts_render
import run_episode
import render_episode


def pcm(seconds=1):
    return b"\x01\x00" * int(g.RATE * seconds)


class Chunks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ep = Path(self.tmp.name)
        self.raw = {"provider": "gemini-tts", "voice": "Charon"}
        self.script(["รถคันแรกยังใช้งานได้", "รถอีกคันกลับบ้านได้"])

    def script(self, texts):
        master = ("\n\n".join(texts)).encode()
        (self.ep / "master_script.md").write_bytes(master)
        self.sm = {"episode_id": "ForeignCarsTH_test", "channel_id": "ForeignCarsTH",
                   "script_sha256": g.digest(master), "blocks": [
                       {"block_id": f"block_{i:03}", "narration_text": text} for i, text in enumerate(texts, 1)]}
        g.atomic_json(self.ep / "script_manifest.json", self.sm)
        # Previous measured timings must neither be overwritten nor open discovery.
        g.atomic_json(self.ep / "tts_manifest.json", {"episode_id": self.sm["episode_id"], "status": "generated",
            "blocks": [{"block_id": b["block_id"], "audio_path": "old.mp3", "duration_sec": 9} for b in self.sm["blocks"]]})

    def run_chunks(self, request=None, **kwargs):
        with redirect_stdout(io.StringIO()):
            return g.render_chunks(self.ep, self.raw, request=request or (lambda *args: pcm()), **kwargs)

    def test_cleanup_exact_approved_rules(self):
        text = 'Caption (Thesis): รถที่ Toyota ยอมทำให้ “ล้าสมัย” อยู่เสมอ—เพราะ  ต้องกลับบ้าน'
        self.assertEqual(g.clean_text(text), 'รถที่ Toyota ยอมทำให้ ล้าสมัย อยู่เสมอ, เพราะ ต้องกลับบ้าน')
        self.assertEqual(g.clean_text('รหัส A_B #3 ราคา 1.5 บาท'), 'รหัส A_B #3 ราคา 1.5 บาท')

    def test_multiblock_and_continuity(self):
        result = self.run_chunks()
        chunk = result['manifest']['chunks'][0]
        self.assertEqual(chunk['block_ids'], ['block_001', 'block_002'])
        self.assertEqual(chunk['duration_sec'], 1)
        self.assertIn('Paragraph endings are not conclusions', result['manifest']['config']['continuity_instruction'])

    def test_adjacent_short_blocks_pack_near_target(self):
        self.script(['ก' * 750] * 4)
        plan = self.run_chunks(dry_run=True)
        self.assertEqual([len(c['block_ids']) for c in plan['chunks']], [2, 2])
        self.assertTrue(all(c['estimated_duration_sec'] <= 120 for c in plan['chunks']))

    def test_no_api_or_writes_in_dry_run(self):
        before = {p.name: p.read_bytes() for p in self.ep.iterdir()}
        with patch.dict(os.environ, {}, clear=True):
            result = g.render_chunks(self.ep, self.raw, dry_run=True)
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.ep.iterdir()})

    def test_missing_key_leaves_all_files_untouched(self):
        before = {p.name: p.read_bytes() for p in self.ep.iterdir()}
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(g.ChunkError, 'GEMINI_API_KEY'):
            g.render_chunks(self.ep, self.raw)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.ep.iterdir()})

    def test_master_hash_mismatch_fails_before_api(self):
        (self.ep / 'master_script.md').write_text('changed')
        with self.assertRaisesRegex(g.ChunkError, 'hash'):
            self.run_chunks()
        self.assertFalse((self.ep / 'audio').exists())

    def test_preserves_locked_sources_and_old_manifest(self):
        before = {name: (self.ep / name).read_bytes() for name in ('master_script.md', 'script_manifest.json', 'tts_manifest.json')}
        self.run_chunks()
        self.assertEqual(before, {name: (self.ep / name).read_bytes() for name in before})

    def test_resume_calls_no_api_and_reprobes_audio(self):
        self.run_chunks()
        def forbidden(*args):
            self.fail('A completed chunk was synthesized again')
        self.assertTrue(self.run_chunks(forbidden)['complete'])

    def test_orphan_salvage_after_receipt_before_manifest(self):
        result = self.run_chunks()
        manifest = g.read_json(result['manifest_path'])
        for chunk in manifest['chunks']:
            chunk['status'] = 'pending'
            for name in ('audio_path', 'audio_sha256', 'duration_sec'):
                del chunk[name]
        manifest['status'] = 'pending'
        g.atomic_json(result['manifest_path'], manifest)
        def forbidden(*args):
            self.fail('Orphan receipt/WAV was not salvaged')
        self.assertTrue(self.run_chunks(forbidden)['complete'])

    def test_truncated_but_probeable_wav_is_not_reused(self):
        result = self.run_chunks()
        chunk = result['manifest']['chunks'][0]
        path = self.ep / chunk['audio_path']
        path.write_bytes(path.read_bytes()[:-200])
        # Even a matching checksum cannot override incomplete sample data.
        receipt = g.read_json(path.with_suffix('.receipt.json'))
        receipt['audio_sha256'] = g.digest(path.read_bytes())
        g.atomic_json(path.with_suffix('.receipt.json'), receipt)
        calls = []
        self.run_chunks(lambda *args: calls.append(1) or pcm())
        self.assertEqual(calls, [1])

    def test_checksum_mismatch_regenerates(self):
        result = self.run_chunks()
        path = self.ep / result['manifest']['chunks'][0]['audio_path']
        data = bytearray(path.read_bytes());data[-1] ^= 1;path.write_bytes(data)
        calls = []
        self.run_chunks(lambda *args: calls.append(1) or pcm())
        self.assertEqual(calls, [1])

    def test_failure_preserves_previous_chunks_and_resumes_only_failed(self):
        self.script(['ก' * 1400, 'ข' * 1400])
        def first(cfg, text, timeout):
            if text.startswith('ข'):
                raise g.ChunkError('temporary failure')
            return pcm()
        result = self.run_chunks(first)
        self.assertFalse(result['complete'])
        self.assertEqual([c['status'] for c in result['manifest']['chunks']], ['generated', 'failed'])
        calls = []
        result = self.run_chunks(lambda cfg, text, timeout: calls.append(text) or pcm())
        self.assertTrue(result['complete'])
        self.assertEqual(calls, ['ข' * 1400])

    def test_rate_limit_stops_without_attempting_remaining_chunks_then_resumes(self):
        self.script(['ก' * 1400, 'ข' * 1400, 'ค' * 1400])
        calls = []
        def limited(cfg, text, timeout):
            calls.append(text)
            if len(calls) == 2:
                raise g.RateLimited('Gemini request failed: RateLimitError')
            return pcm()
        result = self.run_chunks(limited)
        self.assertFalse(result['complete'])
        self.assertEqual(len(calls), 2)
        self.assertEqual([c['status'] for c in result['manifest']['chunks']],
                         ['generated', 'pending', 'pending'])
        self.assertIn('RateLimitError', result['manifest']['chunks'][1]['deferred_reason'])
        self.assertNotIn('deferred_reason', result['manifest']['chunks'][2])

        resumed = []
        result = self.run_chunks(lambda cfg, text, timeout: resumed.append(text) or pcm())
        self.assertTrue(result['complete'])
        self.assertEqual(resumed, ['ข' * 1400, 'ค' * 1400])

    def test_oversize_splits_blocks_and_checkpoints_children(self):
        calls = []
        def request(cfg, text, timeout):
            calls.append(text)
            return pcm(121 if '\n\n' in text else 1)
        result = self.run_chunks(request)
        self.assertTrue(result['complete'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(result['manifest']['chunks']), 2)
        self.assertTrue(all(c['duration_sec'] <= 120 for c in result['manifest']['chunks']))
        self.assertTrue(self.run_chunks(lambda *a: self.fail('adaptive split lost on resume'))['complete'])

    def test_oversize_splits_at_sentence_boundary(self):
        self.script(['First sentence. Second sentence.'])
        calls = []
        def request(cfg, text, timeout):
            calls.append(text)
            return pcm(121 if 'First' in text and 'Second' in text else 1)
        self.assertTrue(self.run_chunks(request)['complete'])
        self.assertEqual(calls[1:], ['First sentence.', 'Second sentence.'])
        self.assertTrue(self.run_chunks()['complete'])

    def test_unsplittable_oversize_fails_without_truncating_words(self):
        self.script(['รถคันนี้'])
        result = self.run_chunks(lambda *a: pcm(121))
        self.assertFalse(result['complete'])
        self.assertEqual(result['manifest']['chunks'][0]['text'], 'รถคันนี้')
        self.assertFalse(list((self.ep / 'audio').rglob('*.wav')))

    def test_unsplittable_long_text_fails_before_api(self):
        self.script(['รถคันนี้ยังวิ่งต่อไป ' * 100])
        with self.assertRaisesRegex(g.ChunkError, 'no safe sentence boundary'):
            self.run_chunks()
        self.assertFalse((self.ep / 'audio').exists())

    def test_bad_pcm_never_publishes(self):
        for bad in (b'', b'\x00', 'not PCM'):
            with self.subTest(bad=bad):
                result = self.run_chunks(lambda *a: bad)
                self.assertFalse(result['complete'])
                self.assertFalse(list((self.ep / 'audio').rglob('*.wav')))

    def test_new_prompt_and_text_have_new_scope(self):
        one = self.run_chunks()['manifest_path']
        self.raw['style_instruction'] = g.APPROVED_PROMPT + '\nKeep it connected.'
        two = self.run_chunks()['manifest_path']
        self.script(['บทใหม่'])
        three = self.run_chunks()['manifest_path']
        self.assertEqual(len({one, two, three}), 3)
        self.assertTrue(one.exists())

    def test_old_timings_do_not_open_status_or_renderer(self):
        self.run_chunks()
        self.assertEqual(run_episode.compute_status(self.ep), 'BLOCK ALIGNMENT REQUIRED')
        with self.assertRaisesRegex(render_episode.RenderError, 'alignment'):
            render_episode.render_episode(self.ep)

    def test_stale_source_blocks_status(self):
        self.run_chunks()
        self.script(['บทที่เปลี่ยน'])
        self.assertEqual(run_episode.compute_status(self.ep), 'GEMINI CHUNKS STALE')

    def test_path_escape_pointer_is_rejected(self):
        g.atomic_json(self.ep / 'tts_chunks.json', {'manifest_path': '../other.json'})
        self.assertEqual(g.alignment_gate(self.ep), 'GEMINI CHUNKS INVALID')

    def test_legacy_block_gemini_entrypoint_is_disabled(self):
        with self.assertRaisesRegex(tts_render.TTSRenderError, 'multi-block'):
            tts_render.render_episode_tts(self.ep, self.raw)

    def test_real_subprocess_timeout_returns_promptly(self):
        real_run = subprocess.run
        def hanging(*args, **kwargs):
            return real_run([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
        started = time.monotonic()
        with patch.object(g.subprocess, 'run', side_effect=hanging), self.assertRaisesRegex(g.ChunkError, 'worker terminated'):
            g.request_pcm(g.config(self.raw), 'test', 0.1)
        self.assertLess(time.monotonic() - started, 2)

    def test_transport_failure_does_not_expose_upstream_secret(self):
        failed = subprocess.CompletedProcess([], 1, '', 'secret-api-key')
        with patch.object(g.subprocess, 'run', return_value=failed):
            with self.assertRaises(g.ChunkError) as caught:
                g.request_pcm(g.config(self.raw), 'test', 1)
        self.assertNotIn('secret-api-key', str(caught.exception))

    def test_worker_error_type_name_surfaces_as_a_diagnosable_hint(self):
        stderr = json.dumps({'error': 'ResourceExhausted'})
        failed = subprocess.CompletedProcess([], 1, '', stderr)
        with patch.object(g.subprocess, 'run', return_value=failed):
            with self.assertRaisesRegex(g.ChunkError, 'ResourceExhausted'):
                g.request_pcm(g.config(self.raw), 'test', 1)

    def test_worker_rate_limit_becomes_distinct_error_without_leaking_stderr(self):
        failed = subprocess.CompletedProcess([], 1, '', json.dumps({'error': 'RateLimitError'}))
        with patch.object(g.subprocess, 'run', return_value=failed):
            with self.assertRaises(g.RateLimited) as caught:
                g.request_pcm(g.config(self.raw), 'test', 1)
        self.assertIn('RateLimitError', str(caught.exception))

    def test_diagnose_only_echoes_the_safe_known_shape(self):
        self.assertEqual(g._diagnose(json.dumps({'error': 'PermissionDenied'})),
                         ': PermissionDenied (likely an auth/billing problem (HTTP 403) -- '
                         "check GEMINI_API_KEY and that billing/the model is enabled for this API key's project)")
        self.assertEqual(g._diagnose(json.dumps({'error': 'SomeOtherExceptionType'})), ': SomeOtherExceptionType')
        for garbage in ('secret-api-key', '', json.dumps({'error': 'not; safe$'}), json.dumps({'error': 12345}),
                        json.dumps({'nope': 'ResourceExhausted'})):
            with self.subTest(garbage=garbage):
                self.assertEqual(g._diagnose(garbage), '')

    def test_second_writer_is_rejected(self):
        with g.episode_lock(self.ep), self.assertRaisesRegex(g.ChunkError, 'Another Gemini'):
            self.run_chunks()

    def test_invalid_config_fails_before_writes(self):
        for raw in ({'target_sec': 121}, {'estimate_chars_per_sec': float('nan')}, {'voice': ''}):
            with self.subTest(raw=raw), self.assertRaises(g.ChunkError):
                g.render_chunks(self.ep, raw, dry_run=True)

    def test_edge_and_chirp_switch_back_preserve_gemini_audio(self):
        for cfg in ({'provider': 'edge-tts', 'voice': 'th-TH-NiwatNeural'},
                    {'provider': 'google-chirp3', 'voice': 'th-TH-Chirp3-HD-Charon', 'language_code': 'th-TH'}):
            with self.subTest(provider=cfg['provider']):
                chunk_result = self.run_chunks()
                audio = self.ep / chunk_result['manifest']['chunks'][0]['audio_path']
                original = audio.read_bytes()
                def synth(config, text, output, timeout):
                    g.write_wav(output, pcm())
                with patch.object(tts_render, '_synthesize', side_effect=synth), patch.object(tts_render, 'google_client'), redirect_stdout(io.StringIO()):
                    result = tts_render.render_episode_tts(self.ep, cfg)
                self.assertTrue(result['complete'])
                self.assertEqual(len(result['manifest']['blocks']), 2)
                self.assertFalse((self.ep / 'tts_chunks.json').exists())
                self.assertEqual(audio.read_bytes(), original)

    def test_failed_edge_switch_does_not_clear_gemini_gate(self):
        self.run_chunks()
        with patch.object(tts_render, '_synthesize', side_effect=tts_render.TTSRenderError('offline')), redirect_stdout(io.StringIO()):
            result = tts_render.render_episode_tts(self.ep, {'provider': 'edge-tts', 'voice': 'th-TH-NiwatNeural'})
        self.assertFalse(result['complete'])
        self.assertEqual(g.alignment_gate(self.ep), 'BLOCK ALIGNMENT REQUIRED')

    def test_missing_ffprobe_leaves_files_untouched(self):
        before = sorted(p.name for p in self.ep.iterdir())
        with patch.object(g.shutil, 'which', return_value=None), self.assertRaisesRegex(g.ChunkError, 'ffprobe'):
            self.run_chunks()
        self.assertEqual(before, sorted(p.name for p in self.ep.iterdir()))

    def test_exactly_120_seconds_is_accepted(self):
        result = self.run_chunks(lambda *a: pcm(120))
        self.assertTrue(result['complete'])
        self.assertEqual(result['manifest']['chunks'][0]['duration_sec'], 120)

    def test_sentence_split_preserves_abbreviations_and_decimals(self):
        text = 'Dr. Smith used a U.S. car with a 4.2 engine. It worked.'
        self.assertEqual([t for a, b, t in g.sentence_parts(text)],
                         ['Dr. Smith used a U.S. car with a 4.2 engine.', 'It worked.'])

    def test_worker_uses_approved_api_prompt_and_rejects_incomplete_audio(self):
        calls = []
        response = SimpleNamespace(status='completed', output_audio=SimpleNamespace(data=pcm()))
        class Client:
            def __init__(self, **kwargs):
                self.interactions = self
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def create(self, **kwargs):
                calls.append(kwargs)
                return response
        google = ModuleType('google')
        google.genai = SimpleNamespace(Client=Client)
        cfg = g.config(self.raw)
        for status in ('completed', 'incomplete', 'completed'):
            response.status = status
            if len(calls) == 2:
                response.output_audio.sample_rate = 48000
            stdout, stderr = io.StringIO(), io.StringIO()
            data = io.StringIO(json.dumps({'config': cfg, 'text': 'ข้อความจริง'}))
            with patch.dict(sys.modules, {'google': google}), patch.dict(os.environ, {'GEMINI_API_KEY': 'unit-test-placeholder'}), patch.object(sys, 'stdin', data), redirect_stdout(stdout), redirect_stderr(stderr):
                code = g.worker()
            self.assertEqual(code, 0 if len(calls) == 1 else 1)
            self.assertNotIn('unit-test-placeholder', stdout.getvalue() + stderr.getvalue())
        self.assertTrue(calls[0]['input'].startswith(g.APPROVED_PROMPT))
        self.assertIn(g.CONTINUITY, calls[0]['input'])
        self.assertEqual(calls[0]['response_format'], {'type': 'audio'})
        self.assertEqual(calls[0]['generation_config'], {'speech_config': [{'voice': 'Charon'}]})

    def test_fingerprint_inspection_matches_renderer(self):
        result = self.run_chunks(dry_run=True)
        self.assertEqual(result['fingerprint'], tts_render.tts_config_fingerprint(self.raw))


if __name__ == '__main__':
    unittest.main()
