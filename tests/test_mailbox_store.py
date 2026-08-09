import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mailbox_store import MailboxStore


class MailboxStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.store = MailboxStore(self.data_dir)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_imports_existing_hme_history_idempotently(self):
        (self.data_dir / "emails-owner@example.com.txt").write_text(
            "first@icloud.com,2026-08-09 10:00:00\n"
            "second@icloud.com,2026-08-09 10:01:00\n",
            encoding="utf-8",
        )

        self.assertEqual(self.store.import_alias_history(), 2)
        self.assertEqual(self.store.import_alias_history(), 0)

        aliases = self.store.list_aliases()
        self.assertEqual([item["email"] for item in aliases], [
            "first@icloud.com",
            "second@icloud.com",
        ])
        self.assertEqual(
            {item["source_account"] for item in aliases}, {"owner@example.com"}
        )

    def test_alias_uses_account_default_until_explicit_override(self):
        self.store.upsert_alias("alias@icloud.com", "owner@example.com")
        first_profile = self.store.create_profile(
            label="Primary inbox",
            email="receiver@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            imap_username="receiver@example.com",
            imap_password="app-password-one",
        )
        second_profile = self.store.create_profile(
            label="Gmail inbox",
            email="receiver@gmail.com",
            imap_host="imap.gmail.com",
            imap_port=993,
            imap_username="receiver@gmail.com",
            imap_password="app-password-two",
            network_mode="socks5",
            proxy_url="socks5h://proxy.internal:1080",
        )

        self.store.set_account_profile("owner@example.com", first_profile["id"])
        self.assertEqual(
            self.store.effective_profile_for_alias("alias@icloud.com")["id"],
            first_profile["id"],
        )

        self.store.set_alias_profile("alias@icloud.com", second_profile["id"])
        self.assertEqual(
            self.store.effective_profile_for_alias("alias@icloud.com")["id"],
            second_profile["id"],
        )

    def test_profile_secrets_are_encrypted_at_rest(self):
        self.store.create_profile(
            label="Private inbox",
            email="receiver@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            imap_username="receiver@example.com",
            imap_password="do-not-store-this-plaintext",
        )

        database_text = (self.data_dir / "mailboxes.sqlite3").read_bytes()
        self.assertNotIn(b"do-not-store-this-plaintext", database_text)

    def test_proxy_profile_requires_an_explicit_proxy_url(self):
        with self.assertRaisesRegex(ValueError, "proxy URL"):
            self.store.create_profile(
                label="Gmail inbox",
                email="receiver@gmail.com",
                imap_host="imap.gmail.com",
                imap_port=993,
                imap_username="receiver@gmail.com",
                imap_password="app-password",
                network_mode="socks5",
            )

    def test_customer_token_is_hashed_and_reads_latest_openai_code(self):
        self.store.upsert_alias("alias@icloud.com", "owner@example.com")
        token = self.store.issue_api_token("alias@icloud.com")
        alias = self.store.get_alias_by_token(token)
        self.assertEqual(alias["email"], "alias@icloud.com")

        connection = sqlite3.connect(self.data_dir / "mailboxes.sqlite3")
        try:
            row = connection.execute(
                "SELECT token_hash FROM aliases WHERE email = ?", ("alias@icloud.com",)
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0], hashlib.sha256(token.encode()).hexdigest())

        self.store.record_openai_message(
            alias_email="alias@icloud.com",
            profile_id="profile-1",
            remote_id="100",
            sender="noreply@tm.openai.com",
            subject="Your OpenAI verification code",
            code="111111",
            received_at="2026-08-09T10:00:00+00:00",
        )
        self.store.record_openai_message(
            alias_email="alias@icloud.com",
            profile_id="profile-1",
            remote_id="101",
            sender="noreply@tm.openai.com",
            subject="Your OpenAI verification code",
            code="222222",
            received_at="2026-08-09T10:01:00+00:00",
        )

        latest = self.store.latest_openai_code(
            "alias@icloud.com", after="2026-08-09T10:00:30+00:00"
        )
        self.assertEqual(latest["code"], "222222")

    def test_sales_state_and_message_retention_are_independent_of_alias_history(self):
        self.store.upsert_alias("sold@icloud.com", "owner@example.com")
        self.store.update_alias_sales(
            "sold@icloud.com",
            api_active=False,
            buyer_note="Order #1001",
            expires_at="2026-09-01T00:00:00+00:00",
        )
        self.store.record_openai_message(
            alias_email="sold@icloud.com",
            profile_id="profile-1",
            remote_id="old",
            sender="noreply@tm.openai.com",
            subject="Your OpenAI verification code",
            code="111111",
            received_at="2026-08-01T00:00:00+00:00",
        )
        self.store.record_openai_message(
            alias_email="sold@icloud.com",
            profile_id="profile-1",
            remote_id="new",
            sender="noreply@tm.openai.com",
            subject="Your OpenAI verification code",
            code="222222",
            received_at="2026-08-09T00:00:00+00:00",
        )

        self.store.set_retention_days(3)
        self.assertEqual(self.store.purge_messages(now="2026-08-10T00:00:00+00:00"), 1)

        alias = self.store.list_aliases()[0]
        self.assertFalse(alias["api_active"])
        self.assertEqual(alias["buyer_note"], "Order #1001")
        self.assertEqual(alias["expires_at"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(self.store.get_retention_days(), 3)
        self.assertEqual(self.store.latest_openai_code("sold@icloud.com")["code"], "222222")

    def test_common_provider_presets_only_need_account_and_app_password(self):
        for preset, mailbox, host in (
            ("gmail", "receiver@gmail.com", "imap.gmail.com"),
            ("126", "receiver@126.com", "imap.126.com"),
            ("163", "receiver@163.com", "imap.163.com"),
        ):
            with self.subTest(preset=preset):
                profile = self.store.create_profile(
                    preset=preset,
                    label="",
                    email=mailbox,
                    imap_host="ignored.example.com",
                    imap_port=1,
                    imap_username="",
                    imap_password="provider-app-password",
                )

                connection = self.store.profile_connection(profile["id"])
                self.assertEqual(connection["imap_host"], host)
                self.assertEqual(connection["imap_port"], 993)
                self.assertEqual(connection["imap_username"], mailbox)
                self.assertEqual(connection["folder"], "INBOX")

    def test_paged_export_filter_and_bulk_token_issue_prevent_duplicate_export(self):
        for number in range(101):
            self.store.upsert_alias(
                f"alias{number:03}@icloud.com", "owner@example.com"
            )

        aliases, total = self.store.list_aliases_page(
            page=1, per_page=100, exported="unexported"
        )
        self.assertEqual((len(aliases), total), (100, 101))

        issued = self.store.issue_export_tokens([item["email"] for item in aliases[:2]])
        self.assertEqual(len(issued), 2)
        self.assertTrue(all(item["token"] for item in issued))
        self.assertTrue(all(item["public_id"] for item in issued))

        remaining, total = self.store.list_aliases_page(
            page=1, per_page=100, exported="unexported"
        )
        self.assertEqual((len(remaining), total), (99, 99))
        with self.assertRaisesRegex(ValueError, "already exported"):
            self.store.issue_export_tokens([issued[0]["email"]])


if __name__ == "__main__":
    unittest.main()
