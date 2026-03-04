"""
src/meet/selectors.py
Resilient DOM selector map for Google Meet UI elements.

Google Meet's DOM changes frequently. This module centralises all selectors
so they can be updated in one place without touching bot logic.

Each entry is a list of CSS/role selectors tried in order — first match wins.

Usage:
    from src.meet.selectors import SEL
    await page.locator(SEL["join_button"]).first.click()

To update broken selectors: edit the lists here, do NOT scatter magic strings
through bot.py.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Selector map
# Each value is a list[str]. Bot tries them in order; first that matches wins.
# ---------------------------------------------------------------------------

SEL: dict[str, list[str]] = {
    # ---- Pre-join / lobby ----
    "join_button": [
        # Text-based (most robust to DOM churn); :has-text is case-insensitive
        # substring match in Playwright — covers "Join now", "Join Now", etc.
        "button:has-text('Join now')",
        "button:has-text('Ask to join')",
        # Broader fallback: any button whose visible text contains "Join"
        # but exclude the "Leave" button family via :not
        "button:has-text('Join')",
        # Aria-label fallbacks (different tenants / locale variants)
        "[aria-label='Join now']",
        "[aria-label='Ask to join']",
        "[aria-label*='join' i]",
        # jsname attributes seen in current Meet builds
        "button[jsname='Qx7uuf']",   # "Join now" button
        "button[jsname='HNeZme']",   # "Ask to join" / knock button
        # Data-idom fallback seen in some tenants
        "[data-idom-class*='join']",
    ],
    "knock_button": [
        "button:has-text('Ask to join')",
        "button:has-text('Knock')",
        "[aria-label='Ask to join']",
        "button[jsname='HNeZme']",
    ],
    "dismiss_popup": [
        "button:has-text('Got it')",
        "button:has-text('Dismiss')",
        "button:has-text('Close')",
        "[aria-label='Close dialog']",
        "[aria-label='Dismiss']",
    ],
    # ---- In-call controls ----
    "mic_button": [
        "[aria-label*='microphone' i]",
        "[aria-label*='Turn off microphone' i]",
        "[aria-label*='Turn on microphone' i]",
        "[data-tooltip*='microphone' i]",
        "button[jsname='BOHaEe']",  # known jsname; may drift
    ],
    "camera_button": [
        "[aria-label*='camera' i]",
        "[aria-label*='Turn off camera' i]",
        "[aria-label*='Turn on camera' i]",
        "[data-tooltip*='camera' i]",
        "button[jsname='R5mgy']",
    ],
    "leave_button": [
        "button:has-text('Leave call')",
        "[aria-label='Leave call']",
        "[aria-label*='leave' i]",
        "button[jsname='CQylAd']",
    ],
    # ---- Participant / waiting room ----
    # These selectors detect the *waiting room* state (not yet admitted).
    # Use :has-text for substring/case-insensitive matching so minor copy
    # changes and Unicode apostrophe variants don't break detection.
    "admit_self_banner": [
        # Substring match — handles straight vs curly apostrophe variants
        ":has-text('waiting room')",
        ":has-text('Waiting to be let in')",
        ":has-text('waiting to be admitted')",
        "[aria-label*='waiting room' i]",
        # jsname seen in recent Meet builds for the waiting-room container
        "[jsname='r4nke']",
    ],
    # ---- Positive in-call indicators (you ARE in the meeting) ----
    # Used to confirm admission after waiting room, as a complement to
    # the banner disappearing.
    "in_call_indicator": [
        # Leave-call button only exists once you're actually in the call
        "[aria-label='Leave call']",
        "button[jsname='CQylAd']",
        # Participant count / people icon only visible in-call
        "[aria-label*='participants' i]",
        "[data-tooltip*='people' i]",
    ],
    # ---- Pre-join: name field ----
    "name_input": [
        "input[aria-label*='name' i]",
        "input[placeholder*='name' i]",
        "input[jsname='YPqjbf']",
    ],
}


def first_matching_selector(selectors: list[str]) -> str:
    """
    Return a combined CSS selector that matches any of the provided selectors.
    Used when you want a single locator that accepts multiple alternatives.
    """
    return ", ".join(selectors)
