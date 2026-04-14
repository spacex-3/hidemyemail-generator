# Randomized Hide My Email Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed reserve-time `label` and `note` with natural-looking randomized English metadata for each reserved address, and remove outdated `rtuna` branding from the README without changing core HME generation, iCloud authentication, or session persistence behavior.

**Architecture:** Add small metadata helper functions inside `icloud/hidemyemail.py` and call them only when `reserve_email()` builds its payload. Cover the helper output and reserve payload wiring with new `unittest` tests, then clean the stale branding text in `README.md`.

**Tech Stack:** Python 3, `unittest`, `unittest.mock`, existing `curl_cffi` async client, Markdown docs.

---

## File Map

- `icloud/hidemyemail.py` — add local word/template pools, metadata helper(s), and reserve-payload wiring; keep `generate_email()` and auth/session behavior unchanged.
- `tests/test_hidemyemail_metadata.py` — new regression tests for helper output and reserve payload behavior.
- `README.md` — remove stale `rtuna` attribution text.

### Task 1: Add failing tests for metadata generation helpers

**Files:**
- Create: `tests/test_hidemyemail_metadata.py`
- Modify: `icloud/hidemyemail.py`
- Test: `tests/test_hidemyemail_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from icloud.hidemyemail import _generate_random_metadata


class MetadataGenerationTests(unittest.TestCase):
    def test_generated_metadata_is_readable_and_brand_free(self):
        metadata = _generate_random_metadata()

        self.assertRegex(metadata["label"], r"^[a-z]+(?: [a-z]+){1,2}$")
        self.assertGreaterEqual(len(metadata["label"].split()), 2)
        self.assertTrue(metadata["note"])
        self.assertTrue(metadata["note"][0].isupper())
        self.assertTrue(metadata["note"].endswith("."))

        combined = f"{metadata['label']} {metadata['note']}".lower()
        self.assertNotIn("rtuna", combined)
        self.assertNotIn("spacex-3", combined)

    def test_generated_labels_are_not_constant_across_samples(self):
        labels = {_generate_random_metadata()["label"] for _ in range(25)}
        self.assertGreater(len(labels), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_hidemyemail_metadata.py' -v`
Expected: FAIL with an import error or missing-name failure for `_generate_random_metadata`.

- [ ] **Step 3: Write minimal implementation**

Add the smallest helper set in `icloud/hidemyemail.py`:

```python
_LABEL_ADJECTIVES = [
    "amber", "calm", "clear", "gentle", "quiet", "silver", "soft", "still",
]
_LABEL_NOUNS = [
    "brook", "garden", "harbor", "meadow", "morning", "orchard", "river", "trail",
]
_NOTE_TEMPLATES = [
    "Reserved for personal email routing.",
    "Created for inbox organization.",
    "Saved for private forwarding use.",
    "Set aside for personal account use.",
]


def _generate_random_label() -> str:
    word_count = random.choice((2, 3))
    words = [random.choice(_LABEL_ADJECTIVES), random.choice(_LABEL_NOUNS)]
    if word_count == 3:
        words.append(random.choice(_LABEL_NOUNS))
    return " ".join(words)


def _generate_random_metadata() -> dict:
    return {
        "label": _generate_random_label(),
        "note": random.choice(_NOTE_TEMPLATES),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_hidemyemail_metadata.py' -v`
Expected: PASS for `test_generated_metadata_is_readable_and_brand_free` and `test_generated_labels_are_not_constant_across_samples`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hidemyemail_metadata.py icloud/hidemyemail.py
git commit -m "test: add randomized metadata helper coverage"
```

### Task 2: Wire randomized metadata into `reserve_email()` with a failing payload test first

**Files:**
- Modify: `tests/test_hidemyemail_metadata.py`
- Modify: `icloud/hidemyemail.py`
- Test: `tests/test_hidemyemail_metadata.py`

- [ ] **Step 1: Write the failing test**

Append this async regression test to `tests/test_hidemyemail_metadata.py`:

```python
from unittest.mock import AsyncMock, patch

