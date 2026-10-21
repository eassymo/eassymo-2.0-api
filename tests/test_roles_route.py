"""Slash-sensitive routes must answer in place so the proxy never redirects them to HTTP."""

import asyncio
import re
from collections import defaultdict

import pytest
from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from main import app


async def _allow_request(request):
    request.state.user = {"uid": "test-user"}
    return {"uid": "test-user"}


def _call(
    asgi_app,
    path: str,
    headers: list[tuple[bytes, bytes]],
    method: str = "GET",
    query: bytes = b"",
):
    captured: dict = {}
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
            captured["headers"] = {
                key.decode("latin1").lower(): value.decode("latin1")
                for key, value in message["headers"]
            }

    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": headers,
        "client": ("10.0.0.8", 443),
        "server": ("www.eassymo-server.com", 443),
    }
    asyncio.run(asgi_app(scope, receive, send))
    return captured


@pytest.fixture
def authed_app(monkeypatch):
    monkeypatch.setattr("main.verify_token", _allow_request)
    monkeypatch.setattr("app.routers.RolesRouter.rolesService.find_roles", lambda: [])
    return app


def test_roles_catalog_does_not_redirect_without_trailing_slash(authed_app):
    response = _call(authed_app, "/roles", [(b"authorization", b"Bearer test")])
    assert response["status"] == 200
    assert "location" not in response["headers"]


def test_roles_catalog_does_not_redirect_with_trailing_slash(authed_app):
    response = _call(authed_app, "/roles/", [(b"authorization", b"Bearer test")])
    assert response["status"] == 200
    assert "location" not in response["headers"]


def test_app_trusts_forwarded_proto_for_redirects():
    installed = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is ProxyHeadersMiddleware
    ]
    assert installed, "ProxyHeadersMiddleware must run before slash redirects are built"
    assert installed[0].kwargs["trusted_hosts"]


def test_collection_roots_accept_both_slash_forms():
    ignored = {"/health", "/docs", "/redoc", "/openapi.json"}
    forms = defaultdict(set)
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or not re.fullmatch(r"/[^/]+/?", path):
            continue
        if path.rstrip("/") in ignored:
            continue
        norm = path.rstrip("/")
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            forms[(method, norm)].add(path)

    missing = {
        f"{method} {norm}": sorted(paths)
        for (method, norm), paths in sorted(forms.items())
        if norm not in paths or f"{norm}/" not in paths
    }
    assert missing == {}


def test_guarantee_brand_and_photo_do_not_redirect(authed_app, monkeypatch):
    monkeypatch.setattr(
        "app.routers.GuaranteeRouter.guaranteeService.find_guarantee_by_label",
        lambda search_param: [],
    )
    monkeypatch.setattr(
        "app.routers.BrandRouter.brandService.find_brand_by_label",
        lambda search_param: [],
    )
    for path in ("/guarantee", "/guarantee/", "/brand", "/brand/", "/photo", "/photo/"):
        response = _call(
            authed_app,
            path,
            [(b"authorization", b"Bearer test")],
            method="POST" if path.startswith("/photo") else "GET",
            query=b"search_param=a",
        )
        assert response["status"] != 307, path
        assert "location" not in response["headers"], path


def test_slash_redirect_keeps_https_when_proxy_says_https():
    mini = FastAPI()
    mini.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    @mini.get("/only-slash/")
    def only_slash():
        return {"ok": True}

    response = _call(
        mini,
        "/only-slash",
        [
            (b"x-forwarded-proto", b"https"),
            (b"host", b"www.eassymo-server.com"),
        ],
    )
    assert response["status"] == 307
    assert response["headers"]["location"].startswith(
        "https://www.eassymo-server.com/only-slash/"
    )
