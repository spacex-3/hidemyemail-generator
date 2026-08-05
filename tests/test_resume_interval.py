import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from main import GenerationManager, Progress
from server import DASHBOARD_HTML, handle_resume


class FakeAccountSession:
    def ensure_authenticated(self):
        return "ok"

    def validate_hme_context(self):
        return True, ""


class FakeResumeManager:
    def __init__(self):
        self.call = None

    async def resume_account(self, account, interval=None):
        self.call = (account, interval)
        return "ok"


class FakeRequest:
    def __init__(self, manager, interval):
        self.match_info = {"account": "person@example.com"}
        self.app = {"manager": manager}
        self._interval = interval

    async def json(self):
        return {"interval": self._interval}


class ResumeIntervalTests(unittest.TestCase):
    def make_manager(self, interval=42):
        manager = GenerationManager()
        progress = Progress()
        progress.account = "person@example.com"
        progress.target = 600
        progress.completed = 65
        progress.success_in_cycle = 5
        progress.interval = interval
        manager.accounts[progress.account] = (FakeAccountSession(), progress)
        manager._run = AsyncMock()
        return manager, progress

    def test_manager_resume_updates_interval_without_resetting_progress(self):
        manager, progress = self.make_manager()

        result = asyncio.run(
            manager.resume_account(progress.account, interval=66)
        )

        self.assertEqual(result, "ok")
        self.assertEqual(progress.interval, 66)
        self.assertEqual(progress.target, 600)
        self.assertEqual(progress.completed, 65)
        self.assertEqual(progress.success_in_cycle, 5)

    def test_manager_resume_preserves_interval_when_not_sent(self):
        manager, progress = self.make_manager(interval=42)

        result = asyncio.run(manager.resume_account(progress.account))

        self.assertEqual(result, "ok")
        self.assertEqual(progress.interval, 42)

    def test_manager_resume_enforces_minimum_interval(self):
        manager, progress = self.make_manager(interval=42)

        result = asyncio.run(manager.resume_account(progress.account, interval=5))

        self.assertEqual(result, "ok")
        self.assertEqual(progress.interval, 30)

    def test_resume_handler_forwards_interval_from_json(self):
        manager = FakeResumeManager()
        request = FakeRequest(manager, interval=66)

        response = asyncio.run(handle_resume(request))

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), {"result": "ok"})
        self.assertEqual(manager.call, ("person@example.com", 66))

    def test_resume_browser_request_sends_current_interval(self):
        resume_function = DASHBOARD_HTML.split("async function rsA(i){", 1)[1]
        resume_function = resume_function.split("function cpA(i){", 1)[0]

        self.assertIn("gid('itv'+i).value", resume_function)
        self.assertIn("JSON.stringify({interval:itv})", resume_function)


if __name__ == "__main__":
    unittest.main()
