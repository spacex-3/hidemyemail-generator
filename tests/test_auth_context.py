import tempfile
import unittest
from unittest.mock import patch

from requests.cookies import create_cookie

from icloud.auth import ICloudSession


class AuthContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        patcher = patch("icloud.auth.get_sessions_dir", return_value=self.tempdir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_session(self, domain="cn"):
        return ICloudSession("person@example.com", domain=domain)

    def test_domain_redirect_switches_all_endpoints_to_global(self):
        session = self.make_session("cn")

        changed = session._apply_domain_to_use("iCloud.com")

        self.assertTrue(changed)
        self.assertEqual(session.domain, "com")
        self.assertEqual(session.HOME_ENDPOINT, "https://www.icloud.com")
        self.assertEqual(session.SETUP_ENDPOINT, "https://setup.icloud.com/setup/ws/1")
        self.assertEqual(session.session.headers["Origin"], "https://www.icloud.com")
        self.assertEqual(session.session_data["domain"], "com")

    def test_domain_redirect_switches_all_endpoints_to_china(self):
        session = self.make_session("com")

        changed = session._apply_domain_to_use("iCloud.com.cn")

        self.assertTrue(changed)
        self.assertEqual(session.domain, "cn")
        self.assertEqual(session.AUTH_ROOT, "https://idmsa.apple.com.cn")
        self.assertEqual(session.HOME_ENDPOINT, "https://www.icloud.com.cn")
        self.assertEqual(session.session_data["domain"], "cn")

    def test_maildomain_service_prefers_maildomainws_bootstrap_url(self):
        session = self.make_session("com")
        session.data = {
            "userPartition": 123,
            "webservices": {
                "maildomainws": {"url": "https://p321-maildomainws.icloud.com"},
                "premiummailsettings": {"url": "https://wrong.icloud.com"},
            },
        }

        self.assertEqual(
            session.get_maildomain_service_url(),
            "https://p321-maildomainws.icloud.com",
        )

    def test_maildomain_service_uses_global_user_partition(self):
        session = self.make_session("com")
        session.data = {"userPartition": 92, "webservices": {}}

        self.assertEqual(
            session.get_maildomain_service_url(),
            "https://p92-maildomainws.icloud.com",
        )

    def test_maildomain_service_uses_china_user_partition(self):
        session = self.make_session("cn")
        session.data = {"userPartition": "217", "webservices": {}}

        self.assertEqual(
            session.get_maildomain_service_url(),
            "https://p217-maildomainws.icloud.com.cn",
        )

    def test_hme_context_rejects_missing_webauth_user_cookie(self):
        session = self.make_session("com")
        session.data = {"dsInfo": {"dsid": "12345"}, "userPartition": 68}

        ok, reason = session.validate_hme_context()

        self.assertFalse(ok)
        self.assertIn("X-APPLE-WEBAUTH-USER", reason)

    def test_hme_context_rejects_missing_dsid(self):
        session = self.make_session("com")
        with patch.object(
            session,
            "get_cookie_string",
            return_value='X-APPLE-WEBAUTH-USER="v=1:s=0"',
        ):
            ok, reason = session.validate_hme_context()

        self.assertFalse(ok)
        self.assertIn("DSID", reason)

    def test_hme_context_accepts_complete_session(self):
        session = self.make_session("com")
        session.data = {"dsInfo": {"dsid": "12345"}, "userPartition": 68}
        with patch.object(
            session,
            "get_cookie_string",
            return_value='X-APPLE-WEBAUTH-USER="v=1:s=0:d=12345"; other=value',
        ):
            ok, reason = session.validate_hme_context()

        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_cookie_export_only_includes_final_hme_service_domain(self):
        session = self.make_session("com")
        session.data = {"userPartition": 68}
        session.session.cookies.set_cookie(
            create_cookie("GLOBAL", "yes", domain=".icloud.com", path="/")
        )
        session.session.cookies.set_cookie(
            create_cookie("CHINA", "no", domain=".icloud.com.cn", path="/")
        )
        session.session.cookies.set_cookie(
            create_cookie("IDMSA", "no", domain=".apple.com", path="/")
        )

        cookie_string = session.get_cookie_string()

        self.assertIn("GLOBAL=yes", cookie_string)
        self.assertNotIn("CHINA=no", cookie_string)
        self.assertNotIn("IDMSA=no", cookie_string)


if __name__ == "__main__":
    unittest.main()
