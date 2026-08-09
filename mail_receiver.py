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


def _imap_response_text(value) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030", "gbk", "latin1"):
            try:
                return value.decode(encoding)
            except UnicodeDecodeError:
                pass
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return " ".join(_imap_response_text(item) for item in value)
    return str(value or "")


def _quote_imap_mailbox(name: str) -> str:
    """Quote simple mailbox names consistently with provider IMAP parsers."""
    value = str(name or "INBOX")
    if value.startswith('"') and value.endswith('"'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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

    async def sync_profile(self, profile_id: str, *, recent: bool = False) -> int:
        lock = self._profile_locks.setdefault(profile_id, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(
                self._sync_profile_blocking, profile_id, recent=recent
            )

    @staticmethod
    def _raw_message(payload) -> bytes:
        return next(
            (item[1] for item in payload if isinstance(item, tuple) and len(item) > 1),
            b"",
        )

    def _connect_profile(self, profile: dict):
        client = ProxyIMAP4SSL(
            profile["imap_host"],
            int(profile["imap_port"]),
            profile["proxy_url"] if profile["network_mode"] != "direct" else "",
        )
        client.login(profile["imap_username"], profile["imap_password"])
        id_probe = self._send_provider_id(client, profile)
        status, data = client.select(
            _quote_imap_mailbox(profile["folder"]), readonly=True
        )
        if status != "OK":
            try:
                client.logout()
            except Exception:
                pass
            detail = _imap_response_text(data)[:500]
            id_detail = _imap_response_text(id_probe[1])[:300] if id_probe else ""
            raise RuntimeError(
                f"Cannot select IMAP folder {profile['folder']}: {status} {detail}"
                + (f"; IMAP ID response: {id_detail}" if id_detail else "")
            )
        return client

    @staticmethod
    def _send_provider_id(client, profile: dict):
        """NetEase IMAP often rejects SELECT until a client ID is presented."""
        host = str(profile.get("imap_host") or "").lower()
        if host not in {"imap.163.com", "imap.126.com"}:
            return None
        try:
            imaplib.Commands["ID"] = ("AUTH",)
            payload = '("name" "HME Mailbox" "version" "1.0" "vendor" "HME")'
            return client._simple_command("ID", payload)
        except Exception as exc:
            return "ERR", [str(exc)]

    @staticmethod
    def _all_uids(client) -> list[int]:
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("IMAP UID search failed")
        return [int(item) for item in (data[0].split() if data and data[0] else [])]

    def _sync_profile_blocking(self, profile_id: str, *, recent: bool = False) -> int:
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
            client = self._connect_profile(profile)
            uids = self._all_uids(client)
            candidates = [uid for uid in uids if uid > newest_uid]
            if recent or newest_uid == 0:
                candidates = uids[-20:]
            for uid in candidates:
                status, payload = client.uid("fetch", str(uid), "(RFC822)")
                if status != "OK":
                    continue
                raw = self._raw_message(payload)
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

    async def inspect_profile(self, profile_id: str) -> dict:
        """Re-scan recent mail and return admin-only routing diagnostics."""
        lock = self._profile_locks.setdefault(profile_id, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(self._inspect_profile_blocking, profile_id)

    def _inspect_profile_blocking(self, profile_id: str) -> dict:
        profile = self.store.profile_connection(profile_id)
        if profile is None:
            raise ValueError("Unknown profile")

        client = None
        imported = 0
        diagnostics = []
        try:
            client = self._connect_profile(profile)
            uids = self._all_uids(client)[-20:]
            for uid in reversed(uids):
                status, payload = client.uid("fetch", str(uid), "(RFC822)")
                if status != "OK":
                    continue
                raw = self._raw_message(payload)
                if not raw:
                    continue
                diagnostic = self.message_diagnostic(profile_id, str(uid), raw)
                if diagnostic["eligible"]:
                    if self.ingest_raw_message(profile_id, str(uid), raw):
                        imported += 1
                        diagnostic["status"] = "imported"
                    else:
                        diagnostic["status"] = "already_cached"
                diagnostics.append(diagnostic)
            if uids:
                self.store.update_profile_sync(profile_id, last_uid=max(uids))
            else:
                self.store.update_profile_sync(profile_id)
            return {"imported": imported, "messages": diagnostics}
        except Exception as exc:
            self.store.update_profile_sync(profile_id, error=str(exc))
            raise
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass

    def message_diagnostic(self, profile_id: str, remote_id: str, raw: bytes) -> dict:
        """Describe why a message will or will not enter the OpenAI cache."""
        message = email.message_from_bytes(raw)
        sender = parseaddr(message.get("From", ""))[1].lower()
        subject = _decode_header(message.get("Subject", ""))
        routing = {
            header: _decode_header(message.get(header, ""))
            for header in RECIPIENT_HEADERS
            if message.get(header, "")
        }
        recipient_text = " ".join(routing.values()).lower()
        matches = [
            item["email"]
            for item in self.store.aliases_for_profile(profile_id)
            if item["email"] in recipient_text
        ]
        openai = is_openai_message(sender)
        code = extract_openai_code(f"{subject}\n{_message_text(message)}") if openai else ""
        if not openai:
            status = "ignored_sender"
        elif not code:
            status = "no_verification_code"
        elif len(matches) == 0:
            status = "no_matching_hme"
        elif len(matches) > 1:
            status = "ambiguous_hme"
        else:
            status = "eligible"
        return {
            "uid": remote_id,
            "sender": sender,
            "subject": subject,
            "received_at": _decode_header(message.get("Date", "")),
            "routing": routing,
            "is_openai": openai,
            "code": code,
            "matched_aliases": matches,
            "eligible": status == "eligible",
            "status": status,
        }

    def ingest_raw_message(self, profile_id: str, remote_id: str, raw: bytes) -> bool:
        message = email.message_from_bytes(raw)
        diagnostic = self.message_diagnostic(profile_id, remote_id, raw)
        if not diagnostic["eligible"]:
            return False

        try:
            received_at = parsedate_to_datetime(message.get("Date", ""))
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=dt.timezone.utc)
        except Exception:
            received_at = dt.datetime.now(dt.timezone.utc)
        return self.store.record_openai_message(
            alias_email=diagnostic["matched_aliases"][0],
            profile_id=profile_id,
            remote_id=remote_id,
            sender=diagnostic["sender"],
            subject=diagnostic["subject"],
            code=diagnostic["code"],
            received_at=received_at.astimezone(dt.timezone.utc).isoformat(),
        )
