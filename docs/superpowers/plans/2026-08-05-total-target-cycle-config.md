# Total Inventory Target and Configurable Cycle Size Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Treat each target as a final saved-address total and make each account's cooldown cycle size configurable in the dashboard.

**Architecture:** `GenerationManager` derives completed and remaining work from `Progress.emails`, while `Progress` stores the selected cycle size. The embedded dashboard passes that value through aiohttp Start and Resume handlers, and `RichHideMyEmail.generate()` uses the stored value for every cycle decision.

**Tech Stack:** Python, asyncio, aiohttp, embedded JavaScript, unittest, Docker.

## Global Constraints

- Existing saved email history is the inventory source and must never be cleared.
- Start target means final local inventory, not a number of new addresses.
- Cycle size is per account, is at least 1, and defaults to 5 for backward compatibility.
- Resume preserves completed, target, email history, and successes already accumulated in the current cycle.
- Frontend progress widths must never exceed 100 percent.

---

### Task 1: Total-target scheduling

**Files:**
- Create: `tests/test_generation_controls.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `GenerationManager.start_account(apple_id, count, interval=45, cycle_size=5)` where `count` is the final inventory target.
- Produces: `_run(..., remaining, ...)` scheduled with `remaining = max(0, count - len(progress.emails))`.

- [x] **Step 1: Write a failing manager test**

Create authenticated fake sessions and saved progress containing 73 email entries. Assert Start with target 600 sets `completed == 73`, `target == 600`, preserves all entries, and calls `_run` with 527.

- [x] **Step 2: Run the focused test and verify RED**

Run: `./venv/bin/python -m unittest tests.test_generation_controls.TotalTargetTests -v`

Expected: failure showing completed is zero or `_run` receives 600.

- [x] **Step 3: Add the target-already-met test**

Assert Start with 73 saved entries and target 70 returns `ok`, sets status `done`, keeps `completed == 73`, and creates no generation task.

- [x] **Step 4: Implement total-target reset and scheduling**

Change `Progress.reset` to accept the existing count, then update Start to derive existing from `len(progress.emails)`, calculate remaining, and finish immediately when remaining is zero.

- [x] **Step 5: Run the focused tests and verify GREEN**

Run: `./venv/bin/python -m unittest tests.test_generation_controls.TotalTargetTests -v`

Expected: all total-target tests pass.

### Task 2: Account-specific generation cycle

**Files:**
- Modify: `tests/test_generation_controls.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `Progress.cycle_size: int` and `Progress.success_in_cycle: int`.
- Produces: cycle-aware batch capacity and cooldown behavior in `RichHideMyEmail.generate()`.

- [x] **Step 1: Write a failing generation-loop test**

Set `cycle_size = 15`, return successful batches, stop after more than five successes, and assert no long cooldown is entered at five.

- [x] **Step 2: Run the focused test and verify RED**

Run: `./venv/bin/python -m unittest tests.test_generation_controls.CycleGenerationTests -v`

Expected: failure because the hard-coded cycle boundary starts cooldown at five.

- [x] **Step 3: Replace all runtime cycle constants**

Read one normalized `cycle_size` from `progress` in `generate()` and use it in startup logs, cycle-room calculation, progress logs, and proactive cooldown comparison.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run: `./venv/bin/python -m unittest tests.test_generation_controls.CycleGenerationTests -v`

Expected: all cycle generation tests pass.

### Task 3: Start and Resume API propagation

**Files:**
- Modify: `tests/test_generation_controls.py`
- Modify: `tests/test_resume_interval.py`
- Modify: `main.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `GenerationManager.resume_account(apple_id, interval=None, cycle_size=None)`.
- Consumes: Start JSON `{count, interval, cycle_size}` and Resume JSON `{interval, cycle_size}`.

- [x] **Step 1: Write failing manager and handler tests**

Assert Start stores 15, Resume changes 5 to 15 while preserving `success_in_cycle == 5`, handlers forward the parsed values, and omitted Resume cycle size keeps the stored value.

- [x] **Step 2: Run handler and manager tests and verify RED**

Run: `./venv/bin/python -m unittest tests.test_generation_controls tests.test_resume_interval -v`

Expected: signature, propagation, or stored-value assertions fail.

- [x] **Step 3: Implement parsing and manager storage**

Extend both manager methods and handlers. Normalize manager values with `max(1, int(cycle_size))`; use 5 only for a missing Start value and preserve the current value for a missing Resume value.

- [x] **Step 4: Run handler and manager tests and verify GREEN**

Run: `./venv/bin/python -m unittest tests.test_generation_controls tests.test_resume_interval -v`

Expected: all focused tests pass.

### Task 4: Dashboard control and progress presentation

**Files:**
- Modify: `tests/test_generation_controls.py`
- Modify: `server.py`

**Interfaces:**
- Produces: input `cyi${i}` and browser request bodies containing `cycle_size`.
- Consumes: status fields `cycle_size`, `success_in_cycle`, `completed`, and `target`.

- [x] **Step 1: Write failing dashboard source assertions**

Assert the card contains the cycle input, Start and Resume read it and submit `cycle_size`, polling updates it from account state while running, and target/cycle percentages are clamped at 100.

- [x] **Step 2: Run the dashboard tests and verify RED**

Run: `./venv/bin/python -m unittest tests.test_generation_controls.DashboardControlTests -v`

Expected: missing input and request-body assertions fail.

- [x] **Step 3: Implement the dashboard changes**

Add the compact `每轮` field beside interval, apply the same authenticated/running visibility rules as the other inputs, send it from Start and Resume, sync it while running, and clamp both progress calculations with `Math.min(100, ...)`.

- [x] **Step 4: Run the dashboard tests and verify GREEN**

Run: `./venv/bin/python -m unittest tests.test_generation_controls.DashboardControlTests -v`

Expected: all dashboard tests pass.

### Task 5: Verification and release

**Files:**
- Modify: `docs/superpowers/plans/2026-08-05-total-target-cycle-config.md`

**Interfaces:**
- Consumes: all completed implementation tasks.
- Produces: verified `main` commit and published GHCR `latest` image.

- [x] **Step 1: Run the full suite**

Run: `./venv/bin/python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [x] **Step 2: Check syntax and diff**

Run: `./venv/bin/python -m py_compile main.py server.py && git diff --check && git status --short`

Expected: exit 0, no whitespace errors, and only intended files plus untracked `.mindfs/`.

- [x] **Step 3: Build and test the Docker image**

Run: `docker build -t hidemyemail-generator:test .`

Run: `docker run --rm hidemyemail-generator:test python -m unittest discover -s tests -v`

Expected: image builds and the container test suite has zero failures.

- [x] **Step 4: Commit and push**

Commit the implementation, tests, spec, and plan with message `feat: make target total and configure cycle size`, push `main`, and verify the GHCR workflow completes successfully.
