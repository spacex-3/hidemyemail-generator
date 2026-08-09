import asyncio
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from mail_service import create_mail_app
from mailbox_store import MailboxStore


class MailServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.store = MailboxStore(self.data_dir)
        self.store.upsert_alias("sold@icloud.com", "owner@example.com")
        self.token = self.store.issue_api_token("sold@icloud.com")
        self.public_id = self.store.get_alias_by_token(self.token)["public_id"]

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_customer_endpoint_returns_only_latest_openai_code_fields(self):
        self.store.record_openai_message(
            alias_email="sold@icloud.com",
            profile_id="profile-1",
            remote_id="100",
            sender="noreply@tm.openai.com",
            subject="Your OpenAI verification code",
            code="123456",
            received_at="2026-08-09T10:00:00+00:00",
        )

        async def request_code():
            app = create_mail_app(
                self.store,
                admin_password="admin-password",
                public_base_url="https://mail.example.com",
                start_receiver=False,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                response = await client.get(
                    f"/api/v1/openai/mailboxes/{self.public_id}/latest",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                return response.status, await response.json()
            finally:
                await client.close()

        status, payload = asyncio.run(request_code())

        self.assertEqual(status, 200)
        self.assertEqual(payload, {
            "success": True,
            "subject": "Your OpenAI verification code",
            "received_at": "2026-08-09T10:00:00+00:00",
            "code": "123456",
        })

    def test_customer_endpoint_rejects_wrong_key_without_leaking_alias(self):
        async def request_code():
            app = create_mail_app(
                self.store,
                admin_password="admin-password",
                public_base_url="https://mail.example.com",
                start_receiver=False,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                response = await client.get(
                    f"/api/v1/openai/mailboxes/{self.public_id}/latest",
                    headers={"Authorization": "Bearer wrong-key"},
                )
                return response.status, await response.json()
            finally:
                await client.close()

        status, payload = asyncio.run(request_code())

        self.assertEqual(status, 404)
        self.assertEqual(payload["success"], False)
        self.assertNotIn("sold@icloud.com", str(payload))

    def test_admin_login_is_required_for_alias_management(self):
        async def admin_status():
            app = create_mail_app(
                self.store,
                admin_password="admin-password",
                public_base_url="https://mail.example.com",
                start_receiver=False,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                denied = await client.get("/api/admin/status")
                login = await client.post(
                    "/api/admin/login", json={"password": "admin-password"}
                )
                allowed = await client.get("/api/admin/status")
                return denied.status, login.status, allowed.status, await allowed.json()
            finally:
                await client.close()

        denied, login, allowed, payload = asyncio.run(admin_status())

        self.assertEqual((denied, login, allowed), (401, 200, 200))
        self.assertEqual(payload["aliases"][0]["email"], "sold@icloud.com")
        self.assertEqual(payload["accounts"][0]["source_account"], "owner@example.com")
        self.assertEqual(payload["retention_days"], 7)
        self.assertNotIn("token_hash", payload["aliases"][0])

    def test_mailbox_dashboard_is_a_separate_admin_page(self):
        async def load_page():
            app = create_mail_app(
                self.store,
                admin_password="admin-password",
                public_base_url="https://mail.example.com",
                start_receiver=False,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                redirect = await client.get("/", allow_redirects=False)
                login_page = await client.get("/login")
                await client.post(
                    "/api/admin/login", json={"password": "admin-password"}
                )
                page = await client.get("/")
                return (
                    redirect.status,
                    redirect.headers.get("Location"),
                    await login_page.text(),
                    await page.text(),
                )
            finally:
                await client.close()

        status, location, login_page, page = asyncio.run(load_page())

        self.assertEqual((status, location), (302, "/login"))
        self.assertIn("管理员密码", login_page)
        self.assertIn("Mailbox API", page)
        self.assertIn("/api/admin/profiles", page)

    def test_customer_page_is_browser_facing_and_uses_its_own_key(self):
        async def load_page():
            app = create_mail_app(
                self.store,
                admin_password="admin-password",
                public_base_url="https://mail.example.com",
                start_receiver=False,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                page = await client.get(
                    f"/openai/{self.public_id}?key={self.token}"
                )
                denied = await client.get(f"/openai/{self.public_id}?key=wrong")
                return page.status, await page.text(), denied.status
            finally:
                await client.close()

        status, page, denied = asyncio.run(load_page())

        self.assertEqual((status, denied), (200, 404))
        self.assertIn("OpenAI 验证码", page)
        self.assertIn("sync=0", page)
        self.assertNotIn("sold@icloud.com", page)

    def test_bulk_export_requires_admin_and_marks_aliases_exported(self):
        self.store.upsert_alias("second@icloud.com", "owner@example.com")

        async def export():
            app = create_mail_app(
                self.store,
                admin_password="admin-password",
                public_base_url="https://mail.example.com",
                start_receiver=False,
            )
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                denied = await client.post(
                    "/api/admin/aliases/export",
                    json={"emails": ["sold@icloud.com"]},
                )
                await client.post(
                    "/api/admin/login", json={"password": "admin-password"}
                )
                exported = await client.post(
                    "/api/admin/aliases/export",
                    json={"emails": ["sold@icloud.com", "second@icloud.com"]},
                )
                return denied.status, exported.status, await exported.json()
            finally:
                await client.close()

        denied, status, payload = asyncio.run(export())

        self.assertEqual((denied, status), (401, 200))
        self.assertIn("sold@icloud.com----https://mail.example.com/openai/", payload["export_text"])
        self.assertEqual(len(payload["items"]), 2)
        self.assertTrue(all(item["exported_at"] for item in self.store.list_aliases()))


if __name__ == "__main__":
    unittest.main()
