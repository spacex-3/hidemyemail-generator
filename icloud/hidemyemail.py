import asyncio
import random

from curl_cffi.requests import AsyncSession


# Browser fingerprint profiles — Safari-heavy since it's the most natural
# client for iCloud. Each entry: (impersonate_target, matching_headers)
BROWSER_PROFILES = [
    {
        "impersonate": "safari15_3",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.3 Safari/605.1.15",
        "sec_ch_ua": None,  # Safari doesn't send sec-ch-ua
        "sec_ch_ua_mobile": None,
        "sec_ch_ua_platform": None,
    },
    {
        "impersonate": "safari17_0",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "sec_ch_ua": None,
        "sec_ch_ua_mobile": None,
        "sec_ch_ua_platform": None,
    },
    {
        "impersonate": "safari18_0",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "sec_ch_ua": None,
        "sec_ch_ua_mobile": None,
        "sec_ch_ua_platform": None,
    },
    {
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"macOS"',
    },
    {
        "impersonate": "chrome131",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"macOS"',
    },
]

# Accept-Language variants to add diversity
_LANG_VARIANTS = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.8",
    "en-GB,en-US;q=0.9,en;q=0.8",
    "en-US,en-GB;q=0.9,en;q=0.7",
    "en,en-US;q=0.9",
    "en-US,en;q=0.9,zh-CN;q=0.8",
    "en-US,en;q=0.9,ja;q=0.8",
]

# Random delay range (seconds) injected before each API call
MIN_DELAY = 1.0
MAX_DELAY = 4.0

# Keywords that indicate Apple's rate limiting
_RATE_LIMIT_KEYWORDS = [
    "reached the limit",
    "rate limit",
    "try again later",
]


def is_rate_limited(response: dict) -> bool:
    """Check if an API response indicates Apple's rate limiting."""
    if not response:
        return False
    if response.get("success"):
        return False

    # Extract error message from various response formats
    error = response.get("error", {})
    reason = ""
    if isinstance(error, int) and "reason" in response:
        reason = response["reason"]
    elif isinstance(error, dict) and "errorMessage" in error:
        reason = error["errorMessage"]

    reason_lower = reason.lower()
    return any(kw in reason_lower for kw in _RATE_LIMIT_KEYWORDS)


def _pick_profile() -> dict:
    """Pick a random browser profile and return assembled headers."""
    profile = random.choice(BROWSER_PROFILES)
    lang = random.choice(_LANG_VARIANTS)

    headers = {
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "User-Agent": profile["user_agent"],
        "Content-Type": "text/plain",
        "Accept": "*/*",
        "Origin": "https://www.icloud.com",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://www.icloud.com/",
        "Accept-Language": lang,
    }

    # Chrome-family browsers send sec-ch-ua headers; Safari does not
    if profile["sec_ch_ua"] is not None:
        headers["sec-ch-ua"] = profile["sec_ch_ua"]
        headers["sec-ch-ua-mobile"] = profile["sec_ch_ua_mobile"]
        headers["sec-ch-ua-platform"] = profile["sec_ch_ua_platform"]
        headers["Sec-GPC"] = "1"

    return {
        "impersonate": profile["impersonate"],
        "headers": headers,
    }


async def _human_delay():
    """Sleep for a random duration to mimic human interaction pacing."""
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


class HideMyEmail:
    base_url_v1 = "https://p68-maildomainws.icloud.com/v1/hme"
    base_url_v2 = "https://p68-maildomainws.icloud.com/v2/hme"
    params = {
        "clientBuildNumber": "2536Project32",
        "clientMasteringNumber": "2536B20",
        "clientId": "",
        "dsid": "", # Directory Services Identifier (DSID) is a method of identifying AppleID accounts
    }

    def __init__(self, label: str = "", cookies: str = ""):
        """Initializes the HideMyEmail class.

        The `label` argument is kept for compatibility, but reserve metadata is
        generated per request.

        Args:
            label (str)     Compatibility argument retained for existing callers.
            cookies (str)   Cookie string to be used with requests. Required for authorization.
        """
        self.label = label.strip()

        # Cookie string to be used with requests. Required for authorization.
        self.cookies = cookies

    async def __aenter__(self):
        # Pick a random browser profile for this session
        profile = _pick_profile()
        self._impersonate = profile["impersonate"]

        headers = profile["headers"]
        headers["Cookie"] = self.__cookies.strip()

        self.s = AsyncSession(
            headers=headers,
            impersonate=self._impersonate,
            timeout=30,
        )

        return self

    async def __aexit__(self, exc_t, exc_v, exc_tb):
        await self.s.close()

    @property
    def cookies(self) -> str:
        return self.__cookies

    @cookies.setter
    def cookies(self, cookies: str):
        # remove new lines/whitespace for security reasons
        self.__cookies = cookies.strip()

    @property
    def browser_fingerprint(self) -> str:
        """Return the current browser impersonation target name."""
        return getattr(self, "_impersonate", "unknown")

    async def rotate_session(self):
        """Close current session and open a new one with a different browser fingerprint.

        Used after rate-limit cooldowns to present a different TLS/header fingerprint.
        """
        await self.s.close()

        profile = _pick_profile()
        self._impersonate = profile["impersonate"]

        headers = profile["headers"]
        headers["Cookie"] = self.cookies.strip()

        self.s = AsyncSession(
            headers=headers,
            impersonate=self._impersonate,
            timeout=30,
        )

    async def generate_email(self) -> dict:
        """Generates an email"""
        try:
            await _human_delay()
            resp = await self.s.post(
                f"{self.base_url_v1}/generate",
                params=self.params,
                json={"langCode": "en-us"},
            )
            return resp.json()
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

    async def reserve_email(self, email: str) -> dict:
        """Reserves an email and registers it for forwarding"""
        try:
            await _human_delay()
            metadata = _generate_random_metadata()
            payload = {
                "hme": email,
                "label": metadata["label"],
                "note": metadata["note"],
            }
            resp = await self.s.post(
                f"{self.base_url_v1}/reserve",
                params=self.params,
                json=payload,
            )
            return resp.json()
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

    async def list_email(self) -> dict:
        """List all HME"""
        try:
            resp = await self.s.get(f"{self.base_url_v2}/list", params=self.params)
            return resp.json()
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

# ---------------------------------------------------------------------------
# Randomized metadata helpers
# ---------------------------------------------------------------------------

_LABEL_ADJECTIVES = [
    "amber", "calm", "clear", "gentle", "quiet", "silver", "soft", "still",
    "warm", "bright", "cool", "deep", "fair", "light", "swift", "tender",
]
_LABEL_NOUNS = [
    "brook", "garden", "harbor", "meadow", "morning", "orchard", "river", "trail",
    "cove", "field", "grove", "haven", "pine", "ridge", "shore", "vale",
]
_NOTE_TEMPLATES = [
    "Reserved for personal email routing.",
    "Created for inbox organization.",
    "Saved for private forwarding use.",
    "Set aside for personal account use.",
    "Used for individual correspondence management.",
    "Dedicated to private mail forwarding.",
]


def _generate_random_label() -> str:
    word_count = random.choice((2, 3))
    words = [random.choice(_LABEL_ADJECTIVES), random.choice(_LABEL_NOUNS)]
    if word_count == 3:
        words.append(random.choice(_LABEL_NOUNS))
    return " ".join(words)


def _generate_random_metadata() -> dict:
    return {
        "label": _generate_random_label(),
        "note": random.choice(_NOTE_TEMPLATES),
    }
