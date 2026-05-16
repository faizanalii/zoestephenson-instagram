"""
Instagram Driver — SeleniumBase wrapper for login, human-like browsing, and
cookie extraction.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.request
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
_2FA_CODE_INPUTS = [
    'input[name="verificationCode"]',
    'input[name="code"]',
    'input[type="text"][autocomplete="one-time-code"]',
    'input[type="number"]',
]
_2FA_SUBMIT_BUTTONS = [
    'button[type="submit"]',
]
_2FA_CONFIRM_BUTTONS = [
    'button:contains("This was me")',
    'button:contains("Yes, it was me")',
    'button:contains("It was me")',
    'button:contains("Confirm")',
    'button:contains("Verify")',
    'button:contains("Submit")',
]


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
            headless2=True,
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

            # Handle 2FA if required
            if self._is_2fa_challenge():
                if not self._handle_2fa():
                    return False

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

    def _is_2fa_challenge(self) -> bool:
        current_url = self.sb.get_current_url().lower()
        return "challenge" in current_url or "two_factor" in current_url

    def _fetch_2fa_code(self) -> tuple[str | None, int | None]:
        """Fetch 2FA code and optional expires_in (seconds) from two_factor_url."""
        url = self.account.two_factor_url
        if not url:
            logger.error("No two_factor_url configured for %s", self.account.email)
            return None, None

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8").strip()
        except Exception:
            logger.exception("Failed to fetch 2FA code from %s", url)
            return None, None

        expires_in: int | None = None

        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                code = str(parsed.get("code") or parsed.get("token") or "")
                for key in ("expires_in", "expiry", "ttl", "valid_for"):
                    if key in parsed and parsed[key] is not None:
                        expires_in = int(parsed[key])
                        break
                return (code if code else None, expires_in)
            return (str(parsed), None)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\b(\d{6})\b", data)
        if match:
            return (match.group(1), None)

        code = data if len(data) <= 10 else None
        return (code, None)

    def _handle_2fa(self) -> bool:
        if not self.account.two_factor or not self.account.two_factor_url:
            logger.error(
                "2FA required for %s but two_factor not configured in DB",
                self.account.email,
            )
            return False

        max_attempts = 3
        code: str | None = None

        for attempt in range(max_attempts):
            code, expires_in = self._fetch_2fa_code()
            if not code:
                logger.error("Could not obtain 2FA code for %s", self.account.email)
                return False

            if expires_in is not None and expires_in <= 3:
                if attempt < max_attempts - 1:
                    wait = max(expires_in + 1, 2)
                    logger.info(
                        "2FA code expires in %ss, waiting %ss for fresh code (attempt %s/%s)",
                        expires_in,
                        wait,
                        attempt + 1,
                        max_attempts,
                    )
                    time.sleep(wait)
                    continue
                logger.warning(
                    "2FA code may expire soon but proceeding anyway (last attempt)"
                )

            break

        if not code:
            return False

        logger.info("Submitting 2FA code for %s", self.account.email)

        _random_sleep(2, 4)

        code_input_found = False
        for selector in _2FA_CODE_INPUTS:
            try:
                if self.sb.is_element_visible(selector):
                    self.sb.type(selector, code, timeout=10)
                    code_input_found = True
                    break
            except Exception:
                continue

        if not code_input_found:
            logger.error(
                "Could not find 2FA code input on the page for %s", self.account.email
            )
            return False

        _random_sleep(0.5, 1.5)

        for selector in _2FA_SUBMIT_BUTTONS:
            try:
                if self.sb.is_element_visible(selector):
                    self.sb.click(selector, timeout=5)
                    break
            except Exception:
                continue

        _random_sleep(3, 5)

        self._handle_2fa_confirm()

        _random_sleep(5, 8)
        self._dismiss_popups()

        current_url = self.sb.get_current_url().lower()
        if (
            "login" in current_url
            or "challenge" in current_url
            or "two_factor" in current_url
        ):
            logger.error(
                "2FA may have failed for %s (URL: %s)", self.account.email, current_url
            )
            return False

        logger.info("2FA completed successfully for %s", self.account.email)
        return True

    def _handle_2fa_confirm(self) -> None:
        """Click 'This was me' / Confirm button shown after 2FA code submission."""
        for selector in _2FA_CONFIRM_BUTTONS:
            try:
                if self.sb.is_element_visible(selector):
                    logger.info("Clicking 2FA confirm button: %s", selector)
                    self.sb.click(selector, timeout=5)
                    _random_sleep(1, 2)
                    return
            except Exception:
                continue

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
