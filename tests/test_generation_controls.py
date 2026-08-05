import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from main import GenerationManager, Progress, RichHideMyEmail
from server import DASHBOARD_HTML, handle_start


class FakeAccountSession:
    status = "authenticated"

    def ensure_authenticated(self):
        return "ok"

    def validate_hme_context(self):
        return True, ""


class FakeStartManager:
    def __init__(self):
        self.call = None

    async def start_account(self, account, count, interval=45, cycle_size=5):
        self.call = (account, count, interval, cycle_size)
        return "ok"


class JsonRequest:
    def __init__(self, manager, payload):
        self.match_info = {"account": "person@example.com"}
        self.app = {"manager": manager}
        self.payload = payload

    async def json(self):
        return self.payload


def saved_emails(count):
    return [
        {"email": f"saved-{index}@icloud.com", "time": "2026-08-05 17:00:00"}
        for index in range(count)
    ]


class TotalTargetTests(unittest.TestCase):
    def make_manager(self, existing):
        manager = GenerationManager()
        progress = Progress()
        progress.account = "person@example.com"
        progress.emails = saved_emails(existing)
        manager.accounts[progress.account] = (FakeAccountSession(), progress)
        manager._run = AsyncMock()
        return manager, progress

    def test_start_schedules_only_work_remaining_to_total_target(self):
        manager, progress = self.make_manager(existing=73)

        async def start():
            result = await manager.start_account(progress.account, count=600)
            await asyncio.sleep(0)
            return result

        result = asyncio.run(start())

        self.assertEqual(result, "ok")
        self.assertEqual(progress.completed, 73)
        self.assertEqual(progress.target, 600)
        self.assertEqual(len(progress.emails), 73)
        self.assertEqual(manager._run.await_args.args[2], 527)

    def test_start_finishes_without_task_when_total_target_is_already_met(self):
        manager, progress = self.make_manager(existing=73)

        result = asyncio.run(
            manager.start_account(progress.account, count=70)
        )

        self.assertEqual(result, "ok")
        self.assertEqual(progress.completed, 73)
        self.assertEqual(progress.target, 70)
        self.assertEqual(progress.status, "done")
        self.assertIn("already", progress.message.lower())
        self.assertNotIn(progress.account, manager._tasks)
        manager._run.assert_not_awaited()


class CycleGenerationTests(unittest.TestCase):
    def test_generate_uses_account_cycle_size_instead_of_global_default(self):
        progress = Progress()
        progress.account = "person@example.com"
        progress.target = 6
        progress.cycle_size = 15
        hme = RichHideMyEmail(
            account=progress.account,
            cookie_str="cookie=value",
            progress=progress,
        )

        def generated_batch(batch_size):
            start = progress.completed
            return [
                {
                    "email": f"new-{start + index}@icloud.com",
                    "time": "2026-08-05 17:00:00",
                }
                for index in range(batch_size)
            ]

        hme._generate_batch = AsyncMock(side_effect=generated_batch)
        hme._save_emails = MagicMock()
        hme._long_cooldown = AsyncMock(return_value=False)

        with patch("main.asyncio.sleep", new=AsyncMock()):
            asyncio.run(hme.generate(6))

        self.assertEqual(
            [call.args[0] for call in hme._generate_batch.await_args_list],
            [2, 2, 2],
        )
        hme._long_cooldown.assert_not_awaited()
        self.assertEqual(progress.completed, 6)
        self.assertEqual(progress.success_in_cycle, 6)


class CycleConfigurationTests(unittest.TestCase):
    def make_manager(self, existing=73):
        manager = GenerationManager()
        progress = Progress()
        progress.account = "person@example.com"
        progress.emails = saved_emails(existing)
        manager.accounts[progress.account] = (FakeAccountSession(), progress)
        manager._run = AsyncMock()
        return manager, progress

    def test_start_stores_account_cycle_size(self):
        manager, progress = self.make_manager()

        async def start():
            result = await manager.start_account(
                progress.account,
                count=600,
                cycle_size=15,
            )
            await asyncio.sleep(0)
            return result

        result = asyncio.run(start())

        self.assertEqual(result, "ok")
        self.assertEqual(progress.cycle_size, 15)

    def test_start_enforces_minimum_cycle_size(self):
        manager, progress = self.make_manager()

        async def start():
            result = await manager.start_account(
                progress.account,
                count=600,
                cycle_size=0,
            )
            await asyncio.sleep(0)
            return result

        result = asyncio.run(start())

        self.assertEqual(result, "ok")
        self.assertEqual(progress.cycle_size, 1)

    def test_resume_updates_cycle_size_without_resetting_cycle_progress(self):
        manager, progress = self.make_manager()
        progress.target = 600
        progress.completed = 73
        progress.success_in_cycle = 5
        progress.cycle_size = 5

        async def resume():
            result = await manager.resume_account(
                progress.account,
                cycle_size=15,
            )
            await asyncio.sleep(0)
            return result

        result = asyncio.run(resume())

        self.assertEqual(result, "ok")
        self.assertEqual(progress.cycle_size, 15)
        self.assertEqual(progress.success_in_cycle, 5)

    def test_resume_preserves_cycle_size_when_not_sent(self):
        manager, progress = self.make_manager()
        progress.target = 600
        progress.completed = 73
        progress.cycle_size = 15

        async def resume():
            result = await manager.resume_account(progress.account)
            await asyncio.sleep(0)
            return result

        result = asyncio.run(resume())

        self.assertEqual(result, "ok")
        self.assertEqual(progress.cycle_size, 15)

    def test_start_handler_forwards_cycle_size(self):
        manager = FakeStartManager()
        request = JsonRequest(
            manager,
            {"count": 600, "interval": 66, "cycle_size": 15},
        )

        response = asyncio.run(handle_start(request))

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), {"result": "ok"})
        self.assertEqual(
            manager.call,
            ("person@example.com", 600, 66, 15),
        )


class DashboardControlTests(unittest.TestCase):
    def test_card_has_per_account_cycle_size_input(self):
        self.assertIn(">每轮</label>", DASHBOARD_HTML)
        self.assertIn('id="cyi${i}"', DASHBOARD_HTML)
        self.assertIn('min="1" max="999"', DASHBOARD_HTML)

    def test_start_browser_request_sends_cycle_size(self):
        start_function = DASHBOARD_HTML.split("async function goA(i){", 1)[1]
        start_function = start_function.split("async function spA(i){", 1)[0]

        self.assertIn("gid('cyi'+i).value", start_function)
        self.assertIn(
            "JSON.stringify({count:c,interval:itv,cycle_size:cyc})",
            start_function,
        )

    def test_dashboard_syncs_cycle_size_while_running(self):
        update_function = DASHBOARD_HTML.split("function up(a,i){", 1)[1]
        update_function = update_function.split("// ── Helpers", 1)[0]

        self.assertIn("cyi.value=a.cycle_size", update_function)

    def test_progress_bar_percentages_are_clamped_to_100(self):
        self.assertIn(
            "Math.min(100,a.completed/a.target*100)",
            DASHBOARD_HTML,
        )
        self.assertIn(
            "Math.min(100,a.success_in_cycle/a.cycle_size*100)",
            DASHBOARD_HTML,
        )


if __name__ == "__main__":
    unittest.main()
