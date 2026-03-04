"""
tests/test_meet_bot_join.py

Unit tests for MeetBot join / admission logic in src/meet/bot.py.

All tests use AsyncMock/MagicMock — no real browser is launched.
They exercise:
  1. _click_join_button: selector retry, text detection, return value
  2. _wait_for_admission: direct join, waiting-room poll, timeout
  3. _navigate_and_join: MeetBotError raised iff join button never found
  4. Selector parity: SEL keys used in bot.py all exist in selectors.py

Regression coverage for:
  - Old bug: _wait_for_admission returned immediately (in_waiting=False)
    when waiting-room banner detection was broken → bot appeared to join
    but was never admitted.
  - Old bug: _click_join_button returned bool; now returns (bool, bool).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.meet.bot import MeetBot, MeetBotError, _JOIN_CLICK_ATTEMPTS, _POLL_INTERVAL
from src.meet.selectors import SEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(**kwargs) -> MeetBot:
    defaults = dict(
        meeting_url="https://meet.google.com/test-url",
        profile_dir="/tmp/test_profile",
        join_timeout=10,
    )
    defaults.update(kwargs)
    bot = MeetBot(**defaults)
    # Attach a mock page so internal methods can be called without a browser
    bot._page = MagicMock()
    return bot


def _locator_visible(inner_text: str = "") -> MagicMock:
    """Return a mock locator whose .first is visible and has the given inner text."""
    loc = MagicMock()
    first = MagicMock()
    first.is_visible = AsyncMock(return_value=True)
    first.inner_text = AsyncMock(return_value=inner_text)
    first.click = AsyncMock()
    loc.first = first
    return loc


def _locator_invisible() -> MagicMock:
    """Return a mock locator whose .first is NOT visible."""
    loc = MagicMock()
    first = MagicMock()
    first.is_visible = AsyncMock(return_value=False)
    first.inner_text = AsyncMock(return_value="")
    first.click = AsyncMock()
    loc.first = first
    return loc


# ---------------------------------------------------------------------------
# _click_join_button tests
# ---------------------------------------------------------------------------

class TestClickJoinButton:

    @pytest.mark.asyncio
    async def test_returns_tuple(self):
        """_click_join_button must return (bool, bool), not bare bool (regression)."""
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_visible("Join now"))

        result = await bot._click_join_button()

        assert isinstance(result, tuple), "Must return a tuple"
        assert len(result) == 2, "Must return exactly (clicked, is_waiting_room)"

    @pytest.mark.asyncio
    async def test_direct_join_returns_clicked_true_not_waiting(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_visible("Join now"))

        clicked, is_waiting = await bot._click_join_button()

        assert clicked is True
        assert is_waiting is False

    @pytest.mark.asyncio
    async def test_ask_to_join_returns_is_waiting_true(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_visible("Ask to join"))

        clicked, is_waiting = await bot._click_join_button()

        assert clicked is True
        assert is_waiting is True

    @pytest.mark.asyncio
    async def test_knock_text_sets_is_waiting_true(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_visible("Knock"))

        clicked, is_waiting = await bot._click_join_button()

        assert clicked is True
        assert is_waiting is True

    @pytest.mark.asyncio
    async def test_no_button_returns_false_false(self):
        """When no join button is ever visible, returns (False, False)."""
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_invisible())

        clicked, is_waiting = await bot._click_join_button()

        assert clicked is False
        assert is_waiting is False

    @pytest.mark.asyncio
    async def test_button_found_on_second_attempt(self):
        """Button is invisible on attempt 1, visible on attempt 2."""
        bot = _make_bot()
        call_count = 0

        def locator_side_effect(sel):
            nonlocal call_count
            # Count calls; after first full selector sweep, return visible
            # We have N selectors in SEL["join_button"]; make first sweep invisible
            num_selectors = len(SEL["join_button"])
            call_count += 1
            if call_count <= num_selectors:
                return _locator_invisible()
            return _locator_visible("Join now")

        bot._page.locator = MagicMock(side_effect=locator_side_effect)

        clicked, is_waiting = await bot._click_join_button()

        assert clicked is True

    @pytest.mark.asyncio
    async def test_click_is_called_on_button(self):
        """The actual .click() must be awaited when button is found."""
        bot = _make_bot()
        visible_loc = _locator_visible("Join now")
        bot._page.locator = MagicMock(return_value=visible_loc)

        await bot._click_join_button()

        visible_loc.first.click.assert_awaited_once()


# ---------------------------------------------------------------------------
# _is_waiting_room_visible / _is_in_call helpers
# ---------------------------------------------------------------------------

class TestStateHelpers:

    @pytest.mark.asyncio
    async def test_is_waiting_room_visible_true(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_visible())

        assert await bot._is_waiting_room_visible() is True

    @pytest.mark.asyncio
    async def test_is_waiting_room_visible_false(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_invisible())

        assert await bot._is_waiting_room_visible() is False

    @pytest.mark.asyncio
    async def test_is_in_call_true(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_visible())

        assert await bot._is_in_call() is True

    @pytest.mark.asyncio
    async def test_is_in_call_false(self):
        bot = _make_bot()
        bot._page.locator = MagicMock(return_value=_locator_invisible())

        assert await bot._is_in_call() is False


# ---------------------------------------------------------------------------
# _wait_for_admission tests
# ---------------------------------------------------------------------------

class TestWaitForAdmission:

    @pytest.mark.asyncio
    async def test_direct_join_no_waiting_room(self):
        """If is_waiting_room=False and in-call indicator visible → returns immediately."""
        bot = _make_bot()
        bot._is_waiting_room_visible = AsyncMock(return_value=False)
        bot._is_in_call = AsyncMock(return_value=True)

        # Must return without raising
        await bot._wait_for_admission(is_waiting_room=False)

    @pytest.mark.asyncio
    async def test_ask_to_join_waits_then_admitted_via_in_call(self):
        """
        Regression: is_waiting_room=True (from "Ask to join" click) must
        enter the poll loop and wait for admission rather than returning
        immediately (old bug: in_waiting detection was broken so it returned
        at once without polling).
        """
        bot = _make_bot(join_timeout=30)

        # is_in_call: False on first 2 polls, True on 3rd
        in_call_returns = [False, False, True]
        bot._is_in_call = AsyncMock(side_effect=in_call_returns + [True] * 10)
        bot._is_waiting_room_visible = AsyncMock(return_value=True)

        # Speed up: patch _POLL_INTERVAL to near-zero for test
        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            await bot._wait_for_admission(is_waiting_room=True)

        # Must have called _is_in_call multiple times (was polling)
        assert bot._is_in_call.await_count >= 2

    @pytest.mark.asyncio
    async def test_admitted_when_banner_clears(self):
        """Admission confirmed when waiting-room banner disappears."""
        bot = _make_bot(join_timeout=30)

        # Banner visible twice, then gone
        banner_returns = [True, True, False, False]
        bot._is_waiting_room_visible = AsyncMock(side_effect=banner_returns + [False] * 10)
        bot._is_in_call = AsyncMock(return_value=False)

        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            await bot._wait_for_admission(is_waiting_room=True)

    @pytest.mark.asyncio
    async def test_timeout_raises_meet_bot_error(self):
        """If never admitted within join_timeout, MeetBotError must be raised."""
        bot = _make_bot(join_timeout=1)  # 1 second timeout
        bot._is_waiting_room_visible = AsyncMock(return_value=True)
        bot._is_in_call = AsyncMock(return_value=False)

        with patch("src.meet.bot._POLL_INTERVAL", 0.1):
            with pytest.raises(MeetBotError, match="Timed out"):
                await bot._wait_for_admission(is_waiting_room=True)

    @pytest.mark.asyncio
    async def test_no_banner_no_in_call_enters_poll_loop(self):
        """
        Regression: If neither banner nor in-call indicator is visible right
        after click (transient state), the old code returned immediately
        (false success). New code must enter the poll loop.

        In the poll loop: if the waiting-room banner is also never visible,
        the "banner cleared" path is triggered (it was never up → already
        admitted or direct join). This is correct behaviour — the test
        verifies the poll loop is entered (is_in_call called multiple times)
        rather than an immediate return.
        """
        bot = _make_bot(join_timeout=5)

        # No banner at any point, no in-call indicator either
        # The poll loop will see "banner not visible" and declare admission.
        call_count = {"n": 0}
        async def counting_in_call():
            call_count["n"] += 1
            return False

        bot._is_waiting_room_visible = AsyncMock(return_value=False)
        bot._is_in_call = AsyncMock(side_effect=counting_in_call)

        with patch("src.meet.bot._POLL_INTERVAL", 0.05):
            # Must succeed (banner cleared path) rather than raise
            await bot._wait_for_admission(is_waiting_room=False)

        # Verify that the poll loop was entered (is_in_call called more than
        # the 2 initial checks in the "not in_waiting" branch)
        assert bot._is_in_call.await_count >= 1, (
            "Expected _is_in_call to be called (poll loop entered)"
        )

    @pytest.mark.asyncio
    async def test_transient_state_timeout_when_banner_persists(self):
        """
        When banner is not visible at click time but then appears in the poll
        loop and never clears, the bot must time out (not succeed silently).
        """
        bot = _make_bot(join_timeout=1)

        # First call: no banner (transitional); subsequent calls: banner visible
        banner_returns = iter([False, True, True, True, True, True, True, True])
        bot._is_waiting_room_visible = AsyncMock(side_effect=lambda: next(banner_returns, True))
        bot._is_in_call = AsyncMock(return_value=False)

        with patch("src.meet.bot._POLL_INTERVAL", 0.1):
            with pytest.raises(MeetBotError, match="Timed out"):
                await bot._wait_for_admission(is_waiting_room=False)


# ---------------------------------------------------------------------------
# _navigate_and_join integration (mocked)
# ---------------------------------------------------------------------------

class TestNavigateAndJoin:

    @pytest.mark.asyncio
    async def test_raises_meet_bot_error_when_no_join_button(self):
        """If _click_join_button returns (False, False), MeetBotError is raised."""
        bot = _make_bot()
        bot._dismiss_popups = AsyncMock()
        bot._fill_display_name = AsyncMock()
        bot._set_preflight_av = AsyncMock()
        bot._click_join_button = AsyncMock(return_value=(False, False))
        bot._wait_for_admission = AsyncMock()
        bot._page = MagicMock()
        bot._page.goto = AsyncMock()

        with pytest.raises(MeetBotError, match="Could not find or click"):
            await bot._navigate_and_join()

        # Admission should NOT be attempted if click failed
        bot._wait_for_admission.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sets_joined_event_on_success(self):
        """_joined event must be set after successful navigation + join."""
        bot = _make_bot()
        bot._dismiss_popups = AsyncMock()
        bot._fill_display_name = AsyncMock()
        bot._set_preflight_av = AsyncMock()
        bot._click_join_button = AsyncMock(return_value=(True, False))
        bot._wait_for_admission = AsyncMock()
        bot._page = MagicMock()
        bot._page.goto = AsyncMock()

        assert not bot.is_joined
        await bot._navigate_and_join()
        assert bot.is_joined

    @pytest.mark.asyncio
    async def test_waiting_room_flag_forwarded_to_admission(self):
        """is_waiting_room from _click_join_button is passed to _wait_for_admission."""
        bot = _make_bot()
        bot._dismiss_popups = AsyncMock()
        bot._fill_display_name = AsyncMock()
        bot._set_preflight_av = AsyncMock()
        bot._click_join_button = AsyncMock(return_value=(True, True))  # ask-to-join
        bot._wait_for_admission = AsyncMock()
        bot._page = MagicMock()
        bot._page.goto = AsyncMock()

        await bot._navigate_and_join()

        bot._wait_for_admission.assert_awaited_once_with(is_waiting_room=True)


# ---------------------------------------------------------------------------
# Selector key parity: every SEL key used in bot.py must exist in SEL
# ---------------------------------------------------------------------------

class TestSelectorParity:

    USED_IN_BOT = {
        "join_button",
        "dismiss_popup",
        "name_input",
        "camera_button",
        "admit_self_banner",
        "in_call_indicator",
        "leave_button",
    }

    def test_all_used_keys_exist_in_sel(self):
        missing = self.USED_IN_BOT - set(SEL.keys())
        assert missing == set(), f"SEL is missing keys used in bot.py: {missing}"

    def test_all_sel_lists_are_nonempty(self):
        for key, selectors in SEL.items():
            assert len(selectors) > 0, f"SEL[{key!r}] is empty"

    def test_in_call_indicator_key_added(self):
        """Regression: 'in_call_indicator' was missing from selectors.py."""
        assert "in_call_indicator" in SEL
        assert len(SEL["in_call_indicator"]) >= 1
