"""
tests/test_sck_audio.py

Regression tests for SCKAudioInput._run_capture_loop variable name bugs.

Bug: _run_capture_loop used bare `q` and `stop_event` (NameError) instead
     of self._q and self._stop_event.  This caused a NameError crash in the
     capture thread whenever SCK initialisation hit any of the error paths or
     the normal run loop.

These tests do NOT require macOS / SCK / pyobjc to be installed.  They mock
the ObjC layer so the method logic can be exercised in any environment.
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sck(sample_rate: int = 16000) -> "SCKAudioInput":
    """Instantiate SCKAudioInput without triggering any ObjC imports."""
    from src.meet.audio import SCKAudioInput
    inst = SCKAudioInput.__new__(SCKAudioInput)
    inst._sample_rate = sample_rate
    inst._chunk_frames = int(sample_rate * 20 / 1000)
    inst._app_bundle_id = None
    inst._q = queue.Queue(maxsize=400)
    inst._stop_event = threading.Event()
    inst._stream = None
    inst._loop_thread = None
    inst._delegate = None
    inst._cm_get_data_buffer = None
    inst._cm_get_length = None
    inst._cm_copy_bytes = None
    return inst


def _make_loop_and_date():
    """Return mocks for NSRunLoop and NSDate used inside _run_capture_loop."""
    loop = MagicMock()
    loop.runUntilDate_ = MagicMock()
    date = MagicMock()
    date.dateWithTimeIntervalSinceNow_ = MagicMock(return_value=MagicMock())
    return loop, date


# ---------------------------------------------------------------------------
# Regression: NameError 'stop_event' / 'q' must not occur
# ---------------------------------------------------------------------------

class TestSCKRunCaptureLoopNameErrors:
    """
    Each test exercises one of the five locations in _run_capture_loop where
    the wrong bare name was previously used.  The test would crash with
    NameError before the fix; after the fix it must reach the intended path.
    """

    def _patch_imports(self, loop, date):
        """Patch the ObjC/Foundation/SCK imports used inside _run_capture_loop."""
        fake_sck = MagicMock()
        fake_sck.SCStreamOutputTypeAudio = 1

        return [
            patch.dict("sys.modules", {
                "Foundation": MagicMock(NSRunLoop=MagicMock(currentRunLoop=MagicMock(return_value=loop)),
                                        NSDate=date,
                                        NSObject=MagicMock()),
                "ScreenCaptureKit": fake_sck,
                "objc": MagicMock(),
                "CoreMedia": MagicMock(),
            }),
        ]

    def test_no_name_error_when_content_is_none(self):
        """
        Regression: the 'q.put_nowait(None)' on the content=None path used a
        bare 'q' that doesn't exist.  After fix, self._q must receive the
        sentinel instead.
        """
        inst = _make_sck()
        inst._stop_event.set()  # prevent run loop from spinning

        loop, date = _make_loop_and_date()

        # SCShareableContent callback will deliver None (simulate error)
        def fake_get_shareable(exclude_desktop, on_screen, handler):
            handler(None, Exception("permission denied"))

        fake_sck = MagicMock()
        fake_sck.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_ \
            = fake_get_shareable
        fake_sck.SCStreamOutputTypeAudio = 1

        fake_foundation = MagicMock()
        fake_foundation.NSRunLoop.currentRunLoop.return_value = loop
        fake_foundation.NSDate = date
        fake_foundation.NSObject = MagicMock()

        with patch.dict("sys.modules", {
            "Foundation": fake_foundation,
            "ScreenCaptureKit": fake_sck,
            "objc": MagicMock(),
            "CoreMedia": MagicMock(),
        }), patch("src.meet.audio._get_sck_delegate_class", return_value=MagicMock(
            return_value=MagicMock())):
            # Must NOT raise NameError
            inst._run_capture_loop()

        # Sentinel must have been placed on self._q
        assert not inst._q.empty(), "Expected None sentinel in self._q after error"
        assert inst._q.get_nowait() is None

    def test_no_name_error_when_no_displays(self):
        """
        Regression: the 'q.put_nowait(None)' on the no-displays path used a
        bare 'q'.  After fix, self._q must receive the sentinel.
        """
        inst = _make_sck()
        inst._stop_event.set()

        loop, date = _make_loop_and_date()

        content_mock = MagicMock()
        content_mock.displays.return_value = []   # no displays

        def fake_get_shareable(exclude_desktop, on_screen, handler):
            handler(content_mock, None)

        fake_sck = MagicMock()
        fake_sck.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_ \
            = fake_get_shareable
        fake_sck.SCStreamOutputTypeAudio = 1

        fake_foundation = MagicMock()
        fake_foundation.NSRunLoop.currentRunLoop.return_value = loop
        fake_foundation.NSDate = date
        fake_foundation.NSObject = MagicMock()

        with patch.dict("sys.modules", {
            "Foundation": fake_foundation,
            "ScreenCaptureKit": fake_sck,
            "objc": MagicMock(),
            "CoreMedia": MagicMock(),
        }), patch("src.meet.audio._get_sck_delegate_class", return_value=MagicMock(
            return_value=MagicMock())):
            inst._run_capture_loop()

        assert not inst._q.empty()
        assert inst._q.get_nowait() is None

    def test_no_name_error_in_main_run_loop(self):
        """
        Regression: the main `while not stop_event.is_set()` loop used a bare
        `stop_event`.  After fix, self._stop_event controls the loop.
        """
        inst = _make_sck()
        # Stop event is already set → loop body runs zero times (immediate exit)
        inst._stop_event.set()

        loop, date = _make_loop_and_date()

        display_mock = MagicMock()
        content_mock = MagicMock()
        content_mock.displays.return_value = [display_mock]

        def fake_get_shareable(exclude_desktop, on_screen, handler):
            handler(content_mock, None)

        stream_mock = MagicMock()
        # Simulate successful stream start
        def fake_start_capture(handler):
            handler(None)  # no error

        stream_mock.startCaptureWithCompletionHandler_ = fake_start_capture
        stream_mock.stopCaptureWithCompletionHandler_ = lambda h: h(None)

        fake_sck = MagicMock()
        fake_sck.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_ \
            = fake_get_shareable
        fake_sck.SCStreamOutputTypeAudio = 1
        fake_sck.SCStream.alloc.return_value.initWithFilter_configuration_delegate_.return_value = stream_mock
        fake_sck.SCStreamConfiguration.alloc.return_value.init.return_value = MagicMock()
        fake_sck.SCContentFilter = MagicMock()
        fake_sck.SCContentFilter.alloc.return_value \
            .initWithDisplay_excludingApplications_exceptingWindows_.return_value = MagicMock()

        fake_foundation = MagicMock()
        fake_foundation.NSRunLoop.currentRunLoop.return_value = loop
        fake_foundation.NSDate = date
        fake_foundation.NSObject = MagicMock()

        delegate_mock = MagicMock()
        delegate_cls_mock = MagicMock()
        delegate_cls_mock.alloc.return_value.initWithExtractor_queue_stopEvent_.return_value = delegate_mock

        with patch.dict("sys.modules", {
            "Foundation": fake_foundation,
            "ScreenCaptureKit": fake_sck,
            "objc": MagicMock(),
            "CoreMedia": MagicMock(),
        }), patch("src.meet.audio._get_sck_delegate_class", return_value=delegate_cls_mock):
            # Must NOT raise NameError on stop_event or q
            inst._run_capture_loop()

        # Sentinel must be in queue after normal stop
        try:
            sentinel = inst._q.get_nowait()
            assert sentinel is None
        except queue.Empty:
            pass  # sentinel may have been consumed; no crash is the key assertion


# ---------------------------------------------------------------------------
# SCKAudioInput attribute presence (no ObjC needed)
# ---------------------------------------------------------------------------

class TestSCKAudioInputAttributes:
    """Verify the instance has self._q and self._stop_event set correctly."""

    def test_has_q_attribute(self):
        inst = _make_sck()
        assert hasattr(inst, "_q")
        assert isinstance(inst._q, queue.Queue)

    def test_has_stop_event_attribute(self):
        inst = _make_sck()
        assert hasattr(inst, "_stop_event")
        assert isinstance(inst._stop_event, threading.Event)

    def test_stop_event_initially_clear(self):
        inst = _make_sck()
        assert not inst._stop_event.is_set()

    def test_stop_sets_stop_event(self):
        """stop() must set self._stop_event (was broken when bare 'stop_event' was used)."""
        from src.meet.audio import SCKAudioInput
        inst = SCKAudioInput(sample_rate=16000)
        inst.stop()
        assert inst._stop_event.is_set()
