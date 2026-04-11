import asyncio
import datetime
import glob
import os
import random
import time
from typing import Union, List, Optional
import re

from rich.console import Console
from rich.table import Table

from icloud import HideMyEmail, is_rate_limited
from icloud.auth import ICloudSession, load_saved_sessions


BATCH_SIZE = 2
CYCLE_SIZE = 5

SHORT_COOLDOWN_MIN = 3.0
SHORT_COOLDOWN_MAX = 5.0

LONG_COOLDOWN_MIN = 40
LONG_COOLDOWN_MAX = 45

console = Console()


# ══════════════════════════════════════════════════════════════
# Progress tracking
# ══════════════════════════════════════════════════════════════

class Progress:
    """Tracks one account's generation state, readable by the web dashboard."""

    def __init__(self):
        self.account = ""
        self.target = 0
        self.completed = 0
        self.emails = []
        self.status = "idle"
        self.fingerprint = ""
        self.cooldown_end = 0
        self.message = ""
        self.errors = 0
        self.success_in_cycle = 0
        self.cycle_size = CYCLE_SIZE
        self.started_at = 0
        self.interval = 45

    def load_historical_emails(self):
        file_path = f"emails-{self.account}.txt"
        self.emails = []
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    parts = line.split(",", 1)
                    if len(parts) == 2:
                        self.emails.append({"email": parts[0], "time": parts[1]})
                    else:
                        self.emails.append({"email": parts[0], "time": ""})

    def to_dict(self):
        return {
            "account": self.account,
            "target": self.target,
            "completed": self.completed,
            "emails": self.emails[:],
            "status": self.status,
            "fingerprint": self.fingerprint,
            "cooldown_end": self.cooldown_end,
            "message": self.message,
            "errors": self.errors,
            "success_in_cycle": self.success_in_cycle,
            "cycle_size": self.cycle_size,
            "started_at": self.started_at,
            "interval": self.interval,
        }

    def reset(self, target: int):
        """Reset for a fresh generation run."""
        self.target = target
        self.completed = 0
        self.errors = 0
        self.success_in_cycle = 0
        self.started_at = 0
        self.cooldown_end = 0
        self.message = ""
        self.status = "idle"
        self.fingerprint = ""


# ══════════════════════════════════════════════════════════════
# HideMyEmail wrapper with rich logging
# ══════════════════════════════════════════════════════════════

