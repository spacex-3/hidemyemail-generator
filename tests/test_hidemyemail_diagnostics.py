import unittest
from unittest.mock import AsyncMock, patch

from icloud.hidemyemail import HideMyEmail


class _NonJsonResponse:
    def __init__(self, status_code=403, content_type="text/html; charset=utf-8", text="<html>Denied by upstream</html>"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = text

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, params=None, json=None):
        self.calls.append({"url": url, "params": params, "json": json})
        return self.response


class NonJsonResponseDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_email_reports_response_details_when_json_decode_fails(self):
        client = HideMyEmail(cookies="session=value")
        client.s = _FakeSession(_NonJsonResponse())

        with patch("icloud.hidemyemail._human_delay", new=AsyncMock()):
            result = await client.generate_email()

        self.assertEqual(result["error"], 1)
        self.assertIn("Non-JSON response during generate_email", result["reason"])
        self.assertIn("status=403", result["reason"])
        self.assertIn("content-type=text/html; charset=utf-8", result["reason"])
        self.assertIn("Denied by upstream", result["reason"])


if __name__ == "__main__":
    unittest.main()
