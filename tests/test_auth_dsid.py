import unittest
import http.cookiejar as cookielib
from types import SimpleNamespace

import requests
from requests.cookies import create_cookie

from icloud.auth import ICloudSession


class ICloudSessionDsidTests(unittest.TestCase):
    def test_get_dsid_falls_back_to_x_apple_webauth_user_cookie(self):
        session = ICloudSession.__new__(ICloudSession)
        session.data = {}
        session.session = requests.Session()
        session.session.cookies.set(
            "X-APPLE-WEBAUTH-USER",
            '"v=1:s=1:d=19268097088"',
        )

        self.assertEqual(session.get_dsid(), "19268097088")

    def test_get_dsid_supports_lwp_cookie_jar_sessions(self):
        session = ICloudSession.__new__(ICloudSession)
        session.data = {}
        jar = cookielib.LWPCookieJar()
        jar.set_cookie(
            create_cookie(
                name="X-APPLE-WEBAUTH-USER",
                value='"v=1:s=1:d=19268097088"',
                domain="setup.icloud.com.cn",
                path="/",
            )
        )
        session.session = SimpleNamespace(cookies=jar)

        self.assertEqual(session.get_dsid(), "19268097088")

    def test_get_maildomain_service_url_reads_premiummailsettings(self):
        session = ICloudSession.__new__(ICloudSession)
        session.data = {
            "webservices": {
                "premiummailsettings": {
                    "url": "https://p217-maildomainws.icloud.com.cn:443/"
                }
            }
        }

        self.assertEqual(
            session.get_maildomain_service_url(),
            "https://p217-maildomainws.icloud.com.cn:443",
        )


if __name__ == "__main__":
    unittest.main()
