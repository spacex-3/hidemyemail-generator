"""Persistent mailbox mappings and cached OpenAI verification codes.

This module is deliberately independent from the HME generator. It discovers
aliases from the generator's append-only history files but never calls Apple
or changes generation state.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


class MailboxStore:
    """SQLite store for forwarding profiles, aliases, tokens, and messages."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._fernet = Fernet(self._load_or_create_key())
        self._connection = sqlite3.connect(
            self.data_dir / "mailboxes.sqlite3", check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema()

    def close(self):
        with self._lock:
            self._connection.close()

    def _load_or_create_key(self) -> bytes:
        path = self.data_dir / "mailbox-secret.key"
        if path.exists():
            return path.read_bytes().strip()

        key = Fernet.generate_key()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(key + b"\n")
        return key

    def _create_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                email TEXT NOT NULL,
                imap_host TEXT NOT NULL,
                imap_port INTEGER NOT NULL,
                imap_username TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                folder TEXT NOT NULL DEFAULT 'INBOX',
                network_mode TEXT NOT NULL DEFAULT 'direct',
                proxy_encrypted TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                last_uid INTEGER NOT NULL DEFAULT 0,
                last_sync_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS account_profiles (
                source_account TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(profile_id) REFERENCES profiles(id)
            );

            CREATE TABLE IF NOT EXISTS aliases (
                email TEXT PRIMARY KEY,
                source_account TEXT NOT NULL,
                profile_id TEXT,
                api_active INTEGER NOT NULL DEFAULT 0,
                public_id TEXT UNIQUE,
                token_hash TEXT NOT NULL DEFAULT '',
                buyer_note TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(profile_id) REFERENCES profiles(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias_email TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                code TEXT NOT NULL,
                received_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(profile_id, remote_id),
                FOREIGN KEY(alias_email) REFERENCES aliases(email)
            );

            CREATE INDEX IF NOT EXISTS idx_aliases_source_account
                ON aliases(source_account);
            CREATE INDEX IF NOT EXISTS idx_messages_alias_received
                ON messages(alias_email, received_at DESC);

            CREATE TABLE IF NOT EXISTS settings (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat()

    @staticmethod
    def _normalize_email(value: str) -> str:
        email = str(value or "").strip().lower()
        if "@" not in email:
            raise ValueError("A valid email address is required")
        return email

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(str(value or "").encode()).decode()

    def _decrypt(self, value: str) -> str:
        return self._fernet.decrypt(str(value or "").encode()).decode()

    def import_alias_history(self) -> int:
        """Import append-only HME history files without changing their contents."""
        imported = 0
        for path in sorted(self.data_dir.glob("emails-*.txt")):
            source_account = path.name[len("emails-"):-len(".txt")]
            if not source_account:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                raw_email = line.split(",", 1)[0].strip()
                if not raw_email:
                    continue
                try:
                    if self.upsert_alias(raw_email, source_account):
                        imported += 1
                except ValueError:
                    continue
        return imported

    def upsert_alias(self, email: str, source_account: str) -> bool:
        email = self._normalize_email(email)
        source_account = self._normalize_email(source_account)
        now = self._now()
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO aliases(email, source_account, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (email, source_account, now, now),
            )
            self._connection.commit()
        return cursor.rowcount == 1

    def list_aliases(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT a.*, COALESCE(a.profile_id, ap.profile_id) AS effective_profile_id
                FROM aliases a
                LEFT JOIN account_profiles ap ON ap.source_account = a.source_account
                ORDER BY a.email
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_account_mappings(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT a.source_account, ap.profile_id, p.label AS profile_label,
                       p.email AS profile_email, COUNT(*) AS alias_count
                FROM aliases a
                LEFT JOIN account_profiles ap ON ap.source_account = a.source_account
                LEFT JOIN profiles p ON p.id = ap.profile_id
                GROUP BY a.source_account, ap.profile_id, p.label, p.email
                ORDER BY a.source_account
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_profile(
        self,
        *,
        label: str,
        email: str,
        imap_host: str,
        imap_port: int,
        imap_username: str,
        imap_password: str,
        folder: str = "INBOX",
        network_mode: str = "direct",
        proxy_url: str = "",
    ) -> dict[str, Any]:
        if network_mode not in {"direct", "socks5", "http_connect"}:
            raise ValueError("Unsupported network mode")
        if not str(imap_password):
            raise ValueError("IMAP password is required")
        if network_mode != "direct" and not str(proxy_url).strip():
            raise ValueError("A proxy URL is required for this network mode")
        profile_id = f"rp_{secrets.token_urlsafe(9)}"
        now = self._now()
        record = (
            profile_id,
            str(label or "").strip() or self._normalize_email(email),
            self._normalize_email(email),
            str(imap_host or "").strip(),
            int(imap_port),
            str(imap_username or "").strip(),
            self._encrypt(imap_password),
            str(folder or "INBOX").strip() or "INBOX",
            network_mode,
            self._encrypt(proxy_url) if proxy_url else "",
            now,
            now,
        )
        if not record[3] or not record[5]:
            raise ValueError("IMAP host and username are required")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO profiles(
                    id, label, email, imap_host, imap_port, imap_username,
                    password_encrypted, folder, network_mode, proxy_encrypted,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                record,
            )
            self._connection.commit()
        return self.get_profile(profile_id)

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, label, email, imap_host, imap_port, imap_username,
                       folder, network_mode, active, last_uid, last_sync_at,
                       last_error, created_at, updated_at
                FROM profiles WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()
        return self._dict(row)

    def profile_connection(self, profile_id: str) -> dict[str, Any] | None:
        """Return decrypted credentials only to the in-process IMAP worker."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            return None
        profile = dict(row)
        profile["imap_password"] = self._decrypt(profile.pop("password_encrypted"))
        encrypted_proxy = profile.pop("proxy_encrypted")
        profile["proxy_url"] = self._decrypt(encrypted_proxy) if encrypted_proxy else ""
        return profile

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, label, email, imap_host, imap_port, imap_username,
                       folder, network_mode, active, last_uid, last_sync_at,
                       last_error, created_at, updated_at
                FROM profiles ORDER BY label, email
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_profile_sync(
        self,
        profile_id: str,
        *,
        last_uid: int | None = None,
        error: str = "",
    ):
        fields = ["last_sync_at = ?", "last_error = ?", "updated_at = ?"]
        params: list[Any] = [self._now(), str(error or "")[:500], self._now()]
        if last_uid is not None:
            fields.insert(0, "last_uid = ?")
            params.insert(0, int(last_uid))
        params.append(profile_id)
        with self._lock:
            self._connection.execute(
                f"UPDATE profiles SET {', '.join(fields)} WHERE id = ?", params
            )
            self._connection.commit()

    def set_account_profile(self, source_account: str, profile_id: str):
        source_account = self._normalize_email(source_account)
        if self.get_profile(profile_id) is None:
            raise ValueError("Unknown profile")
        now = self._now()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO account_profiles(source_account, profile_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_account) DO UPDATE SET
                    profile_id = excluded.profile_id, updated_at = excluded.updated_at
                """,
                (source_account, profile_id, now),
            )
            self._connection.commit()

    def set_alias_profile(self, email: str, profile_id: str | None):
        email = self._normalize_email(email)
        if profile_id and self.get_profile(profile_id) is None:
            raise ValueError("Unknown profile")
        with self._lock:
            self._connection.execute(
                "UPDATE aliases SET profile_id = ?, updated_at = ? WHERE email = ?",
                (profile_id or None, self._now(), email),
            )
            self._connection.commit()

    def effective_profile_for_alias(self, email: str) -> dict[str, Any] | None:
        email = self._normalize_email(email)
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(a.profile_id, ap.profile_id) AS profile_id
                FROM aliases a
                LEFT JOIN account_profiles ap ON ap.source_account = a.source_account
                WHERE a.email = ?
                """,
                (email,),
            ).fetchone()
        if row is None or not row["profile_id"]:
            return None
        return self.get_profile(row["profile_id"])

    def aliases_for_profile(self, profile_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT a.*
                FROM aliases a
                LEFT JOIN account_profiles ap ON ap.source_account = a.source_account
                WHERE COALESCE(a.profile_id, ap.profile_id) = ?
                ORDER BY a.email
                """,
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def issue_api_token(self, email: str) -> str:
        email = self._normalize_email(email)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        public_id = f"mb_{secrets.token_urlsafe(9)}"
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE aliases
                SET public_id = ?, token_hash = ?, api_active = 1, updated_at = ?
                WHERE email = ?
                """,
                (public_id, token_hash, self._now(), email),
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown alias")
            self._connection.commit()
        return token

    def get_alias_by_token(self, token: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(str(token or "").encode()).hexdigest()
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM aliases
                WHERE token_hash = ? AND api_active = 1
                  AND (expires_at = '' OR expires_at > ?)
                """,
                (token_hash, self._now()),
            ).fetchone()
        return self._dict(row)

    def get_alias_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM aliases WHERE public_id = ?", (public_id,)
            ).fetchone()
        return self._dict(row)

    def update_alias_sales(
        self,
        email: str,
        *,
        api_active: bool | None = None,
        buyer_note: str | None = None,
        expires_at: str | None = None,
    ):
        email = self._normalize_email(email)
        fields = ["updated_at = ?"]
        params: list[Any] = [self._now()]
        if api_active is not None:
            fields.append("api_active = ?")
            params.append(int(bool(api_active)))
        if buyer_note is not None:
            fields.append("buyer_note = ?")
            params.append(str(buyer_note)[:500])
        if expires_at is not None:
            fields.append("expires_at = ?")
            params.append(str(expires_at))
        params.append(email)
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE aliases SET {', '.join(fields)} WHERE email = ?", params
            )
            if cursor.rowcount != 1:
                raise ValueError("Unknown alias")
            self._connection.commit()

    def get_retention_days(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM settings WHERE name = 'retention_days'"
            ).fetchone()
        try:
            return max(1, min(90, int(row["value"]))) if row else 7
        except (TypeError, ValueError):
            return 7

    def set_retention_days(self, days: int):
        days = max(1, min(90, int(days)))
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO settings(name, value, updated_at) VALUES ('retention_days', ?, ?)
                ON CONFLICT(name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (str(days), self._now()),
            )
            self._connection.commit()

    def purge_messages(self, now: str = "") -> int:
        try:
            current = dt.datetime.fromisoformat((now or self._now()).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Invalid purge timestamp") from exc
        cutoff = (current - dt.timedelta(days=self.get_retention_days())).isoformat()
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM messages WHERE received_at < ?", (cutoff,)
            )
            self._connection.commit()
        return cursor.rowcount

    def record_openai_message(
        self,
        *,
        alias_email: str,
        profile_id: str,
        remote_id: str,
        sender: str,
        subject: str,
        code: str,
        received_at: str,
    ) -> bool:
        alias_email = self._normalize_email(alias_email)
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO messages(
                    alias_email, profile_id, remote_id, sender, subject, code,
                    received_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alias_email,
                    profile_id,
                    str(remote_id),
                    str(sender),
                    str(subject),
                    str(code),
                    str(received_at),
                    self._now(),
                ),
            )
            self._connection.commit()
        return cursor.rowcount == 1

    def latest_openai_code(
        self, alias_email: str, after: str = ""
    ) -> dict[str, Any] | None:
        alias_email = self._normalize_email(alias_email)
        query = "SELECT * FROM messages WHERE alias_email = ?"
        params: list[str] = [alias_email]
        if after:
            query += " AND received_at > ?"
            params.append(str(after))
        query += " ORDER BY received_at DESC, id DESC LIMIT 1"
        with self._lock:
            row = self._connection.execute(query, params).fetchone()
        return self._dict(row)