from icloud.hidemyemail import HideMyEmail


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def post(self, url, params=None, json=None):
        self.calls.append({"url": url, "params": params, "json": json})
        return _FakeResponse({"success": True})


class ReservePayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserve_email_uses_fresh_metadata_per_call(self):
        client = HideMyEmail(cookies="session=value")
        client.s = _FakeSession()

        with patch("icloud.hidemyemail._human_delay", new=AsyncMock()), patch(
            "icloud.hidemyemail._generate_random_metadata",
            side_effect=[
                {
                    "label": "quiet harbor",
                    "note": "Reserved for personal email routing.",
                },
                {
                    "label": "silver meadow",
                    "note": "Created for inbox organization.",
                },
            ],
        ):
            await client.reserve_email("first@icloud.com")
            await client.reserve_email("second@icloud.com")

        self.assertEqual(
            client.s.calls[0]["json"],
            {
                "hme": "first@icloud.com",
                "label": "quiet harbor",
                "note": "Reserved for personal email routing.",
            },
        )
        self.assertEqual(
            client.s.calls[1]["json"],
            {
                "hme": "second@icloud.com",
                "label": "silver meadow",
                "note": "Created for inbox organization.",
            },
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_hidemyemail_metadata.py' -v`
Expected: FAIL because `reserve_email()` still sends the old fixed `label` / `note` pair.

- [ ] **Step 3: Write minimal implementation**

Update only the reserve metadata path in `icloud/hidemyemail.py`:

```python
class HideMyEmail:
    def __init__(self, label: str = "", cookies: str = ""):
        """Initialize the client.

        The `label` argument is kept only for compatibility; reserve metadata is
        generated per request.
        """
        self.label = label.strip()
        self.cookies = cookies

    async def reserve_email(self, email: str) -> dict:
        try:
            await _human_delay()
            metadata = _generate_random_metadata()
            payload = {
                "hme": email,
                "label": metadata["label"],
                "note": metadata["note"],
            }
            resp = await self.s.post(
                f"{self.base_url_v1}/reserve",
                params=self.params,
                json=payload,
            )
            return resp.json()
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}
```

Do **not** change `generate_email()`, authentication code, or persistence code.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s tests -p 'test_hidemyemail_metadata.py' -v`
Expected: PASS for the new reserve payload test and the helper tests from Task 1.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hidemyemail_metadata.py icloud/hidemyemail.py
git commit -m "feat: randomize reserve metadata per email"
```

### Task 3: Remove stale README branding and verify the scoped change

**Files:**
- Modify: `README.md`
- Test: `tests/test_hidemyemail_metadata.py`

- [ ] **Step 1: Confirm the stale branding is present before editing**

Run: `rg -n "rtuna" README.md icloud/hidemyemail.py`
Expected: matches in the README attribution line and any remaining fixed metadata references in `icloud/hidemyemail.py`.

- [ ] **Step 2: Update the README copy**

Replace the trailing attribution text in `README.md` with neutral maintenance wording:

```markdown
## License

Licensed under the MIT License - see the [LICENSE file](./LICENSE) for more details.

Maintained in this repository by **[spacex-3](https://github.com/spacex-3)**.
```

- [ ] **Step 3: Verify the branding cleanup and test suite**

Run both commands:

```bash
rg -n "rtuna" README.md icloud/hidemyemail.py
python3 -m unittest discover -s tests -p 'test_hidemyemail_metadata.py' -v
```

Expected:
- `rg` returns no matches in `README.md` or `icloud/hidemyemail.py`
- All metadata tests PASS

- [ ] **Step 4: Run the broader verification command**

Run: `python3 -m unittest discover -s tests -p 'test*.py' -v`
Expected: PASS (currently this project should only pick up the new metadata tests).

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_hidemyemail_metadata.py icloud/hidemyemail.py
git commit -m "docs: remove stale branding from metadata and README"
```
