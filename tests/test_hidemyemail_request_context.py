import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from curl_cffi.requests.impersonate import BrowserTypeLiteral

from icloud.hidemyemail import HideMyEmail
from main import GenerationManager, Progress


class HideMyEmailRequestContextTests(unittest.TestCase):
    def test_instances_do_not_share_request_params(self):
        first = HideMyEmail(cookies="session=one")
        second = HideMyEmail(cookies="session=two")

        first.params["dsid"] = "12345"
        first.params["clientId"] = "client-one"

        self.assertEqual(second.params["dsid"], "")
        self.assertEqual(second.params["clientId"], "")

    def test_default_request_params_match_current_web_build(self):
        client = HideMyEmail(cookies="session=one")

        self.assertEqual(client.params["clientBuildNumber"], "2612Build17")
        self.assertEqual(client.params["clientMasteringNumber"], "2612Build17")

    def test_configure_service_context_updates_base_urls_origin_and_lang_code(self):
        client = HideMyEmail(cookies="session=one")

        client.configure_service_context(
            service_url="https://p217-maildomainws.icloud.com.cn:443/",
            home_endpoint="https://www.icloud.com.cn",
        )

        self.assertEqual(
            client.base_url_v1,
            "https://p217-maildomainws.icloud.com.cn:443/v1/hme",
        )
        self.assertEqual(
            client.base_url_v2,
            "https://p217-maildomainws.icloud.com.cn:443/v2/hme",
        )
        self.assertEqual(client.request_origin, "https://www.icloud.com.cn")
        self.assertEqual(client.request_referer, "https://www.icloud.com.cn/")
        self.assertEqual(client.lang_code, "zh-tw")

    def test_cn_context_uses_runtime_supported_chrome_profile(self):
        client = HideMyEmail(cookies="session=one")

        client.configure_service_context(home_endpoint="https://www.icloud.com.cn")

        supported = set(BrowserTypeLiteral.__args__)
        if "chrome146" in supported:
            expected = "chrome146"
        elif "chrome124" in supported:
            expected = "chrome124"
        elif "chrome131" in supported:
            expected = "chrome131"
        else:
            expected = None

        self.assertEqual(client.preferred_profile, expected)


class _FakeResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    text = '{"success": true}'

    def json(self):
        return {"success": True}


class _RecordingAsyncSession:
    def __init__(self):
        self.post_calls = []

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return _FakeResponse()


class HideMyEmailRequestPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_email_uses_text_plain_json_payload_with_cn_lang_code(self):
        client = HideMyEmail(cookies="session=one")
        client.configure_service_context(home_endpoint="https://www.icloud.com.cn")
        client.s = _RecordingAsyncSession()

        with patch("icloud.hidemyemail._human_delay", new=AsyncMock()):
            await client.generate_email()

        self.assertEqual(len(client.s.post_calls), 1)
        _, kwargs = client.s.post_calls[0]
        self.assertEqual(kwargs["data"], '{"langCode":"zh-tw"}')
        self.assertNotIn("json", kwargs)


class _FakeHideMyEmail:
    last_instance = None

    def __init__(self, account: str, cookie_str: str, progress: Progress):
        self.account = account
        self.cookie_str = cookie_str
        self.progress = progress
        self.params = {
            "clientBuildNumber": "2612Build17",
            "clientMasteringNumber": "2612Build17",
            "clientId": "",
            "dsid": "",
        }
        self.base_url_v1 = "https://p68-maildomainws.icloud.com/v1/hme"
        self.base_url_v2 = "https://p68-maildomainws.icloud.com/v2/hme"
        self.request_origin = "https://www.icloud.com"
        self.request_referer = "https://www.icloud.com/"
        self.lang_code = "en-us"
        self.generate_calls = []
        self.rotate_calls = 0
        self._fingerprint = "unknown"
        _FakeHideMyEmail.last_instance = self

    async def __aenter__(self):
        self._fingerprint = "initial-fingerprint"
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


    @property
    def browser_fingerprint(self):
        return self._fingerprint

    async def rotate_session(self):
        self.rotate_calls += 1
        self._fingerprint = "chrome146"

    def configure_service_context(self, service_url: str = "", home_endpoint: str = ""):
        if service_url:
            service_url = service_url.rstrip("/")
            self.base_url_v1 = f"{service_url}/v1/hme"
            self.base_url_v2 = f"{service_url}/v2/hme"
        if home_endpoint:
            self.request_origin = home_endpoint.rstrip("/")
            self.request_referer = f"{self.request_origin}/"
            if self.request_origin.endswith(".com.cn"):
                self.lang_code = "zh-tw"

    async def generate(self, count: int, stop_event: asyncio.Event):
        self.generate_calls.append((count, stop_event))


class GenerationManagerRequestContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_bootstraps_session_and_applies_dynamic_maildomain_context(self):
        manager = GenerationManager()
        progress = Progress()
        session = Mock()
        session.get_cookie_string.return_value = "session=value"
        session.get_dsid.return_value = "987654321"
        session.validate_token.return_value = True
        session.get_maildomain_service_url.return_value = "https://p217-maildomainws.icloud.com.cn:443"
        session.HOME_ENDPOINT = "https://www.icloud.com.cn"
        session.client_id = "auth-9e5ccbaf-f7c5-4536-8c65-0040abefeaab"
        stop_event = asyncio.Event()

        with patch("main.RichHideMyEmail", _FakeHideMyEmail):
            await manager._run("user@example.com", session, 5, progress, stop_event)

        hme = _FakeHideMyEmail.last_instance
        self.assertIsNotNone(hme)
        session.validate_token.assert_called_once_with()
        self.assertEqual(hme.params["dsid"], "987654321")
        self.assertEqual(hme.params["clientId"], "9e5ccbaf-f7c5-4536-8c65-0040abefeaab")
        self.assertEqual(
            hme.base_url_v1,
            "https://p217-maildomainws.icloud.com.cn:443/v1/hme",
        )
        self.assertEqual(
            hme.base_url_v2,
            "https://p217-maildomainws.icloud.com.cn:443/v2/hme",
        )
        self.assertEqual(hme.request_origin, "https://www.icloud.com.cn")
        self.assertEqual(hme.request_referer, "https://www.icloud.com.cn/")
        self.assertEqual(hme.lang_code, "zh-tw")
        self.assertEqual(hme.rotate_calls, 1)
        self.assertEqual(hme.generate_calls, [(5, stop_event)])


if __name__ == "__main__":
    unittest.main()
