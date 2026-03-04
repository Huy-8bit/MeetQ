"""
tests/test_manual_join.py

Unit tests for the manual-join mode added to MeetBot.

Tests cover:
  1. _wait_for_manual_join: in-call detection path, timeout path, progress prints
  2. _navigate_and_join branching: manual mode skips auto-click; auto mode unchanged
  3. CLI parser: --manual-join / --manual-join-timeout present in both parsers
     with correct defaults and parity
  4. MeetBot constructor: manual_join / manual_join_timeout attributes set
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.meet.bot import MeetBot, MeetBotError, _POLL_INTERVAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(**kwargs) -> MeetBot:
    defaults = dict(
        meeting_url="https://meet.google.com/test",
        profile_dir="/tmp/prof",
        join_timeout=10,
    )
    defaults.update(kwargs)
    bot = MeetBot(**defaults)
    bot._page = MagicMock()
    return bot


# ---------------------------------------------------------------------------
# MeetBot constructor
# ---------------------------------------------------------------------------

class TestMeetBotConstructor:

    def test_manual_join_defaults_false(self):
        bot = _make_bot()
        assert bot.manual_join is False

    def test_manual_join_timeout_defaults_300(self):
        bot = _make_bot()
        assert bot.manual_join_timeout == 300

    def test_manual_join_param_set(self):
        bot = _make_bot(manual_join=True, manual_join_timeout=120)
        assert bot.manual_join is True
        assert bot.manual_join_timeout == 120


# ---------------------------------------------------------------------------
# _wait_for_manual_join
# ---------------------------------------------------------------------------

class TestWaitForManualJoin:

    @pytest.mark.asyncio
    async def test_returns_when_in_call_detected(self):
        """Once _is_in_call() returns True, _wait_for_manual_join must return."""
        bot = _make_bot(manual_join=True, manual_join_timeout=30)
        bot._is_in_call = AsyncMock(side_effect=[False, False, True])

        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            await bot._wait_for_manual_join()

        assert bot._is_in_call.await_count == 3

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        """If in-call is never detected, MeetBotError must be raised."""
        bot = _make_bot(manual_join=True, manual_join_timeout=1)
        bot._is_in_call = AsyncMock(return_value=False)

        with patch("src.meet.bot._POLL_INTERVAL", 0.1):
            with pytest.raises(MeetBotError, match="Manual-join timed out"):
                await bot._wait_for_manual_join()

    @pytest.mark.asyncio
    async def test_timeout_error_message_contains_seconds(self):
        bot = _make_bot(manual_join=True, manual_join_timeout=42)
        bot._is_in_call = AsyncMock(return_value=False)

        with patch("src.meet.bot._POLL_INTERVAL", 0.1):
            with pytest.raises(MeetBotError) as exc_info:
                await bot._wait_for_manual_join()

        assert "42" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_prints_instructions_on_start(self, capsys):
        """User must see instructions when manual-join mode activates."""
        bot = _make_bot(manual_join=True, manual_join_timeout=30)
        bot._is_in_call = AsyncMock(return_value=True)  # immediate success

        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            await bot._wait_for_manual_join()

        out = capsys.readouterr().out
        assert "manual" in out.lower() or "Manual" in out
        assert bot.meeting_url in out

    @pytest.mark.asyncio
    async def test_prints_in_call_confirmation(self, capsys):
        """'In call' confirmation message must be printed on detection."""
        bot = _make_bot(manual_join=True, manual_join_timeout=30)
        bot._is_in_call = AsyncMock(side_effect=[False, True])

        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            await bot._wait_for_manual_join()

        out = capsys.readouterr().out
        assert "In call" in out or "in call" in out.lower()

    @pytest.mark.asyncio
    async def test_polls_until_in_call(self):
        """Must not return on first poll if not yet in-call."""
        bot = _make_bot(manual_join=True, manual_join_timeout=30)
        # 4 False, then True
        bot._is_in_call = AsyncMock(side_effect=[False, False, False, False, True])

        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            await bot._wait_for_manual_join()

        assert bot._is_in_call.await_count == 5


# ---------------------------------------------------------------------------
# _navigate_and_join branching
# ---------------------------------------------------------------------------

class TestNavigateAndJoinManualBranch:

    def _patched_bot(self, **kwargs) -> MeetBot:
        bot = _make_bot(**kwargs)
        bot._dismiss_popups = AsyncMock()
        bot._fill_display_name = AsyncMock()
        bot._set_preflight_av = AsyncMock()
        bot._click_join_button = AsyncMock(return_value=(True, False))
        bot._wait_for_admission = AsyncMock()
        bot._wait_for_manual_join = AsyncMock()
        bot._page = MagicMock()
        bot._page.goto = AsyncMock()
        return bot

    @pytest.mark.asyncio
    async def test_manual_mode_calls_wait_for_manual_join(self):
        """In manual mode, _wait_for_manual_join must be called."""
        bot = self._patched_bot(manual_join=True)

        await bot._navigate_and_join()

        bot._wait_for_manual_join.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_mode_does_not_click_join_button(self):
        """In manual mode, _click_join_button must NOT be called."""
        bot = self._patched_bot(manual_join=True)

        await bot._navigate_and_join()

        bot._click_join_button.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_mode_does_not_call_wait_for_admission(self):
        """In manual mode, _wait_for_admission must NOT be called."""
        bot = self._patched_bot(manual_join=True)

        await bot._navigate_and_join()

        bot._wait_for_admission.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_mode_calls_click_join_button(self):
        """In auto mode (default), _click_join_button must be called."""
        bot = self._patched_bot(manual_join=False)

        await bot._navigate_and_join()

        bot._click_join_button.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_mode_does_not_call_wait_for_manual_join(self):
        """In auto mode, _wait_for_manual_join must NOT be called."""
        bot = self._patched_bot(manual_join=False)

        await bot._navigate_and_join()

        bot._wait_for_manual_join.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_mode_sets_joined_event(self):
        """_joined event must be set after successful manual join."""
        bot = self._patched_bot(manual_join=True)

        assert not bot.is_joined
        await bot._navigate_and_join()
        assert bot.is_joined

    @pytest.mark.asyncio
    async def test_manual_mode_meet_bot_error_propagates(self):
        """MeetBotError from _wait_for_manual_join must propagate unchanged."""
        bot = self._patched_bot(manual_join=True)
        bot._wait_for_manual_join = AsyncMock(
            side_effect=MeetBotError("Manual-join timed out after 300s.")
        )

        with pytest.raises(MeetBotError, match="Manual-join timed out"):
            await bot._navigate_and_join()

        # _joined must NOT be set on failure
        assert not bot.is_joined


# ---------------------------------------------------------------------------
# CLI parser parity: --manual-join and --manual-join-timeout
# ---------------------------------------------------------------------------

class TestManualJoinCLIParity:

    def _app_parse(self, argv: list[str]):
        from app import build_parser
        return build_parser().parse_args(argv)

    def _meet_parse(self, argv: list[str]):
        from src.meet.main import parse_args
        return parse_args(argv)

    def test_app_parser_has_manual_join(self):
        # app.py defaults manual_join to True (stable join path for end-user).
        # src/meet/main.py keeps False (advanced entrypoint, explicit flag required).
        args = self._app_parse(["--mode", "meet-bot",
                                "--meeting-url", "https://meet.google.com/x"])
        assert hasattr(args, "manual_join")
        assert args.manual_join is True

    def test_app_parser_manual_join_flag(self):
        args = self._app_parse(["--mode", "meet-bot",
                                "--meeting-url", "https://meet.google.com/x",
                                "--manual-join"])
        assert args.manual_join is True

    def test_app_parser_manual_join_timeout_default(self):
        args = self._app_parse(["--mode", "meet-bot",
                                "--meeting-url", "https://meet.google.com/x"])
        assert args.manual_join_timeout == 300

    def test_app_parser_manual_join_timeout_value(self):
        args = self._app_parse(["--mode", "meet-bot",
                                "--meeting-url", "https://meet.google.com/x",
                                "--manual-join-timeout", "120"])
        assert args.manual_join_timeout == 120

    def test_meet_parser_has_manual_join(self):
        args = self._meet_parse(["--meeting-url", "https://meet.google.com/x"])
        assert hasattr(args, "manual_join")
        assert args.manual_join is False

    def test_meet_parser_manual_join_flag(self):
        args = self._meet_parse(["--meeting-url", "https://meet.google.com/x",
                                 "--manual-join"])
        assert args.manual_join is True

    def test_meet_parser_manual_join_timeout_default(self):
        args = self._meet_parse(["--meeting-url", "https://meet.google.com/x"])
        assert args.manual_join_timeout == 300

    def test_meet_parser_manual_join_timeout_value(self):
        args = self._meet_parse(["--meeting-url", "https://meet.google.com/x",
                                 "--manual-join-timeout", "60"])
        assert args.manual_join_timeout == 60

    def test_defaults_are_identical_across_parsers(self):
        """manual_join_timeout default must match; manual_join differs intentionally."""
        app_args = self._app_parse(["--mode", "meet-bot",
                                    "--meeting-url", "https://meet.google.com/x"])
        meet_args = self._meet_parse(["--meeting-url", "https://meet.google.com/x"])

        # app.py defaults to True (user-friendly); meet/main.py defaults to False (advanced).
        assert app_args.manual_join is True
        assert meet_args.manual_join is False
        # Timeout default must still match.
        assert app_args.manual_join_timeout == meet_args.manual_join_timeout
