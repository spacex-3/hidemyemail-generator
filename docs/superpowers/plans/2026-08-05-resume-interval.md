# Resume Interval Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Resume apply the interval currently shown in the account card without resetting progress.

**Architecture:** The dashboard sends the edited interval in the Resume JSON body. The aiohttp handler normalizes it and `GenerationManager.resume_account` updates `Progress.interval` before starting the remaining work.

**Tech Stack:** Python, asyncio, aiohttp, embedded browser JavaScript, unittest.

## Global Constraints

- Preserve target, completed count, email history, and cycle progress.
- Enforce the existing minimum interval of 30 minutes.
- Keep Resume compatible when no interval is sent.

---

### Task 1: Resume interval data flow

**Files:**
- Modify: `server.py`
- Modify: `main.py`
- Modify: `tests/test_generation_failures.py`
- Create: `tests/test_resume_interval.py`

**Interfaces:**
- Produces: `GenerationManager.resume_account(apple_id: str, interval: int | None = None)`
- Consumes: Resume JSON body `{ "interval": 66 }`

- [x] Add a failing manager test that resumes progress `65/600`, changes interval `42` to `66`, and preserves both progress values.
- [x] Add a failing server test that checks `rsA` reads `itv` and sends JSON to `/resume`.
- [x] Run `python -m unittest tests.test_resume_interval -v` and confirm failures are caused by the absent Resume interval flow.
- [x] Update the browser request, aiohttp handler, and manager signature with minimal validation.
- [x] Run `python -m unittest tests.test_resume_interval -v` and the complete test suite.
- [x] Build the Docker image and push the verified commit to `main` so GHCR publishes `latest`.
