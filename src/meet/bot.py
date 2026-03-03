"""
src/meet/bot.py
Playwright-based Google Meet bot that joins a meeting as a visible participant.

Design:
  - Uses a persistent browser profile directory so Google sign-in is preserved
    across runs (user logs in once manually via --setup-profile).
  - Camera is always OFF; microphone state is controlled via flag.
  - Handles lobby/waiting-room by polling for admission.
  - Cleans up (leaves the call) on stop() or timeout.

Usage (from meet-bot entrypoint):
    bot = MeetBot(
        meeting_url="https://meet.google.com/abc-defg-hij",
        profile_dir="/Users/you/.brseai_profile",
        display_name="Interpreter Bot",
        headless=False,
        mic_device_label="BlackHole 2ch",   # OS device name Chrome should use
        join_timeout=90,
        leave_after_minutes=120,
        debug=False,
    )
    await bot.start()          # opens browser, joins meeting
    await bot.wait_until_done()  # blocks until leave_after_minutes or stop()
    await bot.stop()           # leaves call + closes browser
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.common.logging_utils import get_logger
from src.meet.selectors import SEL, first_matching_selector

logger = get_logger("meet.bot")

# How often to poll for waiting-room admission (seconds)
_POLL_INTERVAL = 3.0
# How long to wait for a selector before trying the next one (ms)
_SELECTOR_TIMEOUT_MS = 3000
# Max attempts to click join button before giving up
_JOIN_CLICK_ATTEMPTS = 3


class MeetBotError(Exception):
    """Raised when the bot cannot join or loses the meeting."""


class MeetBot:
    """
    Joins a Google Meet via Playwright/Chromium with a persistent profile.

    Audio routing is entirely virtual-device based — this class does NOT
    capture or inject audio itself.  The caller is responsible for routing:
      - Chrome speaker output  -> virtual loopback device -> MeetAudioListenerInput
      - MeetAudioMicOutput     -> virtual mic device      -> Chrome microphone input

    Permissions granted automatically:
      - microphone: true   (so the virtual mic device is available to Chrome)
      - camera: false
      - notifications: false
    """

    def __init__(
        self,
        meeting_url: str,
        profile_dir: str,
        display_name: str = "Interpreter Bot",
        headless: bool = False,
        mic_device_label: Optional[str] = None,
        join_timeout: int = 90,
        leave_after_minutes: Optional[int] = None,
        debug: bool = False,
    ) -> None:
        self.meeting_url = meeting_url
        self.profile_dir = profile_dir
        self.display_name = display_name
        self.headless = headless
        self.mic_device_label = mic_device_label
        self.join_timeout = join_timeout
        self.leave_after_minutes = leave_after_minutes
        self.debug = debug

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._joined = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._admitted = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open browser, navigate to the meeting URL, and join."""
        from playwright.async_api import async_playwright

        logger.info(f"[MeetBot] Starting browser (headless={self.headless})")
        self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--use-fake-ui-for-media-stream",  # auto-grant mic/camera in Chrome
            "--no-default-browser-check",
            "--disable-extensions",
        ]
        if self.headless:
            launch_args.append("--headless=new")

        self._browser = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=self.headless,
            args=launch_args,
            permissions=["microphone"],
            ignore_https_errors=True,
        )

        # Use first page if it already exists
        pages = self._browser.pages
        self._page = pages[0] if pages else await self._browser.new_page()
        self._page.set_default_timeout(self.join_timeout * 1000)

        if self.debug:
            self._page.on("console", lambda m: logger.debug(f"[browser] {m.text}"))

        await self._navigate_and_join()

    async def stop(self) -> None:
        """Leave the call and close the browser."""
        self._stop_event.set()
        if self._page and not self._page.is_closed():
            await self._leave_call()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            await self._playwright.stop()
        logger.info("[MeetBot] Browser closed.")

    async def wait_until_done(self) -> None:
        """
        Block until leave_after_minutes elapses or stop() is called.
        """
        if self.leave_after_minutes:
            timeout = self.leave_after_minutes * 60
            logger.info(f"[MeetBot] Will auto-leave after {self.leave_after_minutes} min.")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.info("[MeetBot] leave_after_minutes reached, leaving call.")
        else:
            await self._stop_event.wait()

    @property
    def is_joined(self) -> bool:
        return self._joined.is_set()

    # ------------------------------------------------------------------
    # Internal: navigation + join flow
    # ------------------------------------------------------------------

    async def _navigate_and_join(self) -> None:
        page = self._page
        logger.info(f"[MeetBot] Navigating to {self.meeting_url}")
        print(f"[MeetBot] Navigating to {self.meeting_url}", flush=True)

        await page.goto(self.meeting_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Dismiss any one-time popups (cookies, feature announcements)
        await self._dismiss_popups()

        # Fill display name if prompted
        await self._fill_display_name()

        # Turn off camera, set mic state for the pre-join lobby
        await self._set_preflight_av()

        # Click join / ask-to-join
        joined = await self._click_join_button()
        if not joined:
            raise MeetBotError("Could not find or click the Join button.")

        # Wait for admission if we land in a waiting room
        await self._wait_for_admission()

        self._joined.set()
        print(f"[MeetBot] joined | url={self.meeting_url}", flush=True)
        logger.info("[MeetBot] In call.")

    async def _dismiss_popups(self) -> None:
        """Try to dismiss any interstitial dialogs."""
        for sel in SEL["dismiss_popup"]:
            try:
                btn = self._page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    logger.debug(f"[MeetBot] Dismissed popup via {sel!r}")
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    async def _fill_display_name(self) -> None:
        """If Meet shows a name input, fill it with display_name."""
        for sel in SEL["name_input"]:
            try:
                inp = self._page.locator(sel).first
                if await inp.is_visible(timeout=2000):
                    await inp.triple_click()
                    await inp.type(self.display_name, delay=50)
                    logger.debug(f"[MeetBot] Filled display name via {sel!r}")
                    return
            except Exception:
                pass

    async def _set_preflight_av(self) -> None:
        """In the pre-join lobby: turn camera OFF, mic state depends on flag."""
        # Camera OFF
        for sel in SEL["camera_button"]:
            try:
                btn = self._page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    label = (await btn.get_attribute("aria-label") or "").lower()
                    # If camera is currently ON (label says "turn off"), click to turn off
                    if "turn off" in label or "disable" in label:
                        await btn.click()
                        logger.debug("[MeetBot] Turned camera OFF in pre-join")
                    break
            except Exception:
                pass

        # Mic: leave it as whatever the OS virtual device provides.
        # The caller controls audio by routing through virtual devices.

    async def _click_join_button(self) -> bool:
        """Click the Join Now / Ask to Join button. Returns True on success."""
        for attempt in range(1, _JOIN_CLICK_ATTEMPTS + 1):
            for sel in SEL["join_button"]:
                try:
                    btn = self._page.locator(sel).first
                    if await btn.is_visible(timeout=_SELECTOR_TIMEOUT_MS):
                        print(f"[MeetBot] Clicking join ({sel!r}, attempt {attempt})", flush=True)
                        await btn.click()
                        await asyncio.sleep(1.5)
                        return True
                except Exception as exc:
                    logger.debug(f"[MeetBot] join selector {sel!r} failed: {exc}")

            # If no button found yet, wait a bit and retry
            logger.debug(f"[MeetBot] Join button not found, waiting... (attempt {attempt})")
            await asyncio.sleep(2)

        return False

    async def _wait_for_admission(self) -> None:
        """
        If the bot lands in a waiting room, poll until admitted or timeout.
        Detection heuristic: waiting room indicators disappear once admitted.
        """
        # Check if we're in waiting room
        in_waiting = False
        for sel in SEL["admit_self_banner"]:
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=3000):
                    in_waiting = True
                    logger.info("[MeetBot] In waiting room — polling for admission...")
                    print("[MeetBot] In waiting room — polling for admission...", flush=True)
                    break
            except Exception:
                pass

        if not in_waiting:
            return  # already admitted directly

        deadline = asyncio.get_event_loop().time() + self.join_timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            # Check if the waiting room banner is gone (we were admitted)
            still_waiting = False
            for sel in SEL["admit_self_banner"]:
                try:
                    el = self._page.locator(sel).first
                    if await el.is_visible(timeout=1000):
                        still_waiting = True
                        break
                except Exception:
                    pass
            if not still_waiting:
                logger.info("[MeetBot] Admitted to meeting.")
                print("[MeetBot] Admitted to meeting.", flush=True)
                return

        raise MeetBotError(
            f"Timed out waiting for admission after {self.join_timeout}s. "
            "Ask the meeting host to admit the bot."
        )

    # ------------------------------------------------------------------
    # Internal: in-call controls
    # ------------------------------------------------------------------

    async def _leave_call(self) -> None:
        """Click Leave Call button."""
        for sel in SEL["leave_button"]:
            try:
                btn = self._page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(1)
                    logger.info("[MeetBot] Left call.")
                    return
            except Exception:
                pass
        logger.debug("[MeetBot] Leave button not found — closing browser anyway.")
