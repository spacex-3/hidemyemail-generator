import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from icloud.hidemyemail import (
    HideMyEmail,
    _parse_json_response,
    _pick_profile,
    is_authentication_failed,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", content_type="application/json"):
        self.status_code = status_code
        self.payload = payload
        self.text = text
        self.headers = {"content-type": content_type} if content_type else {}

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class HMEProtocolTests(unittest.TestCase):
    def test_client_build_matches_current_upstream_capture(self):
        self.assertEqual(HideMyEmail.params["clientBuildNumber"], "2626Build17")
        self.assertEqual(HideMyEmail.params["clientMasteringNumber"], "2626Build17")

    def test_browser_profile_is_deterministic_and_internally_consistent(self):
        profile = _pick_profile()

        self.assertEqual(profile["impersonate"], "chrome")
        self.assertIn("Chrome/150.0.0.0", profile["headers"]["User-Agent"])
        self.assertIn('"Chromium";v="150"', profile["headers"]["sec-ch-ua"])
        self.assertEqual(profile["headers"]["sec-ch-ua-platform"], '"macOS"')

    def test_china_service_context_uses_current_locale(self):
        hme = HideMyEmail()

        hme.configure_service_context(
            service_url="https://p217-maildomainws.icloud.com.cn",
            home_endpoint="https://www.icloud.com.cn",
        )

        self.assertEqual(hme.lang_code, "zh-cn")
        profile = _pick_profile(hme.preferred_profile)
        headers = hme._build_session_headers(profile)
        self.assertEqual(headers["Origin"], "https://www.icloud.com.cn")
        self.assertEqual(headers["Referer"], "https://www.icloud.com.cn/")

    def test_generate_uses_structured_json_payload(self):
        hme = HideMyEmail(cookies="cookie=value")
        hme.s = FakeSession(
            FakeResponse(payload={"success": True, "result": {"hme": "x@icloud.com"}})
        )

        with patch("icloud.hidemyemail._human_delay", new=AsyncMock()):
            result = asyncio.run(hme.generate_email())

        self.assertTrue(result["success"])
        _, kwargs = hme.s.calls[0]
        self.assertEqual(kwargs["json"], {"langCode": "en-us"})
        self.assertNotIn("data", kwargs)

    def test_non_json_401_is_authentication_failure(self):
        response = FakeResponse(
            status_code=401,
            text="Forbidden",
            content_type="text/plain; charset=UTF-8",
        )

        parsed = _parse_json_response(response, "generate_email")

        self.assertEqual(parsed["_http_status"], 401)
        self.assertTrue(is_authentication_failed(parsed))

    def test_empty_403_is_authentication_failure(self):
        response = FakeResponse(status_code=403, text="", content_type="")

        parsed = _parse_json_response(response, "generate_email")

        self.assertEqual(parsed["_http_status"], 403)
        self.assertTrue(is_authentication_failed(parsed))

    def test_missing_webauth_cookie_error_is_authentication_failure(self):
        response = {
            "success": False,
            "error": {
                "errorCode": "-401",
                "errorMessage": "Missing X-APPLE-WEBAUTH-USER cookie",
            },
        }

        self.assertTrue(is_authentication_failed(response))

    def test_rate_limit_is_not_authentication_failure(self):
        response = {
            "success": False,
            "error": {"errorMessage": "You have reached the limit. Try again later."},
        }

        self.assertFalse(is_authentication_failed(response))


if __name__ == "__main__":
    unittest.main()
