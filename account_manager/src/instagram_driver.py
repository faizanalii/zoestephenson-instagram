"""
Instagram Driver — SeleniumBase wrapper for login, human-like browsing, and
cookie extraction.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from seleniumbase import SB

from src.account_loader import Account
from src.settings import HUMAN_SIM_DURATION

logger = logging.getLogger(__name__)

# Instagram selectors
_LOGIN_EMAIL = 'input[name="email"]'
_LOGIN_PASSWORD = 'input[name="pass"]'
_LOGIN_BUTTON = 'button[type="submit"]'
_NOT_NOW_BUTTON = 'button:contains("Not Now")'
_SAVE_INFO_NOT_NOW = 'button:contains("Not Now")'
_EXPLORE_LINK = 'a[href="/explore/"]'


class InstagramDriver:
    """Wraps a SeleniumBase UC (undetected-Chrome) session for one Instagram
    account.  Keeps the browser alive across multiple cookie-refresh cycles."""

    def __init__(self, account: Account) -> None:
        self.account = account
        self._sb = None
        self._sb_context = None
        self._logged_in = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the undetected-Chrome browser with the account's proxy."""
        self._sb_context = SB(
            uc=True,
            headless=True,
            # proxy=self.account.proxy,
            chromium_arg="--disable-notifications,--disable-popup-blocking",
        )
        self._sb = self._sb_context.__enter__()
        logger.info(
            "Browser started for %s via proxy %s",
            self.account.email,
            self.account.proxy,
        )

    def stop(self) -> None:
        """Cleanly close the browser."""
        if self._sb_context is not None:
            try:
                self._sb_context.__exit__(None, None, None)
            except Exception:
                logger.exception("Error closing browser for %s", self.account.email)
            finally:
                self._sb = None
                self._sb_context = None
                self._logged_in = False
        logger.info("Browser stopped for %s", self.account.email)

    @property
    def sb(self) -> SB:
        if self._sb is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._sb

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Log into Instagram.  Returns True on success."""
        try:
            self.sb.uc_open_with_reconnect(
                "https://www.instagram.com/accounts/login/", 4
            )
            _random_sleep(3, 5)

            # Accept cookies dialog if present
            self._dismiss_cookie_banner()

            self.sb.type(_LOGIN_EMAIL, self.account.email, timeout=15)
            _random_sleep(0.8, 1.5)
            self.sb.type(_LOGIN_PASSWORD, self.account.password, timeout=15)
            _random_sleep(0.5, 1.2)
            # Press Enter to submit — Instagram doesn't always render a clickable button.
            self.sb.press_keys(_LOGIN_PASSWORD, "\n")

            # Wait for navigation away from login page
            _random_sleep(5, 8)

            # Dismiss "Save Your Login Info?" or "Turn on Notifications" popups
            self._dismiss_popups()

            # Verify we're logged in by checking for the profile icon or feed
            if "login" in self.sb.get_current_url().lower():
                logger.error(
                    "Login may have failed for %s (still on login page)",
                    self.account.email,
                )
                return False

            self._logged_in = True
            logger.info("Logged in as %s", self.account.email)
            return True

        except Exception:
            logger.exception("Login failed for %s", self.account.email)
            return False

    def restore_session(self, cookies: list[dict[str, Any]]) -> bool:
        """Try to restore an authenticated session from a stored cookie jar."""
        if not cookies:
            return False

        try:
            self.sb.open("https://www.instagram.com/")
            _random_sleep(2, 4)
            self._dismiss_cookie_banner()
            self.sb.delete_all_cookies()

            added = 0
            for cookie in cookies:
                normalized = _normalize_cookie(cookie)
                if not normalized:
                    continue
                try:
                    self.sb.driver.add_cookie(normalized)
                    added += 1
                except Exception:
                    logger.debug(
                        "Could not restore cookie %s for %s",
                        normalized.get("name"),
                        self.account.email,
                    )

            if not added:
                return False

            self.sb.refresh()
            _random_sleep(3, 5)
            self._dismiss_popups()
            self._logged_in = self.is_logged_in()
            if self._logged_in:
                logger.info("Restored Instagram session for %s", self.account.email)
            return self._logged_in
        except Exception:
            logger.exception("Failed to restore session for %s", self.account.email)
            return False

    # ------------------------------------------------------------------
    # Human-like browsing
    # ------------------------------------------------------------------

    def simulate_human_behaviour(self, duration: int | None = None) -> None:
        """Browse Instagram like a human for *duration* seconds.

        Randomly picks from: scroll feed, visit explore, pause, scroll up,
        open a random post, go back.
        """
        duration = duration or HUMAN_SIM_DURATION
        end_time = time.monotonic() + duration
        actions = [
            self._scroll_down,
            self._scroll_up,
            self._visit_explore,
            self._idle_pause,
            self._open_random_post,
        ]

        while time.monotonic() < end_time:
            action = random.choice(actions)
            try:
                action()
            except Exception:
                logger.debug("Human-sim action %s failed (non-fatal)", action.__name__)
            _random_sleep(2, 6)

    # ---- individual micro-actions ----

    def _scroll_down(self) -> None:
        distance = random.randint(300, 900)
        self.sb.execute_script(f"window.scrollBy(0, {distance});")
        logger.debug("Scrolled down %spx", distance)

    def _scroll_up(self) -> None:
        distance = random.randint(100, 400)
        self.sb.execute_script(f"window.scrollBy(0, -{distance});")
        logger.debug("Scrolled up %spx", distance)

    def _visit_explore(self) -> None:
        self.sb.open("https://www.instagram.com/explore/")
        _random_sleep(2, 4)
        self._scroll_down()

    def _idle_pause(self) -> None:
        """Just stare at the screen like a real person."""
        _random_sleep(3, 8)

    def _open_random_post(self) -> None:
        """Click a random post link on the current page, wait, then go back."""
        links = self.sb.find_elements('a[href*="/p/"]')
        if not links:
            links = self.sb.find_elements('a[href*="/reel/"]')
        if links:
            target = random.choice(links[:12])  # pick from the first visible ones
            try:
                target.click()
                _random_sleep(2, 5)
                self.sb.go_back()
                _random_sleep(1, 2)
            except Exception:
                pass  # element may have gone stale

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    def get_cookies_dict(self) -> dict[str, str]:
        """Return all browser cookies as a flat {name: value} dict."""
        raw_cookies = self.get_cookies()
        return {
            c["name"]: c["value"] for c in raw_cookies if "name" in c and "value" in c
        }

    def get_cookies(self) -> list[dict[str, Any]]:
        """Return the raw Selenium cookie jar."""
        raw_cookies = self.sb.get_cookies()
        return [cookie for cookie in raw_cookies if isinstance(cookie, dict)]

    def is_logged_in(self) -> bool:
        """Best-effort check that the current browser session is authenticated."""
        try:
            self.sb.open("https://www.instagram.com/")
            _random_sleep(2, 4)
            current_url = self.sb.get_current_url().lower()
        except Exception:
            logger.exception(
                "Unable to validate login state for %s", self.account.email
            )
            return False

        if any(
            marker in current_url for marker in ("challenge", "checkpoint", "suspended")
        ):
            logger.error(
                "Account %s hit an Instagram checkpoint: %s",
                self.account.email,
                current_url,
            )
            return False

        return "login" not in current_url

    def get_login_failure_reason(self) -> str:
        """Return a human-readable reason when session auth fails."""
        try:
            current_url = self.sb.get_current_url().lower()
        except Exception:
            return "Browser session failed before Instagram login could be validated"

        if "challenge" in current_url:
            return "Instagram challenge required"
        if "checkpoint" in current_url:
            return "Instagram checkpoint required"
        if "suspended" in current_url:
            return "Instagram account appears suspended"
        if "login" in current_url:
            return "Instagram login failed or session expired"
        return f"Instagram session invalid at URL: {current_url}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dismiss_cookie_banner(self) -> None:
        """Click 'Allow all cookies' or 'Accept' if the EU banner is shown."""
        for selector in [
            'button:contains("Allow")',
            'button:contains("Accept")',
            'button:contains("Only Allow Essential")',
        ]:
            try:
                if self.sb.is_element_visible(selector):
                    self.sb.click(selector, timeout=3)
                    _random_sleep(0.5, 1)
                    return
            except Exception:
                continue

    def _dismiss_popups(self) -> None:
        """Dismiss post-login popups (save info, notifications)."""
        for _ in range(3):
            for selector in [_NOT_NOW_BUTTON, _SAVE_INFO_NOT_NOW]:
                try:
                    if self.sb.is_element_visible(selector):
                        self.sb.click(selector, timeout=3)
                        _random_sleep(1, 2)
                except Exception:
                    continue
            _random_sleep(1, 2)


# ------------------------------------------------------------------
# Module-level helper
# ------------------------------------------------------------------


def _random_sleep(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def _normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any] | None:
    name = cookie.get("name")
    value = cookie.get("value")
    if not name or value is None:
        return None

    normalized: dict[str, Any] = {"name": name, "value": value}
    for key in ("domain", "path", "expiry", "secure", "httpOnly", "sameSite"):
        if key in cookie and cookie[key] is not None:
            normalized[key] = cookie[key]
    return normalized
