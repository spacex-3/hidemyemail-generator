import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mailbox_store import MailboxStore
from mail_receiver import MailboxReceiver, extract_openai_code, is_openai_message


class OpenAIReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = MailboxStore(Path(self.tempdir.name))
        self.store.upsert_alias("sold@icloud.com", "owner@example.com")
        self.profile = self.store.create_profile(
            label="Inbox",
            email="receiver@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            imap_username="receiver@example.com",
            imap_password="app-password",
        )
        self.store.set_account_profile("owner@example.com", self.profile["id"])
        self.receiver = MailboxReceiver(self.store, poll_seconds=60)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_accepts_openai_sender_and_extracts_contextual_code(self):
        self.assertTrue(is_openai_message("noreply@tm.openai.com"))
        self.assertTrue(is_openai_message("security@mail.openai.com"))
        self.assertTrue(
            is_openai_message("otp_at_tm1_openai_com_token@icloud.com")
        )
        self.assertFalse(is_openai_message("noreply@example.com"))
        self.assertEqual(
            extract_openai_code("Your OpenAI verification code is 123456."),
            "123456",
        )
        self.assertEqual(extract_openai_code("Invoice 123456"), "")
        self.assertEqual(
            extract_openai_code("123456 是你的 ChatGPT 临时验证码"), "123456"
        )

    def test_ingests_icloud_forwarded_openai_mail_with_chinese_code_text(self):
        raw = b"\r\n".join([
            b"From: otp_at_tm1_openai_com_token@icloud.com",
            b"To: Hide My Email <sold@icloud.com>",
            "Subject: 你的 ChatGPT 临时验证码".encode(),
            b"Date: Sat, 09 Aug 2026 10:00:00 +0000",
            b"Content-Type: text/plain; charset=utf-8",
            b"",
            "246810 是你的 ChatGPT 临时验证码".encode(),
        ])

        self.assertTrue(
            self.receiver.ingest_raw_message(
                profile_id=self.profile["id"], remote_id="forwarded-1", raw=raw
            )
        )
        self.assertEqual(self.store.latest_openai_code("sold@icloud.com")["code"], "246810")

    def test_ingests_only_strictly_routed_openai_messages(self):
        raw = b"\r\n".join([
            b"From: OpenAI <noreply@tm.openai.com>",
            b"To: receiver@example.com",
            b"X-Original-To: sold@icloud.com",
            b"Subject: Your OpenAI verification code",
            b"Message-ID: <message-1@example.com>",
            b"Date: Sat, 09 Aug 2026 10:00:00 +0000",
            b"Content-Type: text/plain; charset=utf-8",
            b"",
            b"Your OpenAI verification code is 123456.",
        ])

        self.assertTrue(
            self.receiver.ingest_raw_message(
                profile_id=self.profile["id"], remote_id="100", raw=raw
            )
        )
        latest = self.store.latest_openai_code("sold@icloud.com")
        self.assertEqual(latest["code"], "123456")
        self.assertEqual(latest["subject"], "Your OpenAI verification code")

    def test_does_not_ingest_openai_message_without_alias_routing_header(self):
        raw = b"\r\n".join([
            b"From: OpenAI <noreply@tm.openai.com>",
            b"To: receiver@example.com",
            b"Subject: Your OpenAI verification code",
            b"Message-ID: <message-2@example.com>",
            b"",
            b"Your OpenAI verification code is 654321.",
        ])

        self.assertFalse(
            self.receiver.ingest_raw_message(
                profile_id=self.profile["id"], remote_id="101", raw=raw
            )
        )
        self.assertIsNone(self.store.latest_openai_code("sold@icloud.com"))

    def test_profile_sync_fetches_new_uid_without_proxy_for_direct_profile(self):
        raw = b"\r\n".join([
            b"From: OpenAI <noreply@tm.openai.com>",
            b"X-Original-To: sold@icloud.com",
            b"Subject: Your OpenAI verification code",
            b"Date: Sat, 09 Aug 2026 10:00:00 +0000",
            b"",
            b"Your OpenAI verification code is 246810.",
        ])

        class FakeIMAP:
            proxy_urls = []

            def __init__(self, host, port, proxy_url):
                self.proxy_urls.append(proxy_url)

            def login(self, username, password):
                self.logged_in = (username, password)

            def select(self, folder, readonly):
                return "OK", [b""]

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"100"]
                if command == "fetch":
                    return "OK", [(b"100 (RFC822)", raw)]
                raise AssertionError(command)

            def logout(self):
                pass

        with patch("mail_receiver.ProxyIMAP4SSL", FakeIMAP):
            imported = self.receiver._sync_profile_blocking(self.profile["id"])

        self.assertEqual(imported, 1)
        self.assertEqual(FakeIMAP.proxy_urls, [""])
        self.assertEqual(self.store.latest_openai_code("sold@icloud.com")["code"], "246810")

    def test_recent_inspection_rescans_and_reports_routing_diagnostics(self):
        openai_raw = b"\r\n".join([
            b"From: OpenAI <noreply@tm.openai.com>",
            b"X-Original-To: sold@icloud.com",
            b"Subject: Your OpenAI verification code",
            b"Date: Sat, 09 Aug 2026 10:00:00 +0000",
            b"",
            b"Your OpenAI verification code is 246810.",
        ])
        unrelated_raw = b"\r\n".join([
            b"From: billing@example.com",
            b"To: receiver@example.com",
            b"Subject: Invoice",
            b"",
            b"Invoice 123456",
        ])

        class FakeIMAP:
            def __init__(self, *args):
                pass

            def login(self, username, password):
                pass

            def select(self, folder, readonly):
                return "OK", [b""]

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"100 101"]
                if command == "fetch":
                    raw = openai_raw if args[0] == "100" else unrelated_raw
                    return "OK", [(b"RFC822", raw)]
                raise AssertionError(command)

            def logout(self):
                pass

        with patch("mail_receiver.ProxyIMAP4SSL", FakeIMAP):
            result = asyncio.run(self.receiver.inspect_profile(self.profile["id"]))

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["messages"][0]["status"], "ignored_sender")
        self.assertEqual(result["messages"][1]["status"], "imported")
        self.assertEqual(result["messages"][1]["matched_aliases"], ["sold@icloud.com"])
        self.assertEqual(self.store.latest_openai_code("sold@icloud.com")["code"], "246810")

    def test_netease_profiles_send_imap_id_and_keep_select_error_details(self):
        netease = self.store.create_profile(
            preset="163",
            label="",
            email="receiver@163.com",
            imap_host="",
            imap_port=993,
            imap_username="",
            imap_password="app-password",
        )
        self.store.set_alias_profile("sold@icloud.com", netease["id"])

        class FakeIMAP:
            id_calls = []
            selected_folders = []

            def __init__(self, *args):
                pass

            def login(self, username, password):
                pass

            def _simple_command(self, command, payload):
                self.id_calls.append((command, payload))
                return "OK", [b"ID accepted"]

            def select(self, folder, readonly):
                self.selected_folders.append(folder)
                return "NO", [b"Unsafe Login"]

            def logout(self):
                pass

        with patch("mail_receiver.ProxyIMAP4SSL", FakeIMAP):
            with self.assertRaisesRegex(RuntimeError, "Unsafe Login"):
                self.receiver._sync_profile_blocking(netease["id"])

        self.assertEqual(FakeIMAP.id_calls[0][0], "ID")
        self.assertEqual(FakeIMAP.selected_folders, ['"INBOX"'])


if __name__ == "__main__":
    unittest.main()
