"""Standalone mailbox sidecar for HME forwarding and OpenAI code retrieval."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from mail_receiver import MailboxReceiver
from mailbox_store import IMAP_PRESETS, MailboxStore
from mailbox_web import (
    MAILBOX_DASHBOARD_HTML,
    MAILBOX_LOGIN_HTML,
    customer_mailbox_page,
)


SESSION_COOKIE = "hme_mail_admin"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60


def _json(payload: dict, status: int = 200) -> web.Response:
    response = web.json_response(payload, status=status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _public_alias(alias: dict) -> dict:
    return {
        "email": alias["email"],
        "source_account": alias["source_account"],
        "profile_id": alias.get("profile_id"),
        "effective_profile_id": alias.get("effective_profile_id"),
        "api_active": bool(alias["api_active"]),
        "public_id": alias.get("public_id") or "",
        "exported_at": alias.get("exported_at") or "",
        "buyer_note": alias.get("buyer_note") or "",
        "expires_at": alias.get("expires_at") or "",
        "created_at": alias["created_at"],
        "updated_at": alias["updated_at"],
    }


class AdminSession:
    def __init__(self, password: str):
        self.password = password.encode()
        self.signing_key = hashlib.sha256(b"hme-mail-session-v1:" + self.password).digest()

    def create(self) -> str:
        issued_at = str(int(time.time()))
        signature = hmac.new(self.signing_key, issued_at.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{issued_at}.{signature}".encode()).decode()

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            issued_at, signature = base64.urlsafe_b64decode(token.encode()).decode().split(".", 1)
            expected = hmac.new(
                self.signing_key, issued_at.encode(), hashlib.sha256
            ).hexdigest()
            return (
                hmac.compare_digest(signature, expected)
                and 0 <= time.time() - int(issued_at) <= SESSION_MAX_AGE_SECONDS
            )
        except Exception:
            return False


def _admin_required(request: web.Request) -> bool:
    return request.app["admin_session"].valid(request.cookies.get(SESSION_COOKIE))


async def _admin_login(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    password = str(payload.get("password") or "").encode()
    admin_session: AdminSession = request.app["admin_session"]
    if not hmac.compare_digest(password, admin_session.password):
        return _json({"success": False, "error": "Invalid password"}, 401)
    response = _json({"success": True})
    response.set_cookie(
        SESSION_COOKIE,
        admin_session.create(),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="Strict",
        secure=bool(request.app["cookie_secure"]),
    )
    return response


async def _admin_logout(_: web.Request) -> web.Response:
    response = _json({"success": True})
    response.del_cookie(SESSION_COOKIE)
    return response


async def _admin_status(request: web.Request) -> web.Response:
    store: MailboxStore = request.app["store"]
    store.import_alias_history()
    try:
        page = max(1, int(request.query.get("page", "1")))
        aliases, total = store.list_aliases_page(
            page=page,
            per_page=100,
            source_account=request.query.get("source_account", ""),
            exported=request.query.get("exported", "all"),
        )
    except ValueError as exc:
        return _json({"success": False, "error": str(exc)}, 400)
    return _json({
        "success": True,
        "aliases": [_public_alias(alias) for alias in aliases],
        "accounts": store.list_account_mappings(),
        "profiles": store.list_profiles(),
        "imap_presets": IMAP_PRESETS,
        "summary": store.alias_summary(),
        "pagination": {
            "page": page,
            "per_page": 100,
            "total": total,
            "pages": max(1, (total + 99) // 100),
            "source_account": request.query.get("source_account", ""),
            "exported": request.query.get("exported", "all"),
        },
        "retention_days": store.get_retention_days(),
        "public_base_url": request.app["public_base_url"],
    })


async def _admin_create_profile(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        profile = request.app["store"].create_profile(
            label=str(payload.get("label") or ""),
            email=str(payload.get("email") or ""),
            imap_host=str(payload.get("imap_host") or ""),
            imap_port=int(payload.get("imap_port") or 993),
            imap_username=str(payload.get("imap_username") or ""),
            imap_password=str(payload.get("imap_password") or ""),
            folder=str(payload.get("folder") or "INBOX"),
            network_mode=str(payload.get("network_mode") or "direct"),
            proxy_url=str(payload.get("proxy_url") or ""),
            preset=str(payload.get("preset") or "custom"),
        )
        return _json({"success": True, "profile": profile}, 201)
    except (TypeError, ValueError) as exc:
        return _json({"success": False, "error": str(exc)}, 400)


async def _admin_set_account_profile(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        request.app["store"].set_account_profile(
            request.match_info["account"], str(payload.get("profile_id") or "")
        )
        return _json({"success": True})
    except (TypeError, ValueError) as exc:
        return _json({"success": False, "error": str(exc)}, 400)


async def _admin_set_alias_profile(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        request.app["store"].set_alias_profile(
            request.match_info["email"], payload.get("profile_id") or None
        )
        return _json({"success": True})
    except (TypeError, ValueError) as exc:
        return _json({"success": False, "error": str(exc)}, 400)


async def _admin_issue_token(request: web.Request) -> web.Response:
    try:
        email = request.match_info["email"]
        token = request.app["store"].issue_api_token(email, mark_exported=True)
        alias = request.app["store"].get_alias_by_token(token)
        base_url = request.app["public_base_url"].rstrip("/")
        endpoint = f"{base_url}/api/v1/openai/mailboxes/{quote(alias['public_id'])}/latest"
        page_url = f"{base_url}/openai/{quote(alias['public_id'])}?key={quote(token)}"
        return _json({
            "success": True,
            "token": token,
            "api_url": endpoint,
            "page_url": page_url,
            "authorization": f"Bearer {token}",
            "public_id": alias["public_id"],
            "exported_at": alias["exported_at"],
        })
    except ValueError as exc:
        return _json({"success": False, "error": str(exc)}, 404)


async def _admin_bulk_issue_export(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        emails = payload.get("emails")
        if not isinstance(emails, list):
            raise ValueError("emails must be a list")
        issued = request.app["store"].issue_export_tokens(emails)
        base_url = request.app["public_base_url"].rstrip("/")
        items = []
        lines = []
        for item in issued:
            page_url = (
                f"{base_url}/openai/{quote(item['public_id'])}?key={quote(item['token'])}"
            )
            lines.append(f"{item['email']}----{page_url}")
            items.append({
                "email": item["email"],
                "public_id": item["public_id"],
                "exported_at": item["exported_at"],
                "page_url": page_url,
            })
        return _json({"success": True, "items": items, "export_text": "\n".join(lines)})
    except (TypeError, ValueError) as exc:
        return _json({"success": False, "error": str(exc)}, 400)


async def _admin_update_sales(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        request.app["store"].update_alias_sales(
            request.match_info["email"],
            api_active=payload.get("api_active"),
            buyer_note=payload.get("buyer_note"),
            expires_at=payload.get("expires_at"),
        )
        return _json({"success": True})
    except (TypeError, ValueError) as exc:
        return _json({"success": False, "error": str(exc)}, 400)


async def _admin_update_retention(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
        request.app["store"].set_retention_days(int(payload.get("retention_days")))
        return _json({
            "success": True,
            "retention_days": request.app["store"].get_retention_days(),
        })
    except (TypeError, ValueError) as exc:
        return _json({"success": False, "error": str(exc)}, 400)


async def _admin_sync_profile(request: web.Request) -> web.Response:
    try:
        count = await request.app["receiver"].sync_profile(request.match_info["profile_id"])
        return _json({"success": True, "imported": count})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 502)


async def _public_openai_code(request: web.Request) -> web.Response:
    public_id = request.match_info["public_id"]
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip() or request.query.get("key", "")
    store: MailboxStore = request.app["store"]
    alias = store.get_alias_by_token(token)
    if alias is None or alias.get("public_id") != public_id:
        return _json({"success": False, "code": "not_found"}, 404)

    after = request.query.get("after", "")
    message = store.latest_openai_code(alias["email"], after=after)
    if message is None and request.query.get("sync", "1") != "0":
        try:
            profile = store.effective_profile_for_alias(alias["email"])
            if profile is not None:
                await request.app["receiver"].sync_profile(profile["id"])
                message = store.latest_openai_code(alias["email"], after=after)
        except Exception:
            message = store.latest_openai_code(alias["email"], after=after)
    if message is None:
        return _json({
            "success": False,
            "code": "no_code",
            "message": "No new OpenAI verification code",
            "retryable": True,
        })
    return _json({
        "success": True,
        "subject": message["subject"],
        "received_at": message["received_at"],
        "code": message["code"],
    })


async def _public_mailbox_page(request: web.Request) -> web.Response:
    public_id = request.match_info["public_id"]
    token = request.query.get("key", "")
    alias = request.app["store"].get_alias_by_token(token)
    if alias is None or alias.get("public_id") != public_id:
        return web.Response(status=404, text="Not found")
    api_url = (
        f"/api/v1/openai/mailboxes/{quote(public_id)}/latest?key={quote(token)}&sync=0"
    )
    response = web.Response(
        text=customer_mailbox_page(json.dumps(api_url)), content_type="text/html"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def create_mail_app(
    store: MailboxStore,
    *,
    admin_password: str,
    public_base_url: str,
    poll_seconds: int = 60,
    start_receiver: bool = True,
    cookie_secure: bool = False,
) -> web.Application:
    if not admin_password:
        raise ValueError("MAIL_ADMIN_PASSWORD must be set")
    app = web.Application()
    receiver = MailboxReceiver(store, poll_seconds=poll_seconds)
    app["store"] = store
    app["receiver"] = receiver
    app["admin_session"] = AdminSession(admin_password)
    app["public_base_url"] = public_base_url.rstrip("/")
    app["cookie_secure"] = cookie_secure

    @web.middleware
    async def admin_middleware(request: web.Request, handler):
        public_paths = {
            "/health",
            "/login",
            "/api/admin/login",
        }
        if (
            request.path in public_paths
            or request.path.startswith("/api/v1/openai/")
            or request.path.startswith("/openai/")
            or _admin_required(request)
        ):
            return await handler(request)
        if request.path.startswith("/api/"):
            return _json({"success": False, "error": "Admin login required"}, 401)
        return web.Response(status=302, headers={"Location": "/login"})

    app.middlewares.append(admin_middleware)

    async def startup(_: web.Application):
        store.import_alias_history()
        store.purge_messages()
        if start_receiver:
            await receiver.start()

    async def cleanup(_: web.Application):
        if start_receiver:
            await receiver.stop()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    async def health(_: web.Request) -> web.Response:
        return _json({"success": True})

    async def dashboard(_: web.Request) -> web.Response:
        return web.Response(text=MAILBOX_DASHBOARD_HTML, content_type="text/html")

    async def login_page(_: web.Request) -> web.Response:
        return web.Response(text=MAILBOX_LOGIN_HTML, content_type="text/html")

    app.router.add_get("/health", health)
    app.router.add_get("/", dashboard)
    app.router.add_get("/login", login_page)
    app.router.add_post("/api/admin/login", _admin_login)
    app.router.add_post("/api/admin/logout", _admin_logout)
    app.router.add_get("/api/admin/status", _admin_status)
    app.router.add_post("/api/admin/profiles", _admin_create_profile)
    app.router.add_post("/api/admin/accounts/{account}/profile", _admin_set_account_profile)
    app.router.add_post("/api/admin/aliases/{email}/profile", _admin_set_alias_profile)
    app.router.add_post("/api/admin/aliases/{email}/token", _admin_issue_token)
    app.router.add_post("/api/admin/aliases/export", _admin_bulk_issue_export)
    app.router.add_post("/api/admin/aliases/{email}/sales", _admin_update_sales)
    app.router.add_post("/api/admin/profiles/{profile_id}/sync", _admin_sync_profile)
    app.router.add_post("/api/admin/settings/retention", _admin_update_retention)
    app.router.add_get("/api/v1/openai/mailboxes/{public_id}/latest", _public_openai_code)
    app.router.add_get("/openai/{public_id}", _public_mailbox_page)
    return app


def main():
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    store = MailboxStore(data_dir)
    app = create_mail_app(
        store,
        admin_password=os.environ.get("MAIL_ADMIN_PASSWORD", ""),
        public_base_url=os.environ.get("MAIL_PUBLIC_BASE_URL", "http://127.0.0.1:8787"),
        poll_seconds=int(os.environ.get("MAIL_POLL_SECONDS", "60")),
        cookie_secure=os.environ.get("MAIL_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
    )
    web.run_app(app, host=os.environ.get("MAIL_HOST", "0.0.0.0"), port=int(os.environ.get("MAIL_PORT", "8787")))


if __name__ == "__main__":
    main()
