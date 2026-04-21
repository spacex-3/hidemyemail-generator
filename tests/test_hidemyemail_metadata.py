import unittest
from unittest.mock import AsyncMock, patch

from icloud.hidemyemail import HideMyEmail, _generate_random_metadata


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


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def post(self, url, params=None, json=None, data=None):
        self.calls.append({"url": url, "params": params, "json": json, "data": data})
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
            client.s.calls[0]["data"],
            "{\"hme\":\"first@icloud.com\",\"label\":\"quiet harbor\",\"note\":\"Reserved for personal email routing.\"}",
        )
        self.assertEqual(
            client.s.calls[1]["data"],
            "{\"hme\":\"second@icloud.com\",\"label\":\"silver meadow\",\"note\":\"Created for inbox organization.\"}",
        )


if __name__ == "__main__":
    unittest.main()
