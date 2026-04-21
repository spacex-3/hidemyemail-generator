import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server import handle_add_account, handle_verify_2fa


class _ExplodingManager:
    async def add_account(self, apple_id: str, password: str, domain: str = "cn"):
        raise RuntimeError("boom-add")

    async def verify_2fa(self, apple_id: str, code: str):
        raise RuntimeError("boom-2fa")


class ApiErrorHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app["manager"] = _ExplodingManager()
        app.router.add_post("/api/accounts/add", handle_add_account)
        app.router.add_post("/api/accounts/{account}/verify-2fa", handle_verify_2fa)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_add_account_returns_json_when_manager_raises(self):
        resp = await self.client.post(
            "/api/accounts/add",
            json={"apple_id": "user@example.com", "password": "pw", "domain": "com"},
        )

        self.assertEqual(resp.status, 500)
        self.assertEqual(resp.content_type, "application/json")
        payload = await resp.json()
        self.assertEqual(payload["result"], "Server error: boom-add")

    async def test_verify_2fa_returns_json_when_manager_raises(self):
        resp = await self.client.post(
            "/api/accounts/user@example.com/verify-2fa",
            json={"code": "123456"},
        )

        self.assertEqual(resp.status, 500)
        self.assertEqual(resp.content_type, "application/json")
        payload = await resp.json()
        self.assertEqual(payload["result"], "Server error: boom-2fa")


if __name__ == "__main__":
    unittest.main()
