"""
Tests for meet-bot CLI argument wiring between app.py and src/meet/main.py.

Regressions covered:
  - AttributeError: 'Namespace' object has no attribute 'sck'
    Root cause: app.py's build_parser() was missing --sck and --sck-app.
  - app.py refactored to meet-bot as primary mode (no --mode required).
    Regressions: unsupported modes must fail fast; --meeting-url required.
"""
import sys
import types
from io import StringIO
from pathlib import Path
from unittest.mock import patch, AsyncMock

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


# ---------------------------------------------------------------------------
# New primary-mode behaviour: no --mode needed, meet-bot is default
# ---------------------------------------------------------------------------

class TestMeetBotPrimaryMode:
    """app.py defaults to meet-bot; --mode meet-bot is explicit but equivalent."""

    def test_default_mode_is_meet_bot(self):
        """Parsing with only --meeting-url should produce mode='meet-bot'."""
        args = _app_parse(["--meeting-url", "https://meet.google.com/abc"])
        assert args.mode == "meet-bot"

    def test_explicit_mode_meet_bot_still_works(self):
        """--mode meet-bot remains valid for backward compatibility."""
        args = _app_parse(["--mode", "meet-bot",
                           "--meeting-url", "https://meet.google.com/abc"])
        assert args.mode == "meet-bot"

    def test_manual_join_default_is_true(self):
        """app.py defaults --manual-join to True (stable join path)."""
        args = _app_parse(["--meeting-url", "https://meet.google.com/abc"])
        assert args.manual_join is True

    def test_no_manual_join_flag_disables_it(self):
        """--no-manual-join disables manual-join (enables auto-click)."""
        args = _app_parse(["--meeting-url", "https://meet.google.com/abc",
                           "--no-manual-join"])
        assert args.manual_join is False


# ---------------------------------------------------------------------------
# Unsupported legacy modes are rejected with a clear error
# ---------------------------------------------------------------------------

class TestUnsupportedModesRejected:
    """--mode realtime and --mode fallback must exit 1 with a clear message."""

    def _run_main(self, argv: list[str]) -> tuple[int, str]:
        """Run app.main() with argv, return (exit_code, stderr_text)."""
        from app import main
        captured = StringIO()
        with patch("sys.argv", ["app.py"] + argv), \
             patch("sys.stderr", captured):
            code = main()
        return code, captured.getvalue()

    def test_mode_realtime_exits_1(self):
        code, err = self._run_main(["--mode", "realtime"])
        assert code == 1

    def test_mode_realtime_error_mentions_not_supported(self):
        _, err = self._run_main(["--mode", "realtime"])
        assert "not supported" in err.lower() or "not supported" in err

    def test_mode_realtime_error_suggests_alternative(self):
        _, err = self._run_main(["--mode", "realtime"])
        assert "src.realtime.main" in err

    def test_mode_fallback_exits_1(self):
        code, err = self._run_main(["--mode", "fallback"])
        assert code == 1

    def test_mode_fallback_error_mentions_not_supported(self):
        _, err = self._run_main(["--mode", "fallback"])
        assert "not supported" in err.lower() or "not supported" in err

    def test_mode_fallback_error_suggests_alternative(self):
        _, err = self._run_main(["--mode", "fallback"])
        assert "src.fallback.pipeline" in err


# ---------------------------------------------------------------------------
# Missing --meeting-url produces a clear error (not a crash)
# ---------------------------------------------------------------------------

class TestMissingMeetingUrl:
    """No --meeting-url should produce exit 1 and a helpful error."""

    def _run_main(self, argv: list[str], env: dict | None = None) -> tuple[int, str]:
        from app import main
        captured = StringIO()
        env = env or {"OPENAI_API_KEY": "sk-test"}
        with patch("sys.argv", ["app.py"] + argv), \
             patch("sys.stderr", captured), \
             patch.dict("os.environ", env, clear=False):
            code = main()
        return code, captured.getvalue()

    def test_no_meeting_url_exits_1(self):
        code, _ = self._run_main([])
        assert code == 1

    def test_no_meeting_url_error_mentions_required(self):
        _, err = self._run_main([])
        assert "--meeting-url" in err and "required" in err

    def test_no_meeting_url_error_shows_example(self):
        _, err = self._run_main([])
        assert "meet.google.com" in err

    def test_mode_meet_bot_no_url_also_exits_1(self):
        """Explicit --mode meet-bot without --meeting-url also fails cleanly."""
        code, err = self._run_main(["--mode", "meet-bot"])
        assert code == 1
        assert "--meeting-url" in err