class RichHideMyEmail(HideMyEmail):

    def __init__(self, account: str, cookie_str: str, progress: Progress):
        super().__init__()
        self.account = account
        self.table = Table()
        self._rate_limited = False
        self.progress = progress
        self._email_file = f"emails-{account}.txt"
        self.cookies = cookie_str

    @property
    def _tag(self):
        a = self.account
        if len(a) > 18:
            a = a[:16] + ".."
        return f"[bold cyan][{a}][/]"

    # ── single email ─────────────────────────────────────────

    async def _generate_one(self) -> Union[str, None]:
        if self._rate_limited:
            return None

        self.progress.message = "Generating email..."
        gen_res = await self.generate_email()

        if not gen_res:
            self.progress.errors += 1
            return

        if is_rate_limited(gen_res):
            self._rate_limited = True
            console.log(f"{self._tag} [bold yellow][RATE LIMIT][/] Generate blocked")
            return

        if "success" not in gen_res or not gen_res["success"]:
            error = gen_res.get("error", {})
            err_msg = "Unknown"
            if isinstance(error, int) and "reason" in gen_res:
                err_msg = gen_res["reason"]
            elif isinstance(error, dict) and "errorMessage" in error:
                err_msg = error["errorMessage"]
            console.log(f"{self._tag} [bold red][ERR][/] Generate failed: {err_msg}")
            self.progress.errors += 1
            return

        email = gen_res["result"]["hme"]
        console.log(f'{self._tag} [50%] "{email}" - Generated')

        if self._rate_limited:
            return None

        self.progress.message = f'Reserving "{email}"...'
        reserve_res = await self.reserve_email(email)

        if not reserve_res:
            self.progress.errors += 1
            return

        if is_rate_limited(reserve_res):
            self._rate_limited = True
            console.log(
                f'{self._tag} [bold yellow][RATE LIMIT][/] "{email}" - Reserve blocked'
            )
            return

        if "success" not in reserve_res or not reserve_res["success"]:
            error = reserve_res.get("error", {})
            err_msg = "Unknown"
            if isinstance(error, int) and "reason" in reserve_res:
                err_msg = reserve_res["reason"]
            elif isinstance(error, dict) and "errorMessage" in error:
                err_msg = error["errorMessage"]
            console.log(
                f'{self._tag} [bold red][ERR][/] "{email}" - Reserve failed: {err_msg}'
            )
            self.progress.errors += 1
            return

        console.log(f'{self._tag} [100%] "{email}" - Reserved ✓')
        return email

    # ── batch ────────────────────────────────────────────────

    async def _generate_batch(self, count: int):
        tasks = [asyncio.ensure_future(self._generate_one()) for _ in range(count)]
        results = await asyncio.gather(*tasks)
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        batch = []
        for e in results:
            if e:
                batch.append({"email": e, "time": now})
        return batch

    def _save_emails(self, emails: List[dict]):
        if emails:
            with open(self._email_file, "a+", encoding="utf-8") as f:
                lines = [f"{e['email']},{e['time']}" for e in emails]
                f.write(os.linesep.join(lines) + os.linesep)

    # ── cooldown ─────────────────────────────────────────────

    async def _long_cooldown(self, reason: str, stop_event: asyncio.Event = None, override_minutes: int = 0):
        """Returns True if stopped during cooldown."""
        if override_minutes > 0:
            cooldown_minutes = override_minutes
        else:
            base_interval = getattr(self.progress, "interval", 45)
            base_interval = max(30, base_interval)  # minimum 30 min limit
            cooldown_minutes = base_interval + random.randint(1, 3)
        total_seconds = cooldown_minutes * 60

        self.progress.status = "long_cooldown"
        self.progress.cooldown_end = time.time() + total_seconds
        self.progress.message = f"{reason} — {cooldown_minutes} min cooldown"

        console.log(
            f"{self._tag} [bold yellow]⏳ {reason}. "
            f"Pausing {cooldown_minutes} min...[/]"
        )

        for elapsed in range(total_seconds):
            if stop_event and stop_event.is_set():
                self.progress.cooldown_end = 0
                self.progress.status = "stopped"
                self.progress.message = (
                    f"Stopped during cooldown. {self.progress.completed} saved."
                )
                console.log(f"{self._tag} [yellow]Stopped during cooldown[/]")
                return True

            remaining_s = total_seconds - elapsed
            mins, _ = divmod(remaining_s, 60)
            if elapsed % 300 == 0 and elapsed > 0:
                console.log(f"{self._tag} [dim]⏳ {mins}m remaining...[/]")
            await asyncio.sleep(1)

        self.progress.cooldown_end = 0
        console.log(f"{self._tag} [bold green]✓ Cooldown complete[/]")

        self.progress.status = "rotating"
        self.progress.message = "Rotating browser fingerprint..."
        await self.rotate_session()
        self.progress.fingerprint = self.browser_fingerprint
        console.log(
            f"{self._tag} [bold green]🔄 New fingerprint: "
            f"{self.browser_fingerprint}[/]"
        )
        return False

    # ── main generation loop ─────────────────────────────────

    async def generate(self, count: int, stop_event: asyncio.Event = None):
        """Generate `count` emails, appending to existing progress."""
        try:
            if self.progress.started_at == 0:
                self.progress.started_at = time.time()
            self.progress.fingerprint = self.browser_fingerprint
            self.progress.status = "generating"

            console.log(
                f"{self._tag} Starting: {count} emails | "
                f"FP: {self.browser_fingerprint} | "
                f"Batch: {BATCH_SIZE} | Cycle: {CYCLE_SIZE}"
            )

            remaining = count
            success_in_cycle = self.progress.success_in_cycle
            batch_num = 0
            
            recovering_from_cooldown = False
            cycle_rate_limit_retries = 3

            while remaining > 0:
                # ── stop check ──
                if stop_event and stop_event.is_set():
                    self.progress.status = "stopped"
                    self.progress.message = (
                        f"Stopped. {self.progress.completed} emails saved."
                    )
                    console.log(f"{self._tag} [yellow]Stopped by user[/]")
                    return

                cycle_room = max(1, CYCLE_SIZE - success_in_cycle)
                batch_size = min(BATCH_SIZE, remaining, cycle_room)
                batch_num += 1

                # ── short cooldown ──
                if batch_num > 1:
                    cd = random.uniform(SHORT_COOLDOWN_MIN, SHORT_COOLDOWN_MAX)
                    self.progress.status = "short_cooldown"
                    self.progress.cooldown_end = time.time() + cd
                    self.progress.message = f"Short cooldown ({cd:.1f}s)"
                    await asyncio.sleep(cd)
                    self.progress.cooldown_end = 0

                    if stop_event and stop_event.is_set():
                        self.progress.status = "stopped"
                        self.progress.message = (
                            f"Stopped. {self.progress.completed} emails saved."
                        )
                        console.log(f"{self._tag} [yellow]Stopped by user[/]")
                        return

                # ── generate batch ──
                self.progress.status = "generating"
                self.progress.message = (
                    f"Batch #{batch_num} "
                    f"({batch_size} email{'s' if batch_size > 1 else ''})..."
                )
                self._rate_limited = False

                try:
                    batch = await asyncio.wait_for(
                        self._generate_batch(batch_size), 
                        timeout=60.0
                    )
                except asyncio.TimeoutError:
                    console.log(
                        f"{self._tag} [bold red]⚠ Generation timed out (Apple blocked IP). Treating as Rate Limit.[/]"
                    )
                    self._rate_limited = True
                    batch = []
                except Exception as e:
                    console.log(f"{self._tag} [bold red]⚠ Generation error: {e}[/]")
                    batch = []

                if batch:
                    self._save_emails(batch)
                    self.progress.emails.extend(batch)
                    self.progress.completed += len(batch)
                    remaining -= len(batch)
                    success_in_cycle += len(batch)
                    self.progress.success_in_cycle = success_in_cycle
                    
                    recovering_from_cooldown = False
                    cycle_rate_limit_retries = 3

                    console.log(
                        f"{self._tag} [dim]💾 Saved {len(batch)}. "
                        f"Total: {self.progress.completed}/{self.progress.target} | "
                        f"Cycle: {success_in_cycle}/{CYCLE_SIZE}[/]"
                    )

                # ── rate limited ──
                if self._rate_limited:
                    if remaining > 0:
                        if recovering_from_cooldown:
                            # Hit limit immediately after a cooldown -- retry in 5 mins
                            was_stopped = await self._long_cooldown(
                                "Recovery check failed", stop_event, override_minutes=5
                            )
                            if was_stopped:
                                return
                        elif cycle_rate_limit_retries > 0:
                            # Hit limit during active cycle, do a short retry first
                            cycle_rate_limit_retries -= 1
                            console.log(
                                f"{self._tag} [bold yellow]⚠ Rate limited. "
                                f"Retrying ({3 - cycle_rate_limit_retries}/3) in 5s...[/]"
                            )
                            await asyncio.sleep(5)
                            if stop_event and stop_event.is_set():
                                return
                        else:
                            # Max retries exhausted, perform normal long cooldown
                            console.log(
                                f"{self._tag} [bold yellow]⚠ Rate limited max retries. "
                                f"{remaining} remaining[/]"
                            )
                            was_stopped = await self._long_cooldown(
                                "Rate limited exhausted", stop_event
                            )
                            if was_stopped:
                                return
                            recovering_from_cooldown = True
                            cycle_rate_limit_retries = 3
                            success_in_cycle = 0
                            self.progress.success_in_cycle = 0
                            batch_num = 0

                # ── proactive cycle cooldown ──
                elif success_in_cycle >= CYCLE_SIZE and remaining > 0:
                    console.log(
                        f"{self._tag} [bold cyan]🔄 Cycle done "
                        f"({success_in_cycle} emails). Rotating...[/]"
                    )
                    was_stopped = await self._long_cooldown(
                        f"Cycle complete ({success_in_cycle} emails)", stop_event
                    )
                    if was_stopped:
                        return
                    recovering_from_cooldown = True
                    cycle_rate_limit_retries = 3
                    success_in_cycle = 0
                    self.progress.success_in_cycle = 0
                    batch_num = 0

            # ── done ──
            self.progress.status = "done"
            self.progress.message = f"All {self.progress.completed} emails done!"
            console.log(
                f"{self._tag} [bold green]✅ Done! "
                f"{self.progress.completed} emails → {self._email_file}[/]"
            )

        except asyncio.CancelledError:
            self.progress.status = "stopped"
            self.progress.message = "Task cancelled"
        except Exception as e:
            self.progress.status = "error"
            self.progress.message = f"Error: {e}"
            console.log(f"{self._tag} [bold red]Error: {e}[/]")

    # ── list command ─────────────────────────────────────────

    async def list(self, active: bool, search: str) -> None:
        gen_res = await self.list_email()
        if not gen_res:
            return
        if "success" not in gen_res or not gen_res["success"]:
            error = gen_res.get("error", {})
            err_msg = "Unknown"
            if isinstance(error, int) and "reason" in gen_res:
                err_msg = gen_res["reason"]
            elif isinstance(error, dict) and "errorMessage" in error:
                err_msg = error["errorMessage"]
            console.log(f"[bold red][ERR][/] Failed to list: {err_msg}")
            return

        self.table.add_column("Label")
        self.table.add_column("Hide my email")
        self.table.add_column("Created Date Time")
        self.table.add_column("IsActive")

        for row in gen_res["result"]["hmeEmails"]:
            if row["isActive"] == active:
                if search is None or re.search(search, row["label"]):
                    self.table.add_row(
                        row["label"],
                        row["hme"],
                        str(
                            datetime.datetime.fromtimestamp(
                                row["createTimestamp"] / 1000
                            )
                        ),
                        str(row["isActive"]),
                    )
        console.print(self.table)


