from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"
DEFAULT_SESSION_PATH = DEFAULT_DATA_DIR / "session.json"
DEFAULT_QR_PATH = DEFAULT_DATA_DIR / "wx_qrcode.png"


class SessionError(RuntimeError):
    """Raised when a saved WeChat MP session cannot be used."""


def cookie_string_from_cookies(cookies: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for cookie in cookies:
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", ""))
        if name:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": str(cookie.get("name", "")),
        "value": str(cookie.get("value", "")),
        "domain": str(cookie.get("domain") or "mp.weixin.qq.com"),
        "path": str(cookie.get("path") or "/"),
    }

    expires = cookie.get("expires", cookie.get("expiry"))
    try:
        if expires is not None and float(expires) > 0:
            item["expires"] = int(float(expires))
    except (TypeError, ValueError):
        pass

    same_site = cookie.get("sameSite")
    if same_site in {"Strict", "Lax", "None"}:
        item["sameSite"] = same_site
    secure = cookie.get("secure")
    if isinstance(secure, bool):
        item["secure"] = secure
    http_only = cookie.get("httpOnly")
    if isinstance(http_only, bool):
        item["httpOnly"] = http_only
    return item


def compute_expiry(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    now = int(time.time())
    preferred = {"slave_sid", "slave_user", "ticket", "uuid"}
    candidates: list[tuple[int, str]] = []
    for cookie in cookies:
        name = str(cookie.get("name", ""))
        expires = cookie.get("expires", cookie.get("expiry"))
        try:
            timestamp = int(float(expires))
        except (TypeError, ValueError):
            continue
        if timestamp > now:
            score = 0 if name in preferred else 1
            candidates.append((score * 10_000_000_000 + timestamp, name))

    if not candidates:
        return {"timestamp": 0, "expiry_time": "", "source": ""}

    encoded, name = min(candidates)
    timestamp = encoded % 10_000_000_000
    return {
        "timestamp": timestamp,
        "expiry_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
        "source": name,
    }


def build_session(
    *,
    token: str,
    cookies: list[dict[str, Any]],
    user_agent: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = [normalize_cookie(cookie) for cookie in cookies if cookie.get("name")]
    session = {
        "token": str(token or ""),
        "cookies": normalized,
        "cookie": cookie_string_from_cookies(normalized),
        "user_agent": user_agent,
        "saved_at": int(time.time()),
        "expiry": compute_expiry(normalized),
    }
    if extra:
        session["extra"] = extra
    validate_session(session)
    return session


def validate_session(session: dict[str, Any]) -> None:
    if not session.get("token"):
        raise SessionError("session has no token; run auth again")
    if not session.get("cookie") and not session.get("cookies"):
        raise SessionError("session has no cookies; run auth again")


def save_session(session: dict[str, Any], path: Path | str = DEFAULT_SESSION_PATH) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    validate_session(session)
    target.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_session(path: Path | str = DEFAULT_SESSION_PATH) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise SessionError(f"session file not found: {target}")
    session = json.loads(target.read_text(encoding="utf-8"))
    validate_session(session)
    return session


def load_werss_session(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        raise SessionError(f"WeRSS wx.lic not found: {source}")
    data = json.loads(source.read_text(encoding="utf-8") or "{}")
    token_data = data.get("token_data") or data
    token = str(token_data.get("token", ""))
    cookies = token_data.get("cookies") or []
    cookie_string = str(token_data.get("cookie", ""))

    if not cookies and cookie_string:
        cookies = []
        for part in cookie_string.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if name:
                cookies.append(
                    {
                        "name": name,
                        "value": value.strip(),
                        "domain": "mp.weixin.qq.com",
                        "path": "/",
                    }
                )

    session = build_session(
        token=token,
        cookies=cookies,
        extra={"imported_from": str(source), "source": "we-mp-rss"},
    )
    if cookie_string:
        session["cookie"] = cookie_string
    if token_data.get("expiry"):
        session["expiry"] = token_data["expiry"]
    return session


def redacted_session_summary(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_file_has_token": bool(session.get("token")),
        "cookie_count": len(session.get("cookies") or []),
        "saved_at": session.get("saved_at"),
        "expiry": session.get("expiry", {}),
    }

