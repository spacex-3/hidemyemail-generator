import asyncio
import unittest
from unittest.mock import AsyncMock

from icloud.hidemyemail import HMEAuthenticationError
from main import GenerationManager, Progress, RichHideMyEmail


class FakeAccountSession:
    def __init__(self, context_result):
        self.context_result = context_result

    def ensure_authenticated(self):
        return "ok"

    def validate_hme_context(self):
        return self.context_result


class GenerationFailureTests(unittest.TestCase):
    def make_hme(self):
        progress = Progress()
        progress.account = "person@example.com"
        return RichHideMyEmail(
            account=progress.account,
            cookie_str="cookie=value",
            progress=progress,
        )

    def test_generate_one_raises_terminal_error_for_401(self):
        hme = self.make_hme()
        hme.generate_email = AsyncMock(
            return_value={
                "error": 1,
                "_http_status": 401,
                "reason": "Non-JSON response (body=Forbidden)",
            }
        )

        with self.assertRaisesRegex(HMEAuthenticationError, "401"):
            asyncio.run(hme._generate_one())

        self.assertEqual(hme.generate_email.await_count, 1)

    def test_generate_one_raises_terminal_error_for_403(self):
        hme = self.make_hme()
        hme.generate_email = AsyncMock(
            return_value={
                "error": 1,
                "_http_status": 403,
                "reason": "Non-JSON response (body=<empty>)",
            }
        )

        with self.assertRaisesRegex(HMEAuthenticationError, "403"):
            asyncio.run(hme._generate_one())

        self.assertEqual(hme.generate_email.await_count, 1)

    def test_generate_stops_after_first_authentication_failure(self):
        hme = self.make_hme()
        hme._generate_batch = AsyncMock(
            side_effect=HMEAuthenticationError("HTTP 401: Forbidden")
        )

        asyncio.run(hme.generate(20))

        self.assertEqual(hme._generate_batch.await_count, 1)
        self.assertEqual(hme.progress.status, "error")
        self.assertIn("authentication", hme.progress.message.lower())

    def test_generate_stops_after_first_empty_non_rate_limited_batch(self):
        hme = self.make_hme()
        hme._generate_batch = AsyncMock(return_value=[])

        asyncio.run(asyncio.wait_for(hme.generate(20), timeout=0.05))

        self.assertEqual(hme._generate_batch.await_count, 1)
        self.assertEqual(hme.progress.status, "error")
        self.assertIn("no successful emails", hme.progress.message.lower())

    def test_manager_rejects_incomplete_hme_context_before_starting(self):
        manager = GenerationManager()
        session = FakeAccountSession(
            (False, "HME authorization cookie X-APPLE-WEBAUTH-USER is missing")
        )
        progress = Progress()
        progress.account = "person@example.com"
        manager.accounts[progress.account] = (session, progress)
        manager._run = AsyncMock()

        result = asyncio.run(manager.start_account(progress.account, count=5))

        self.assertIn("X-APPLE-WEBAUTH-USER", result)
        self.assertEqual(progress.status, "error")
        self.assertNotIn(progress.account, manager._tasks)


if __name__ == "__main__":
    unittest.main()
