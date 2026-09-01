"""Simulate Windows lock semantics on every test host; no API calls.

The existing real second-writer test still runs against the host's actual OS.
These additional checks exercise the Windows branch even on Linux CI.
"""
from contextlib import contextmanager
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tts_gemini_chunks as g


class WindowsLock(unittest.TestCase):
    @contextmanager
    def windows_stream(self, size):
        stream = MagicMock()
        stream.tell.return_value = size
        stream.fileno.return_value = 42
        # Reproduce Windows refusing reads of another handle's locked byte.
        stream.read.side_effect = PermissionError(13, "Permission denied")
        episode = MagicMock()
        episode.__truediv__.return_value.open.return_value.__enter__.return_value = stream
        msvcrt = ModuleType("msvcrt")
        msvcrt.LK_NBLCK, msvcrt.LK_UNLCK = 2, 0
        msvcrt.locking = MagicMock()
        # Patch only this module's OS reference, not global os.name (which
        # would also change pathlib/subprocess platform selection on Linux).
        with patch.object(g, "os", SimpleNamespace(name="nt")), patch.dict(sys.modules, {"msvcrt": msvcrt}):
            yield episode, stream, msvcrt

    def test_contended_lock_does_not_read_or_write_locked_byte(self):
        with self.windows_stream(1) as (episode, stream, msvcrt):
            msvcrt.locking.side_effect = PermissionError(13, "Permission denied")
            with self.assertRaisesRegex(g.ChunkError, "Another Gemini render"):
                with g.episode_lock(episode):
                    self.fail("Contended lock was acquired")
            stream.read.assert_not_called()
            stream.write.assert_not_called()
            msvcrt.locking.assert_called_once_with(42, msvcrt.LK_NBLCK, 1)

    def test_empty_file_is_initialized_and_lock_released_on_body_failure(self):
        with self.windows_stream(0) as (episode, stream, msvcrt):
            with self.assertRaisesRegex(RuntimeError, "body failed"):
                with g.episode_lock(episode):
                    raise RuntimeError("body failed")
            stream.read.assert_not_called()
            stream.write.assert_called_once_with(b"0")
            stream.flush.assert_called_once()
            self.assertEqual(msvcrt.locking.call_args_list,
                             [call(42, msvcrt.LK_NBLCK, 1), call(42, msvcrt.LK_UNLCK, 1)])
            self.assertEqual(stream.seek.call_args, call(0))

    def test_initialization_race_reports_lock_error_without_unlocking(self):
        with self.windows_stream(0) as (episode, stream, msvcrt):
            stream.write.side_effect = PermissionError(13, "Permission denied")
            with self.assertRaisesRegex(g.ChunkError, "Another Gemini render"):
                with g.episode_lock(episode):
                    self.fail("Lock initialization failed but yielded")
            msvcrt.locking.assert_not_called()


if __name__ == "__main__":
    unittest.main()
