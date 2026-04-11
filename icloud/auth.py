"""
Apple iCloud SRP Authentication with 2FA support and session persistence.

Flow:
  1. SRP authenticate(apple_id, password) → "2fa_required" | "ok" | error
  2. validate_2fa_code(code) → "ok" | error
  3. Session persisted to sessions/ dir (trust token ~90 days)
  4. On restart: load_session() → validate_token() → auto re-auth if needed
"""

import base64
import getpass
import hashlib
import http.cookiejar as cookielib
import json
import logging
import os
import platform
from pathlib import Path
from uuid import uuid1

import requests
import srp

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

SESSIONS_DIR = "sessions"

# Apple's widget/OAuth key (same for all iCloud web apps)
WIDGET_KEY = "d39ba9916b7251055b22c7f910e2ea796ee65e98b2ddecea8f5dde8d9d1a815d"

# Headers Apple sets in responses that we need to capture
HEADER_DATA = {
    "X-Apple-ID-Account-Country": "account_country",
    "X-Apple-ID-Session-Id": "session_id",
    "X-Apple-Session-Token": "session_token",
    "X-Apple-TwoSV-Trust-Token": "trust_token",
    "X-Apple-TwoSV-Trust-Eligible": "trust_eligible",
    "scnt": "scnt",
}

# Endpoints by domain
ENDPOINTS = {
    "cn": {
        "AUTH_ROOT": "https://idmsa.apple.com.cn",
        "AUTH": "https://idmsa.apple.com.cn/appleauth/auth",
        "HOME": "https://www.icloud.com.cn",
        "SETUP": "https://setup.icloud.com.cn/setup/ws/1",
    },
    "com": {
        "AUTH_ROOT": "https://idmsa.apple.com",
        "AUTH": "https://idmsa.apple.com/appleauth/auth",
        "HOME": "https://www.icloud.com",
        "SETUP": "https://setup.icloud.com/setup/ws/1",
    },
}


# ─── Password encryption ────────────────────────────────────

def _derive_key() -> bytes:
    """Derive a machine-specific Fernet key for password encryption."""
    info = f"hme-gen-{platform.node()}-{getpass.getuser()}-{platform.machine()}"
    raw = hashlib.pbkdf2_hmac("sha256", info.encode(), b"hme-salt-v1", 100_000)
    return base64.urlsafe_b64encode(raw)


def _encrypt(plaintext: str) -> str:
    return Fernet(_derive_key()).encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return Fernet(_derive_key()).decrypt(ciphertext.encode()).decode()


# ─── SRP Password helper ────────────────────────────────────

class _SrpPassword:
    """Adapter so the `srp` library can use Apple's password derivation."""

    def __init__(self, password: str):
        self.pwd = password
        self.protocol = ""
        self.salt = b""
        self.iterations = 0

    def set_encrypt_info(self, protocol: str, salt: bytes, iterations: int):
        self.protocol = protocol
        self.salt = salt
        self.iterations = iterations

    def encode(self) -> bytes:
        pw_hash = hashlib.sha256(self.pwd.encode())
        digest = (
            pw_hash.hexdigest().encode()
            if self.protocol == "s2k_fo"
            else pw_hash.digest()
        )
        return hashlib.pbkdf2_hmac("sha256", digest, self.salt, self.iterations, 32)


# ─── Main class ──────────────────────────────────────────────

