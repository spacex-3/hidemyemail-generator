import os
import unittest
from unittest.mock import patch

from storage_paths import get_data_dir, get_sessions_dir, get_emails_file


class TestStoragePaths(unittest.TestCase):
    def test_legacy_paths_without_data_dir(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DATA_DIR", None)
            self.assertEqual(get_data_dir(), "")
            self.assertEqual(get_sessions_dir(), "sessions")
            self.assertEqual(get_emails_file("user@icloud.com"), "emails-user@icloud.com.txt")

    def test_docker_paths_with_data_dir(self):
        with patch.dict(os.environ, {"DATA_DIR": "/app/data"}):
            self.assertEqual(get_data_dir(), "/app/data")
            self.assertEqual(get_sessions_dir(), "/app/data/sessions")
            self.assertEqual(get_emails_file("user@icloud.com"), "/app/data/emails-user@icloud.com.txt")

    def test_sessions_dir_creation_when_writable(self):
        """get_sessions_dir itself is a pure path resolver;
        ICloudSession.__init__ handles makedirs. Verify the path only."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            with patch.dict(os.environ, {"DATA_DIR": data_dir}):
                self.assertEqual(
                    get_sessions_dir(),
                    os.path.join(data_dir, "sessions"),
                )

    def test_emails_path_preserves_special_chars(self):
        with patch.dict(os.environ, {"DATA_DIR": "/app/data"}):
            self.assertEqual(
                get_emails_file("user+tag@icloud.com"),
                "/app/data/emails-user+tag@icloud.com.txt",
            )


if __name__ == "__main__":
    unittest.main()