# ══════════════════════════════════════════════════════════════
# Generation Manager  — controllable via web UI
# ══════════════════════════════════════════════════════════════

class GenerationManager:
    """Manages multi-account generation with Apple ID auth + start/stop/resume."""

    def __init__(self):
        self.accounts = {}       # apple_id -> (ICloudSession, Progress)
        self._tasks = {}         # apple_id -> asyncio.Task
        self._stop_events = {}   # apple_id -> asyncio.Event

    # ── session management ───────────────────────────────────

    def load_sessions(self):
        """Load all previously saved sessions from disk."""
        for session in load_saved_sessions():
            aid = session.apple_id
            if aid not in self.accounts:
                progress = Progress()
                progress.account = aid
                progress.load_historical_emails()
                self.accounts[aid] = (session, progress)
                console.log(f"  • {aid} [dim]({session.status})[/]")

    async def add_account(self, apple_id: str, password: str, domain: str = "cn") -> str:
        """
        Add an account and perform SRP authentication.
        Returns: "ok", "2fa_required", or error string.
        """
        # Check if already exists
        if apple_id in self.accounts:
            session, _ = self.accounts[apple_id]
            # Re-authenticate with new password
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, session.authenticate, password
            )
            return result

        session = ICloudSession(apple_id, domain=domain)
        progress = Progress()
        progress.account = apple_id
        progress.load_historical_emails()
        self.accounts[apple_id] = (session, progress)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, session.authenticate, password)
        console.log(f"[bold]Auth[/] {apple_id}: {result}")
        return result

    async def verify_2fa(self, apple_id: str, code: str) -> str:
        """
        Submit 2FA code for an account.
        Returns: "ok" or error string.
        """
        if apple_id not in self.accounts:
            return "Account not found"

        session, _ = self.accounts[apple_id]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, session.validate_2fa_code, code)
        console.log(f"[bold]2FA[/] {apple_id}: {result}")
        return result

    async def remove_account(self, apple_id: str) -> bool:
        """Remove an account and its session files."""
        if apple_id not in self.accounts:
            return False

        await self._cancel_task(apple_id)
        session, _ = self.accounts[apple_id]
        session.remove()
        del self.accounts[apple_id]
        console.log(f"[bold]Removed[/] {apple_id}")
        return True

    # ── generation control ───────────────────────────────────

    async def start_account(self, apple_id: str, count: int, interval: int = 45):
        """Start fresh generation (resets progress)."""
        if apple_id not in self.accounts:
            return "Account not found"

        # Ensure authentication is valid first
        session, progress = self.accounts[apple_id]
        loop = asyncio.get_event_loop()
        try:
            auth_result = await asyncio.wait_for(
                loop.run_in_executor(None, session.ensure_authenticated),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            auth_result = "Exception: Apple authentication server timed out."
        except Exception as e:
            auth_result = f"Exception: {e}"

        if auth_result != "ok":
            progress.status = "error"
            progress.message = f"Auth: {auth_result}"
            return auth_result

        await self._cancel_task(apple_id)

        progress.reset(count)
        progress.interval = interval

        stop_event = asyncio.Event()
        self._stop_events[apple_id] = stop_event

        task = asyncio.create_task(
            self._run(apple_id, session, count, progress, stop_event)
        )
        self._tasks[apple_id] = task
        return "ok"

    async def stop_account(self, apple_id: str):
        """Signal a running account to stop."""
        if apple_id in self._stop_events:
            self._stop_events[apple_id].set()
        return True

    async def resume_account(self, apple_id: str):
        """Resume a stopped account from where it left off."""
        if apple_id not in self.accounts:
            return "Account not found"

        session, progress = self.accounts[apple_id]
        remaining = progress.target - progress.completed
        if remaining <= 0:
            return "Nothing to resume"

        # Re-check auth
        loop = asyncio.get_event_loop()
        try:
            auth_result = await asyncio.wait_for(
                loop.run_in_executor(None, session.ensure_authenticated),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            auth_result = "Exception: Apple authentication server timed out."
        except Exception as e:
            auth_result = f"Exception: {e}"

        if auth_result != "ok":
            progress.status = "error"
            progress.message = f"Auth: {auth_result}"
            return auth_result

        await self._cancel_task(apple_id)

        stop_event = asyncio.Event()
        self._stop_events[apple_id] = stop_event
        progress.status = "generating"
        progress.message = "Resuming..."

        task = asyncio.create_task(
            self._run(apple_id, session, remaining, progress, stop_event)
        )
        self._tasks[apple_id] = task
        return "ok"

    # ── internals ────────────────────────────────────────────

    async def _cancel_task(self, apple_id: str):
        """Cancel any existing task for an account."""
        if apple_id in self._stop_events:
            self._stop_events[apple_id].set()
        if apple_id in self._tasks and not self._tasks[apple_id].done():
            try:
                await asyncio.wait_for(self._tasks[apple_id], timeout=3.0)
            except asyncio.TimeoutError:
                self._tasks[apple_id].cancel()
                try:
                    await self._tasks[apple_id]
                except (asyncio.CancelledError, Exception):
                    pass
            except Exception:
                pass

    async def _run(self, apple_id, session, count, progress, stop_event):
        """Run generation for a single account in a fresh session."""
        try:
            cookie_str = session.get_cookie_string()
            if not cookie_str:
                progress.status = "error"
                progress.message = "No cookies — auth may have failed"
                return

            async with RichHideMyEmail(
                account=apple_id, cookie_str=cookie_str, progress=progress
            ) as hme:
                await hme.generate(count, stop_event)
        except asyncio.CancelledError:
            progress.status = "stopped"
            progress.message = "Task cancelled"
        except Exception as e:
            progress.status = "error"
            progress.message = f"Error: {e}"
            console.log(f"[bold red][{apple_id}] Error: {e}[/]")

    # ── serialization ────────────────────────────────────────

    def to_dict(self):
        accounts = []
        for aid, (session, progress) in self.accounts.items():
            d = progress.to_dict()
            d["auth_status"] = session.status
            accounts.append(d)

        total_target = sum(p.target for _, (_, p) in self.accounts.items())
        total_completed = sum(p.completed for _, (_, p) in self.accounts.items())
        return {
            "accounts": accounts,
            "total_target": total_target,
            "total_completed": total_completed,
        }


# ══════════════════════════════════════════════════════════════
# Entry points
# ══════════════════════════════════════════════════════════════

async def serve(port: int):
    """Start the web dashboard server (all control via UI)."""
    manager = GenerationManager()

    console.rule("[bold]HideMyEmail Generator[/]")
    console.log("Loading saved sessions...")
    manager.load_sessions()

    if not manager.accounts:
        console.log("[dim]No saved sessions. Add accounts from the dashboard.[/]")

    console.rule()

    from server import start_server
    runner = await start_server(manager, port)
    console.log(f"[bold cyan]📊 Dashboard: http://0.0.0.0:{port}[/]")
    console.log("[dim]Add accounts and control generation from the web UI.[/]")
    console.log("[dim]Press Ctrl+C to exit.[/]")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for acc in list(manager.accounts.keys()):
            await manager._cancel_task(acc)
        await runner.cleanup()


async def list_emails(active: bool, search: str) -> None:
    """List emails for the first discovered account."""
    sessions = load_saved_sessions()
    if not sessions:
        console.log("[bold red]No saved sessions found![/]")
        console.log("[dim]Add an account from the dashboard first.[/]")
        return
    s = sessions[0]
    result = s.ensure_authenticated()
    if result != "ok":
        console.log(f"[bold red]Auth failed: {result}[/]")
        return
    progress = Progress()
    progress.account = s.apple_id
    cookie_str = s.get_cookie_string()
    async with RichHideMyEmail(
        account=s.apple_id, cookie_str=cookie_str, progress=progress
    ) as hme:
        await hme.list(active, search)