class ICloudSession:
    """
    Manages Apple ID authentication (SRP + 2FA) with persistent sessions.

    Usage:
        s = ICloudSession("user@example.com", domain="cn")
        result = s.authenticate("password123")   # "2fa_required" or "ok"
        result = s.validate_2fa_code("123456")    # "ok"
        cookie_str = s.get_cookie_string()        # for curl_cffi
    """

    def __init__(self, apple_id: str, domain: str = "cn"):
        self.apple_id = apple_id
        self.domain = domain
        self.client_id = f"auth-{str(uuid1()).lower()}"
        self.session_data: dict = {}
        self.data: dict = {}
        self._password: str | None = None

        ep = ENDPOINTS.get(domain, ENDPOINTS["cn"])
        self.AUTH_ROOT = ep["AUTH_ROOT"]
        self.AUTH_ENDPOINT = ep["AUTH"]
        self.HOME_ENDPOINT = ep["HOME"]
        self.SETUP_ENDPOINT = ep["SETUP"]

        # requests session for auth (synchronous)
        self.session = requests.Session()
        self.session.headers.update({
            "Origin": self.HOME_ENDPOINT,
            "Referer": f"{self.HOME_ENDPOINT}/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        })

        # Persistent cookie jar + session file
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        safe = "".join(c for c in apple_id if c.isalnum() or c in "._-@")
        self._cookiejar_path = os.path.join(SESSIONS_DIR, f"{safe}.cookies")
        self._session_path = os.path.join(SESSIONS_DIR, f"{safe}.session")

        self.session.cookies = cookielib.LWPCookieJar(filename=self._cookiejar_path)

        self._load_session()

    # ── persistence ──────────────────────────────────────────

    def _load_session(self):
        """Restore session data + cookies from disk."""
        if os.path.exists(self._session_path):
            try:
                with open(self._session_path) as f:
                    self.session_data = json.load(f)
                if "client_id" in self.session_data:
                    self.client_id = self.session_data["client_id"]
                if "encrypted_password" in self.session_data:
                    try:
                        self._password = _decrypt(
                            self.session_data["encrypted_password"]
                        )
                    except Exception:
                        logger.warning("Failed to decrypt stored password")
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        if os.path.exists(self._cookiejar_path):
            try:
                self.session.cookies.load(
                    ignore_discard=True, ignore_expires=True
                )
            except Exception:
                pass

    def _save_session(self):
        """Write session data + cookies to disk."""
        self.session_data["client_id"] = self.client_id
        self.session_data["apple_id"] = self.apple_id
        self.session_data["domain"] = self.domain
        if self._password:
            self.session_data["encrypted_password"] = _encrypt(self._password)

        with open(self._session_path, "w") as f:
            json.dump(self.session_data, f, indent=2)

        try:
            self.session.cookies.save(ignore_discard=True, ignore_expires=True)
        except Exception:
            pass

    def _capture_headers(self, response: requests.Response):
        """Extract Apple auth headers from response and store them."""
        for header, key in HEADER_DATA.items():
            val = response.headers.get(header)
            if val:
                self.session_data[key] = val

    # ── status ───────────────────────────────────────────────

    @property
    def status(self) -> str:
        """Current auth status string for the dashboard."""
        if self.session_data.get("requires_2fa"):
            return "requires_2fa"
        if self.session_data.get("authenticated"):
            return "authenticated"
        return "unauthenticated"

    # ── auth headers ─────────────────────────────────────────

    def _get_auth_headers(self) -> dict:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Apple-OAuth-Client-Id": WIDGET_KEY,
            "X-Apple-OAuth-Client-Type": "firstPartyAuth",
            "X-Apple-OAuth-Redirect-URI": self.HOME_ENDPOINT,
            "X-Apple-OAuth-Require-Grant-Code": "true",
            "X-Apple-OAuth-Response-Mode": "web_message",
            "X-Apple-OAuth-Response-Type": "code",
            "X-Apple-OAuth-State": self.client_id,
            "X-Apple-Widget-Key": WIDGET_KEY,
        }
        if self.session_data.get("scnt"):
            headers["scnt"] = self.session_data["scnt"]
        if self.session_data.get("session_id"):
            headers["X-Apple-ID-Session-Id"] = self.session_data["session_id"]
        return headers

    # ── SRP authentication ───────────────────────────────────

    def authenticate(self, password: str) -> str:
        """
        Perform SRP login.
        Returns: "ok", "2fa_required", or an error message string.
        """
        self._password = password

        try:
            # Step 1: generate SRP public key A
            srp_pw = _SrpPassword(password)
            srp.rfc5054_enable()
            srp.no_username_in_x()
            usr = srp.User(
                self.apple_id, srp_pw,
                hash_alg=srp.SHA256, ng_type=srp.NG_2048,
            )
            uname, A = usr.start_authentication()

            init_data = {
                "a": base64.b64encode(A).decode(),
                "accountName": uname,
                "protocols": ["s2k", "s2k_fo"],
            }

            headers = self._get_auth_headers()
            headers["Origin"] = self.AUTH_ROOT
            headers["Referer"] = f"{self.AUTH_ROOT}/"

            # POST /signin/init
            resp = self.session.post(
                f"{self.AUTH_ENDPOINT}/signin/init",
                json=init_data,
                headers=headers,
            )
            self._capture_headers(resp)

            if resp.status_code == 401:
                return "Invalid Apple ID or password"
            if resp.status_code >= 500:
                return f"Apple server error ({resp.status_code})"

            body = resp.json()
            salt = base64.b64decode(body["salt"])
            b = base64.b64decode(body["b"])
            c = body["c"]
            iterations = body["iteration"]
            protocol = body["protocol"]

            # Step 2: compute M1/M2
            srp_pw.set_encrypt_info(protocol, salt, iterations)
            m1 = usr.process_challenge(salt, b)
            m2 = usr.H_AMK

            complete_data = {
                "accountName": uname,
                "c": c,
                "m1": base64.b64encode(m1).decode(),
                "m2": base64.b64encode(m2).decode(),
                "rememberMe": True,
                "trustTokens": [],
            }
            if self.session_data.get("trust_token"):
                complete_data["trustTokens"] = [
                    self.session_data["trust_token"]
                ]

            # POST /signin/complete
            resp = self.session.post(
                f"{self.AUTH_ENDPOINT}/signin/complete",
                params={"isRememberMeEnabled": "true"},
                json=complete_data,
                headers=headers,
            )
            self._capture_headers(resp)

            if resp.status_code == 409:
                # 2FA required
                self.session_data["requires_2fa"] = True
                self.session_data["authenticated"] = False
                self._save_session()
                return "2fa_required"

            if resp.status_code == 200:
                self.session_data["requires_2fa"] = False
                self._authenticate_with_token()
                self.session_data["authenticated"] = True
                self._save_session()
                return "ok"

            if resp.status_code == 412:
                # Repair flow (non-2FA account edge case)
                h2 = self._get_auth_headers()
                resp2 = self.session.post(
                    f"{self.AUTH_ENDPOINT}/repair/complete",
                    json={}, headers=h2,
                )
                self._capture_headers(resp2)
                self.session_data["requires_2fa"] = True
                self.session_data["authenticated"] = False
                self._save_session()
                return "2fa_required"

            return f"Login failed (HTTP {resp.status_code})"

        except Exception as e:
            logger.exception("SRP authentication failed")
            return f"Auth error: {e}"

    # ── 2FA verification ─────────────────────────────────────

    def validate_2fa_code(self, code: str) -> str:
        """
        Verify 6-digit 2FA code.
        Returns: "ok" or an error message string.
        """
        headers = self._get_auth_headers()
        headers["Accept"] = "application/json"

        try:
            resp = self.session.post(
                f"{self.AUTH_ENDPOINT}/verify/trusteddevice/securitycode",
                json={"securityCode": {"code": code}},
                headers=headers,
            )
            self._capture_headers(resp)

            if resp.status_code == 400:
                return "Invalid verification code"
            if resp.status_code >= 400:
                return f"Verification failed (HTTP {resp.status_code})"

            # Trust this session
            self._trust_session()

            # Complete auth with token
            self._authenticate_with_token()

            self.session_data["requires_2fa"] = False
            self.session_data["authenticated"] = True
            self._save_session()
            return "ok"

        except Exception as e:
            logger.exception("2FA verification failed")
            return f"2FA error: {e}"

    def _trust_session(self):
        """Request session trust (avoids 2FA next time, ~90 days)."""
        headers = self._get_auth_headers()
        try:
            resp = self.session.get(
                f"{self.AUTH_ENDPOINT}/2sv/trust", headers=headers
            )
            self._capture_headers(resp)
        except Exception:
            logger.warning("Failed to trust session")

    def _authenticate_with_token(self):
        """Exchange session token for full auth data + webservices."""
        data = {
            "accountCountryCode": self.session_data.get("account_country"),
            "dsWebAuthToken": self.session_data.get("session_token"),
            "extended_login": True,
            "trustToken": self.session_data.get("trust_token", ""),
        }
        resp = self.session.post(
            f"{self.SETUP_ENDPOINT}/accountLogin",
            json=data,
            headers={
                "Origin": self.HOME_ENDPOINT,
                "Referer": f"{self.HOME_ENDPOINT}/",
            },
        )
        self._capture_headers(resp)
        self.data = resp.json()

        # Handle domain redirect
        domain_to_use = self.data.get("domainToUse")
        if domain_to_use:
            logger.warning(f"Apple insists on domain: {domain_to_use}")

        self._save_session()

    # ── session validation & auto re-auth ────────────────────

    def validate_token(self) -> bool:
        """Check if the current session is still valid."""
        try:
            resp = self.session.post(
                f"{self.SETUP_ENDPOINT}/validate",
                data="null",
                headers={
                    "Origin": self.HOME_ENDPOINT,
                    "Referer": f"{self.HOME_ENDPOINT}/",
                },
            )
            if resp.status_code == 200:
                self.data = resp.json()
                return True
        except Exception:
            pass
        return False

    def ensure_authenticated(self) -> str:
        """
        Ensure session is valid — auto re-auth if needed.
        Returns: "ok", "2fa_required", or error string.
        """
        # 1. Already authenticated? Try validating token
        if self.session_data.get("authenticated"):
            if self.validate_token():
                return "ok"

            # 2. Try re-auth with stored session_token
            if self.session_data.get("session_token"):
                try:
                    self._authenticate_with_token()
                    if self.validate_token():
                        return "ok"
                except Exception:
                    pass

        # 3. Try full re-auth with stored password
        if self._password:
            return self.authenticate(self._password)

        return "unauthenticated"

    # ── cookie export ────────────────────────────────────────

    def get_cookie_string(self) -> str:
        """Export cookies as a header string for curl_cffi."""
        parts = []
        for cookie in self.session.cookies:
            parts.append(f"{cookie.name}={cookie.value}")
        return "; ".join(parts)

    def get_dsid(self) -> str:
        """Get DSID from auth data."""
        return str(self.data.get("dsInfo", {}).get("dsid", ""))

    # ── cleanup ──────────────────────────────────────────────

    def remove(self):
        """Delete all session files for this account."""
        for p in [self._session_path, self._cookiejar_path]:
            if os.path.exists(p):
                os.remove(p)


# ─── Discovery ───────────────────────────────────────────────

def load_saved_sessions() -> list[ICloudSession]:
    """Load all previously saved sessions from the sessions/ directory."""
    sessions = []
    if not os.path.exists(SESSIONS_DIR):
        return sessions

    for fname in sorted(os.listdir(SESSIONS_DIR)):
        if not fname.endswith(".session"):
            continue
        try:
            with open(os.path.join(SESSIONS_DIR, fname)) as f:
                data = json.load(f)
            apple_id = data.get("apple_id", "")
            domain = data.get("domain", "cn")
            if apple_id:
                s = ICloudSession(apple_id, domain=domain)
                sessions.append(s)
        except Exception:
            continue

    return sessions
