# Linux HME Authentication Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore HME generation for pure-Linux SRP and 2FA sessions by resolving the final iCloud region, obtaining the correct HME service context, matching the current request protocol, and stopping on authentication failures.

**Architecture:** `ICloudSession` owns final region and bootstrap resolution. `HideMyEmail` owns the deterministic current web request protocol. `GenerationManager` validates the session context before generation, while `RichHideMyEmail` classifies terminal authentication failures separately from rate limits.

**Tech Stack:** Python 3.12+, requests, curl_cffi, aiohttp dashboard, unittest/pytest-compatible tests, Docker.

## Global Constraints

- Preserve the pure-Linux SRP and 2FA workflow.
- Do not require imported browser cookies or a headless browser.
- Support global iCloud and iCloud China.
- Preserve existing saved session compatibility.
- Treat only explicit Apple limit responses as rate limits.

---

### Task 1: Region and service-context resolution

**Files:**
- Modify: `icloud/auth.py`
- Create: `tests/test_auth_context.py`

**Interfaces:**
- Produces: `ICloudSession._apply_domain_to_use(domain_to_use: str) -> bool`
- Produces: `ICloudSession.get_maildomain_service_url() -> str`
- Produces: `ICloudSession.validate_hme_context() -> tuple[bool, str]`

- [x] Write tests for `iCloud.com`/`iCloud.com.cn` endpoint switching, service URL preference, partition fallback, and missing Cookie/DSID messages.
- [x] Run `python3 -m unittest tests.test_auth_context -v` and verify the new tests fail for the missing behavior.
- [x] Implement endpoint switching, repeat setup login once after a domain change, service discovery, and context validation.
- [x] Run `python3 -m unittest tests.test_auth_context -v` and verify all tests pass.

### Task 2: Current deterministic HME request protocol

**Files:**
- Modify: `icloud/hidemyemail.py`
- Create: `tests/test_hme_protocol.py`

**Interfaces:**
- Produces: `HMEAuthenticationError`
- Produces: `is_authentication_failed(response: dict) -> bool`
- Produces: `HideMyEmail` requests with current build/header values.

- [x] Write tests for build `2626Build17`, matching Chrome 150 headers, regional headers, and 401/403 authentication classification.
- [x] Run `python3 -m unittest tests.test_hme_protocol -v` and verify failures show the stale request contract.
- [x] Implement the deterministic current protocol and structured response metadata.
- [x] Run `python3 -m unittest tests.test_hme_protocol -v` and verify all tests pass.

### Task 3: Fail-fast generation behavior

**Files:**
- Modify: `main.py`
- Create: `tests/test_generation_failures.py`
- Modify: `icloud/__init__.py`

**Interfaces:**
- Consumes: `is_authentication_failed(response: dict) -> bool`
- Produces: generation tasks that stop with `status=error` on authentication failure.

- [x] Write asynchronous tests showing 401/403 and missing authorization Cookie stop the generation loop without cooldown or unbounded retries.
- [x] Run `python3 -m unittest tests.test_generation_failures -v` and verify the current loop fails the assertions.
- [x] Validate HME context before opening the client and propagate terminal authentication failures through `RichHideMyEmail.generate`.
- [x] Run `python3 -m unittest tests.test_generation_failures -v` and verify all tests pass.

### Task 4: Verification and deployment readiness

**Files:**
- Modify: `README.md` only if operation or diagnostics changed materially.

- [x] Run `python3 -m unittest discover -s tests -v` and verify zero failures.
- [x] Run `python3 -m compileall -q .` and verify exit code 0.
- [x] Run `docker build -t hidemyemail-generator:auth-context-fix .` and verify exit code 0.
- [x] Inspect `git diff --check` and `git status --short` for accidental or unrelated changes.
- [x] Report that external Apple acceptance requires a fresh login/2FA run using the rebuilt image, including the exact diagnostic to provide if Apple still rejects it.
