"""
Tests for meet-bot CLI argument wiring between app.py and src/meet/main.py.

Regression: AttributeError: 'Namespace' object has no attribute 'sck'
Root cause: app.py's build_parser() was missing --sck and --sck-app arguments
            that _run_meet_bot() unconditionally accesses.
"""
import sys
import types
from pathlib import Path

import pytest

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app_parse(argv: list[str]):
    """Parse argv using app.py's build_parser (the broken entry-point path)."""
    from app import build_parser
    return build_parser().parse_args(argv)


def _meet_parse(argv: list[str]):
    """Parse argv using src/meet/main.py's standalone parse_args."""
    from src.meet.main import parse_args
    return parse_args(argv)


# ---------------------------------------------------------------------------
# Regression: --sck must exist on app.py's Namespace
# ---------------------------------------------------------------------------

class TestSckArgPresentInAppParser:
    """Ensure app.py's parser exposes every attribute _run_meet_bot accesses."""

    REQUIRED_ATTRS = [
        "sck",
        "sck_app",
        "meeting_url",
        "profile_dir",
        "headless",
        "display_name",
        "join_timeout_seconds",
        "leave_after_minutes",
        "meet_speaker_device",
        "meet_mic_device",
        "meet_sample_rate",
        "model",
        "src",
        "tgt",
        "pairs",
        "show_input",
        "meeting_mode",
        "debug",
    ]

    def _base_argv(self) -> list[str]:
        return [
            "--mode", "meet-bot",
            "--meeting-url", "https://meet.google.com/abc-defg-hij",
        ]

    def test_all_required_attrs_present(self):
        """Regression: _run_meet_bot must not raise AttributeError on any attr it reads."""
        args = _app_parse(self._base_argv())
        missing = [a for a in self.REQUIRED_ATTRS if not hasattr(args, a)]
        assert missing == [], (
            f"app.py Namespace is missing attributes that _run_meet_bot accesses: {missing}"
        )

    def test_sck_default_is_false(self):
        args = _app_parse(self._base_argv())
        assert args.sck is False

    def test_sck_flag_sets_true(self):
        args = _app_parse(self._base_argv() + ["--sck"])
        assert args.sck is True

    def test_sck_app_default_is_none(self):
        args = _app_parse(self._base_argv())
        assert args.sck_app is None

    def test_sck_app_value(self):
        args = _app_parse(self._base_argv() + ["--sck", "--sck-app", "com.google.Chrome"])
        assert args.sck_app == "com.google.Chrome"


# ---------------------------------------------------------------------------
# Parity: app.py parser attrs must match meet.main parser defaults
# ---------------------------------------------------------------------------

class TestAppAndMeetParserParity:
    """Shared meet-bot arguments must have the same defaults in both parsers."""

    SHARED_ATTRS_WITH_DEFAULTS = {
        "sck": False,
        "sck_app": None,
        "headless": False,
        "display_name": "Interpreter Bot",
        "join_timeout_seconds": 90,
        "leave_after_minutes": None,
        "meet_speaker_device": None,
        "meet_mic_device": None,
        "src": "auto",
        "tgt": "auto",
        "pairs": "",
        "meeting_mode": "locked",
        "show_input": False,
        "debug": False,
    }

    def test_defaults_match_between_parsers(self):
        app_args = _app_parse(["--mode", "meet-bot",
                               "--meeting-url", "https://meet.google.com/x"])
        meet_args = _meet_parse(["--meeting-url", "https://meet.google.com/x"])

        mismatches = {}
        for attr, expected_default in self.SHARED_ATTRS_WITH_DEFAULTS.items():
            app_val = getattr(app_args, attr, "__MISSING__")
            meet_val = getattr(meet_args, attr, "__MISSING__")
            if app_val != meet_val:
                mismatches[attr] = {"app.py": app_val, "meet/main.py": meet_val}

        assert mismatches == {}, (
            "Default values differ between app.py and src/meet/main.py parsers:\n"
            + "\n".join(f"  {k}: {v}" for k, v in mismatches.items())
        )


# ---------------------------------------------------------------------------
# _run_meet_bot: attribute access simulation (no real I/O)
# ---------------------------------------------------------------------------

class TestRunMeetBotAttrAccess:
    """Simulate the attribute-access pattern of _run_meet_bot without real I/O."""

    def _make_args(self, extra: list[str] | None = None) -> types.SimpleNamespace:
        argv = [
            "--mode", "meet-bot",
            "--meeting-url", "https://meet.google.com/abc-defg-hij",
        ]
        if extra:
            argv += extra
        return _app_parse(argv)

    def test_no_attr_error_sck_branch(self):
        """The 'if args.sck:' line must not raise AttributeError."""
        args = self._make_args(["--sck"])
        # Just reading the attribute — was the actual crash site
        _ = args.sck
        _ = args.sck_app

    def test_no_attr_error_device_branch(self):
        """With --meet-speaker-device, sck must still be accessible."""
        args = self._make_args(["--meet-speaker-device", "4"])
        assert args.sck is False
        assert args.meet_speaker_device == 4

    def test_all_attrs_readable_without_exception(self):
        """Reading every attribute _run_meet_bot uses must not raise."""
        from app import build_parser
        args = build_parser().parse_args([
            "--mode", "meet-bot",
            "--meeting-url", "https://meet.google.com/test",
            "--sck",
            "--sck-app", "com.google.Chrome",
            "--meet-mic-device", "5",
            "--src", "ja",
            "--tgt", "vi",
            "--meeting-mode", "locked",
            "--show-input",
            "--debug",
        ])
        # Mirror the attribute access sequence in _run_meet_bot lines 240-320
        accessed = [
            args.model,
            args.sck,
            args.meet_sample_rate,
            args.sck_app,
            args.meet_speaker_device,
            args.meet_mic_device,
            args.pairs,
            args.debug,
            args.src,
            args.tgt,
            args.show_input,
            args.meeting_mode,
            args.meeting_url,
            args.profile_dir,
            args.display_name,
            args.headless,
            args.join_timeout_seconds,
            args.leave_after_minutes,
        ]
        # If we get here without AttributeError, the test passes
        assert len(accessed) == 18
