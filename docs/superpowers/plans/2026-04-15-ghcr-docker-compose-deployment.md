# GHCR Docker Compose Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a Docker image to GHCR, add a compose file for one-command VPS deployment, and introduce a `DATA_DIR`-aware storage path helper so email history can be migrated without format changes.

**Architecture:** Add `storage_paths.py` helper, update two consumers (`icloud/auth.py`, `main.py`) to use it, then add Dockerfile / .dockerignore / compose / GitHub Actions workflow and README docs.

**Tech Stack:** Python 3.13, Docker, GitHub Actions, GHCR, aiohttp.

---

## File Map

- `storage_paths.py` — new module; `DATA_DIR`-aware path resolution
- `tests/test_storage_paths.py` — new; unit tests for path helper
- `icloud/auth.py` — modify `SESSIONS_DIR` to use helper
- `main.py` — modify email file paths to use helper
- `Dockerfile` — new; Python 3.13-slim image
- `.dockerignore` — new; exclude local artefacts
- `docker-compose.yml` — new; reference VPS compose file
- `.github/workflows/docker.yml` — new; build + push to GHCR
- `README.md` — update; add Docker deployment section

---

### Task 1: Add storage path helper with tests

**Files:**
- Create: `storage_paths.py`
- Create: `tests/test_storage_paths.py`
- Test: `tests/test_storage_paths.py`

- [ ] **Step 1: Write failing tests**

```python
import os
import unittest
from unittest.mock import patch

from storage_paths import get_data_dir, get_sessions_dir, get_emails_file


class TestStoragePaths(unittest.TestCase):
    def test_legacy_paths_without_data_dir(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove DATA_DIR if it exists
            os.environ.pop("DATA_DIR", None)
            self.assertEqual(get_data_dir(), "")
            self.assertEqual(get_sessions_dir(), "sessions")
            self.assertEqual(get_emails_file("user@icloud.com"), "emails-user@icloud.com.txt")

    def test_docker_paths_with_data_dir(self):
        with patch.dict(os.environ, {"DATA_DIR": "/app/data"}):
            self.assertEqual(get_data_dir(), "/app/data")
            self.assertEqual(get_sessions_dir(), "/app/data/sessions")
            self.assertEqual(get_emails_file("user@icloud.com"), "/app/data/emails-user@icloud.com.txt")

    def test_sessions_dir_is_created(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            with patch.dict(os.environ, {"DATA_DIR": data_dir}):
                sessions = get_sessions_dir()
                self.assertTrue(os.path.exists(sessions))
                self.assertEqual(sessions, os.path.join(data_dir, "sessions"))

    def test_emails_path_sanitizes_account(self):
        with patch.dict(os.environ, {"DATA_DIR": "/app/data"}):
            self.assertEqual(
                get_emails_file("user+tag@icloud.com"),
                "/app/data/emails-user+tag@icloud.com.txt",
            )
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python3 -m pytest tests/test_storage_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'storage_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
import os


def get_data_dir() -> str:
    return os.environ.get("DATA_DIR", "")


def get_sessions_dir() -> str:
    base = get_data_dir()
    path = os.path.join(base, "sessions") if base else "sessions"
    os.makedirs(path, exist_ok=True)
    return path


def get_emails_file(account: str) -> str:
    base = get_data_dir()
    filename = f"emails-{account}.txt"
    return os.path.join(base, filename) if base else filename
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `python3 -m pytest tests/test_storage_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage_paths.py tests/test_storage_paths.py
git commit -m "feat: add DATA_DIR-aware storage path helper with tests"
```

---

### Task 2: Integrate storage path helper into auth and main

**Files:**
- Modify: `icloud/auth.py`
- Modify: `main.py`
- Test: `tests/test_storage_paths.py` (no regressions)

- [ ] **Step 1: Update `icloud/auth.py`**

Replace the module-level constant:

```python
SESSIONS_DIR = "sessions"
```

With a function call:

```python
from storage_paths import get_sessions_dir as _get_sessions_dir

# SESSIONS_DIR is now resolved dynamically
# All usages of SESSIONS_DIR need to call _get_sessions_dir()
```

Specifically, update every reference to `SESSIONS_DIR` in `icloud/auth.py` to use `_get_sessions_dir()` instead of the old constant.

- [ ] **Step 2: Update `main.py`**

Replace hardcoded email file patterns:

- `Progress.load_historical_emails`: `f"emails-{self.account}.txt"` → `get_emails_file(self.account)`
- `RichHideMyEmail.__init__`: `f"emails-{account}.txt"` → `get_emails_file(account)`

Add import:

```python
from storage_paths import get_emails_file
```

- [ ] **Step 3: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (storage path tests still green, no regressions)

- [ ] **Step 4: Commit**

```bash
git add icloud/auth.py main.py
git commit -m "feat: integrate storage path helper into auth and main"
```

---

### Task 3: Add Dockerfile, .dockerignore, and docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `.dockerignore`**

```
.git
.worktrees
venv
__pycache__
**/__pycache__
*.pyc
sessions
data
emails-*.txt
*.spec
build
dist
.DS_Store
docs
tests
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "cli.py", "serve", "--port", "8080"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  hme:
    image: ghcr.io/spacex-3/hidemyemail-generator:latest
    container_name: hme
    ports:
      - "8080:8080"
    environment:
      - DATA_DIR=/app/data
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

- [ ] **Step 4: Verify Docker build locally**

Run: `docker build -t hme-test .`
Expected: successful build

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat: add Dockerfile, compose, and dockerignore"
```

---

### Task 4: Add GitHub Actions workflow for GHCR

**Files:**
- Create: `.github/workflows/docker.yml`

- [ ] **Step 1: Create workflow**

```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [main]
  workflow_dispatch:

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=raw,value=latest
            type=sha

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docker.yml
git commit -m "ci: add GHCR build and push workflow"
```

---

### Task 5: Update README with Docker deployment docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Docker section after CLI Commands**

Insert a new section covering:
- Prerequisites (VPS with Docker)
- One-command deployment: create compose file → up -d
- Migration steps for existing `emails-*.txt`
- Note about re-adding accounts through dashboard

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Docker deployment and migration instructions"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no rtuna branding remains**

Run: `rg -n "rtuna" README.md icloud/hidemyemail.py`
Expected: no matches

- [ ] **Step 3: Verify Docker build succeeds**

Run: `docker build -t hme-test .`
Expected: successful build
