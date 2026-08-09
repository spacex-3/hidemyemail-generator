"""Background IMAP receiver for cached OpenAI verification codes."""

from __future__ import annotations

import asyncio
import datetime as dt
import email
import html
import imaplib
import re
import ssl
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import unquote, urlparse

import socks

from mailbox_store import MailboxStore


OPENAI_SENDER_DOMAINS = {"openai.com", "tm.openai.com"}
RECIPIENT_HEADERS = (
    "To",
    "Delivered-To",
    "X-Original-To",
    "X-Forwarded-To",
    "X-GM-Original-To",
    "X-Apple-Original-To",
    "Original-To",
    "Envelope-To",
    "Cc",
    "Resent-To",
)


def _decode_header(value: str) -> str:
    parts = []
    for fragment, encoding in decode_header(value or ""):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


def _visible_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _message_text(message: email.message.Message) -> str:
    plain_parts = []
    html_parts = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue
        if "attachment" in str(part.get("Content-Disposition") or "").lower():
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True) or b""
        decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(decoded)
        else:
            html_parts.append(_visible_text(decoded))
    return "\n".join(plain_parts or html_parts)


def is_openai_message(sender: str) -> bool:
    address = parseaddr(sender or "")[1].lower()
    return any(address == domain or address.endswith(f".{domain}") for domain in OPENAI_SENDER_DOMAINS)


def extract_openai_code(text: str) -> str:
    patterns = (
        r"(?:openai|chatgpt)[^\d]{0,80}(?:verification|login)?\s*code[^\d]{0,24}(\d{6})",
        r"(?:verification|login)\s+code[^\d]{0,24}(\d{6})",
        r"code\s+(?:is|:|：)\s*(\d{6})",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


class ProxyIMAP4SSL(imaplib.IMAP4_SSL):
    """IMAP4_SSL with a per-profile SOCKS5 or HTTP CONNECT route."""

    def __init__(self, host: str, port: int, proxy_url: str = "", timeout: int = 30):
        self._proxy_url = proxy_url
        context = ssl.create_default_context()
        super().__init__(host=host, port=port, ssl_context=context, timeout=timeout)

    def _create_socket(self, timeout):
        if not self._proxy_url:
            return super()._create_socket(timeout)

        parsed = urlparse(self._proxy_url)
        scheme = parsed.scheme.lower()
        if scheme not in {"socks5", "socks5h", "http", "http_connect"}:
            raise ValueError("IMAP proxy must use socks5, socks5h, http, or http_connect")
        proxy_type = socks.SOCKS5 if scheme.startswith("socks5") else socks.HTTP
        proxy_host = parsed.hostname
        if not proxy_host or not parsed.port:
            raise ValueError("IMAP proxy URL must include host and port")
        sock = socks.socksocket()
        sock.set_proxy(
            proxy_type,
            proxy_host,
            parsed.port,
            rdns=scheme == "socks5h",
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
        )
        sock.settimeout(timeout)
        sock.connect((self.host, self.port))
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


class MailboxReceiver:
    """Poll mapped IMAP profiles without touching HME generation state."""

    def __init__(self, store: MailboxStore, poll_seconds: int = 60):
        self.store = store
        self.poll_seconds = max(15, int(poll_seconds))
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._profile_locks: dict[str, asyncio.Lock] = {}

    async def start(self):
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="mailbox-imap-poller")

    async def stop(self):
        self._stopping.set()
        if self._task:
            await self._task

    async def _run(self):
        while not self._stopping.is_set():
            self.store.import_alias_history()
            self.store.purge_messages()
            for profile in self.store.list_profiles():
                if profile["active"]:
                    try:
                        await self.sync_profile(profile["id"])
                    except Exception:
                        pass
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def sync_profile(self, profile_id: str) -> int:
        lock = self._profile_locks.setdefault(profile_id, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(self._sync_profile_blocking, profile_id)

    def _sync_profile_blocking(self, profile_id: str) -> int:
        profile = self.store.profile_connection(profile_id)
        if profile is None:
            raise ValueError("Unknown profile")
        aliases = self.store.aliases_for_profile(profile_id)
        if not aliases:
            self.store.update_profile_sync(profile_id)
            return 0

        client = None
        newest_uid = int(profile["last_uid"] or 0)
        imported = 0
        try:
            client = ProxyIMAP4SSL(
                profile["imap_host"],
                int(profile["imap_port"]),
                profile["proxy_url"] if profile["network_mode"] != "direct" else "",
            )
            client.login(profile["imap_username"], profile["imap_password"])
            status, _ = client.select(profile["folder"], readonly=True)
            if status != "OK":
                raise RuntimeError(f"Cannot select IMAP folder {profile['folder']}")
            status, data = client.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError("IMAP UID search failed")
            uids = [int(item) for item in (data[0].split() if data and data[0] else [])]
            candidates = [uid for uid in uids if uid > newest_uid]
            if newest_uid == 0:
                candidates = uids[-20:]
            for uid in candidates:
                status, payload = client.uid("fetch", str(uid), "(RFC822)")
                if status != "OK":
                    continue
                raw = next(
                    (item[1] for item in payload if isinstance(item, tuple) and len(item) > 1),
                    b"",
                )
                if raw and self.ingest_raw_message(profile_id, str(uid), raw):
                    imported += 1
                newest_uid = max(newest_uid, uid)
            self.store.update_profile_sync(profile_id, last_uid=newest_uid)
            return imported
        except Exception as exc:
            self.store.update_profile_sync(profile_id, error=str(exc))
            raise
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass

    def ingest_raw_message(self, profile_id: str, remote_id: str, raw: bytes) -> bool:
        message = email.message_from_bytes(raw)
        sender = parseaddr(message.get("From", ""))[1].lower()
        if not is_openai_message(sender):
            return False
        subject = _decode_header(message.get("Subject", ""))
        code = extract_openai_code(f"{subject}\n{_message_text(message)}")
        if not code:
            return False

        recipient_text = " ".join(
            _decode_header(message.get(header, "")) for header in RECIPIENT_HEADERS
        ).lower()
        aliases = self.store.aliases_for_profile(profile_id)
        matches = [item for item in aliases if item["email"] in recipient_text]
        if len(matches) != 1:
            return False

        try:
            received_at = parsedate_to_datetime(message.get("Date", ""))
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=dt.timezone.utc)
        except Exception:
            received_at = dt.datetime.now(dt.timezone.utc)
        return self.store.record_openai_message(
            alias_email=matches[0]["email"],
            profile_id=profile_id,
            remote_id=remote_id,
            sender=sender,
            subject=subject,
            code=code,
            received_at=received_at.astimezone(dt.timezone.utc).isoformat(),
        )
