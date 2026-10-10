"""#1771 — the EU Data Act portal's CDN answered 406 to the one User-Agent this
connector hard-coded (macOS Chrome/148.0.0.0), and the login surfaced it as
"check email and password".

The connector now picks one UA per session from a broad, calendar-tracked pool
of desktop and phone browsers, sends it on every request, and picks another
when the portal's priming GET answers 406.

HTTP is mocked like test_v2155_portal_consent_accept.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from custom_components.vag_connect.cariad.auth import _eu_data_act as m

_BLOCKED_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

_SIGNIN_HTML = (
    '<form action="/signin-service/v1/CLIENT/login/identifier">'
    '<input type="hidden" name="hmac" value="email_hmac">'
    '<input type="hidden" name="_csrf" value="csrf1">'
    '<input type="hidden" name="relayState" value="rs1">'
    '</form>'
)
_PASSWORD_HTML = (
    '<script>window._IDK = {templateModel: '
    '{"hmac":"fresh_pw_hmac","relayState":"rs1",'
    '"postAction":"/signin-service/v1/CLIENT/login/authenticate"}, '
    'csrf_token: "csrf2"};</script>'
)
_PORTAL_OK_LANDING = "https://eu-data-act.drivesomethinggreater.com/dashboard"


class _FakeResp:
    def __init__(self, url: str, *, status: int = 200, text: str = "") -> None:
        self.url = url
        self.status = status
        self._text = text

    async def __aenter__(self) -> "_FakeResp":
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False

    async def text(self, errors: str | None = None) -> str:
        return self._text

    async def json(self, content_type: str | None = None) -> Any:
        return {"vehicles": []}


class _RecordingSession:
    """A successful login flow that records the UA of every request.

    The priming GET answers 406 for any UA in ``refuse``.
    """

    def __init__(self, *, refuse: set[str] | None = None) -> None:
        self.refuse = refuse or set()
        self.uas: list[tuple[str, str]] = []

    def _ua(self, method: str, url: str, kw: dict[str, Any]) -> str:
        ua = kw["headers"]["User-Agent"]
        self.uas.append((f"{method} {url}", ua))
        return ua

    def get(self, url: str, **kw: Any) -> _FakeResp:
        ua = self._ua("GET", url, kw)
        if url.endswith("/") and "drivesomethinggreater" in url:
            status = 406 if ua in self.refuse else 200
            return _FakeResp(url, status=status, text="<html>portal</html>")
        if "authorize" in url:
            return _FakeResp(
                "https://identity.vwgroup.io/signin-service/v1/CLIENT/login/"
                "identifier",
                text=_SIGNIN_HTML,
            )
        if "/proxy_api/" in url:
            return _FakeResp(url)
        raise AssertionError(f"unmatched GET {url}")

    def post(self, url: str, **kw: Any) -> _FakeResp:
        self._ua("POST", url, kw)
        if url.endswith("/login/identifier"):
            return _FakeResp(
                "https://identity.vwgroup.io/signin-service/v1/CLIENT/login/"
                "authenticate?relayState=rs1",
                text=_PASSWORD_HTML,
            )
        if "/login/authenticate" in url:
            return _FakeResp(_PORTAL_OK_LANDING, text="<html>logged in</html>")
        raise AssertionError(f"unmatched POST {url}")


def test_pool_is_broad_and_tracks_the_calendar() -> None:
    pool = m._user_agent_pool(date(2026, 10, 9))
    assert len(pool) == len(set(pool)) >= 100
    joined = "\n".join(pool)
    for family in (
        "Windows NT", "Macintosh", "X11; Linux", "Android", "iPhone", "iPad",
        "Edg/", "EdgA/", "OPR/", "Firefox/", "FxiOS/", "CriOS/", "Version/",
    ):
        assert family in joined, family
    # 2026-10-09 → Chrome 153 (138 + 16 four-week majors - 1 lag).
    assert "Chrome/153.0.0.0" in joined
    assert "Chrome/154.0.0.0" not in joined
    assert _BLOCKED_UA not in pool
    # A year later the versions have moved on by themselves.
    later = "\n".join(m._user_agent_pool(date(2027, 10, 9)))
    assert "Chrome/153.0.0.0" not in later
    assert "Chrome/166.0.0.0" in later


def test_pick_avoids_excluded_user_agents() -> None:
    pool = m._user_agent_pool()
    assert m._pick_user_agent(exclude=pool[1:]) == pool[0]
    # Everything excluded: still returns a pool UA rather than failing.
    assert m._pick_user_agent(exclude=pool) in pool


@pytest.mark.asyncio
async def test_one_user_agent_for_the_whole_session() -> None:
    session = _RecordingSession()
    conn = m.EUDataActConnector(session)  # type: ignore[arg-type]
    await conn.login("user@example.com", "secret")
    await conn.list_vehicle_vins()
    sent = {ua for _req, ua in session.uas}
    assert sent == {conn._user_agent}
    assert conn._user_agent in m._user_agent_pool()
    assert any("/proxy_api/" in req for req, _ua in session.uas)


@pytest.mark.asyncio
async def test_refused_user_agent_is_replaced_before_login() -> None:
    session = _RecordingSession()
    conn = m.EUDataActConnector(session)  # type: ignore[arg-type]
    first = conn._user_agent
    session.refuse = {first}
    await conn.login("user@example.com", "secret")
    assert conn.logged_in
    assert conn._user_agent != first
    prime_uas = [ua for req, ua in session.uas if req.endswith(".com/")]
    assert prime_uas == [first, conn._user_agent]
    # Everything after the refused priming GET runs on the replacement.
    after = [ua for req, ua in session.uas[1:]]
    assert set(after) == {conn._user_agent}
