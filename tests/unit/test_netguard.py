"""SSRF guard: DNS rebinding, redirects to internal hosts, and path prefixes.

No real network: ``socket.getaddrinfo`` is faked and ``socket.create_connection``
is redirected to a local HTTP server, so we can assert *which address the
client tried to connect to* (it must be the validated one).
"""

import importlib.util
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from bondy.app_utils import security
from bondy.core import images, netguard
from bondy.core.models import ImageOccurrence

PUBLIC = "93.184.216.34"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
FETCH_SCRIPT = (
    Path(netguard.__file__).parents[1]
    / "resources/skills/alt-text-quality-analyzer/scripts/fetch_image.py"
)


class _Handler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, tuple[int, dict[str, str], bytes]]] = {}
    seen: ClassVar[list[tuple[str, str | None]]] = []

    def do_GET(self):
        type(self).seen.append((self.path, self.headers.get("Host")))
        status, headers, body = type(self).routes.get(
            self.path, (404, {}, b"not found")
        )
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server(monkeypatch):
    handler = type("H", (_Handler,), {"routes": {}, "seen": []})
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    connects: list[tuple[str, int]] = []

    def fake_create(address, timeout=None, source_address=None):
        connects.append(address)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", port))  # the "validated IP" is simulated
        return sock

    monkeypatch.setattr(socket, "create_connection", fake_create)
    yield handler, connects
    srv.shutdown()
    srv.server_close()


def fake_dns(monkeypatch, answers: dict[str, list[str]]):
    """``answers[host]`` is consumed one entry per lookup; the last one repeats."""
    calls: list[tuple[str, int]] = []
    state = {h: list(v) for h, v in answers.items()}

    def getaddrinfo(host, port, *a, **k):
        calls.append((host, port))
        queue = state.get(host) or [host]  # IP literals resolve to themselves
        ip = queue.pop(0) if len(queue) > 1 else queue[0]
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return calls


def occ(src: str) -> ImageOccurrence:
    return ImageOccurrence(
        file="p.html", line=1, tag="<img>", src=src, alt="x", context=""
    )


# ----- rebinding -------------------------------------------------------------
def test_rebinding_connects_to_the_validated_ip_and_resolves_once(monkeypatch, server):
    handler, connects = server
    handler.routes["/a.png"] = (200, {"Content-Type": "image/png"}, PNG)
    # first answer is public; any later lookup would be loopback (rebinding)
    calls = fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC, "127.0.0.1"]})
    res = netguard.fetch_public_bytes("http://cdn.example.test/a.png", 1024)
    assert res.data == PNG and res.content_type == "image/png"
    assert len(calls) == 1  # resolved once, not again at connect time
    assert connects == [(PUBLIC, 80)]  # connected to the IP that was checked
    assert handler.seen == [("/a.png", "cdn.example.test")]  # original Host kept


def test_rebinding_on_a_redirect_hop_is_blocked(monkeypatch, server):
    handler, connects = server
    handler.routes["/r"] = (302, {"Location": "http://rebind.test/x.png"}, b"")
    fake_dns(
        monkeypatch,
        {"cdn.example.test": [PUBLIC], "rebind.test": ["127.0.0.1"]},
    )
    with pytest.raises(netguard.NetGuardError, match="non-public"):
        netguard.fetch_public_bytes("http://cdn.example.test/r", 1024)
    assert len(connects) == 1  # never connected to the redirect target


def test_mixed_public_and_private_answer_is_refused(monkeypatch):
    def getaddrinfo(host, port, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    with pytest.raises(netguard.NetGuardError):
        netguard.resolve_public("mixed.test", 80)


# ----- redirects to internal addresses ---------------------------------------
@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://localhost/",
    ],
)
def test_redirect_to_internal_address_is_blocked(monkeypatch, server, target):
    handler, connects = server
    handler.routes["/r"] = (302, {"Location": target}, b"")
    fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC], "localhost": ["127.0.0.1"]})
    with pytest.raises(netguard.NetGuardError):
        netguard.fetch_public_bytes("http://cdn.example.test/r", 1024)
    assert len(connects) == 1


def test_relative_redirect_is_followed_and_non_http_scheme_is_blocked(
    monkeypatch, server
):
    handler, _ = server
    handler.routes["/r"] = (301, {"Location": "/real.png"}, b"")
    handler.routes["/real.png"] = (200, {"Content-Type": "image/png"}, PNG)
    handler.routes["/f"] = (302, {"Location": "file:///etc/passwd"}, b"")
    fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC]})
    ok = netguard.fetch_public_bytes("http://cdn.example.test/r", 1024)
    assert ok.data == PNG and ok.final_url.endswith("/real.png")
    with pytest.raises(netguard.NetGuardError, match="http"):
        netguard.fetch_public_bytes("http://cdn.example.test/f", 1024)


def test_redirect_loop_is_capped(monkeypatch, server):
    handler, connects = server
    handler.routes["/loop"] = (302, {"Location": "/loop"}, b"")
    fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC]})
    with pytest.raises(netguard.FetchError, match="redirects"):
        netguard.fetch_public_bytes("http://cdn.example.test/loop", 1024)
    assert len(connects) == netguard.MAX_REDIRECTS + 1


# ----- URL syntax, ports, size -----------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.test/a.png",
        "file:///etc/passwd",
        "http://user:pw@example.test/a.png",
        "http://example.test:bad/a.png",
        "http:///nohost",
    ],
)
def test_bad_urls_are_rejected_before_any_lookup(monkeypatch, url):
    calls = fake_dns(monkeypatch, {"example.test": [PUBLIC]})
    with pytest.raises(netguard.NetGuardError):
        netguard.fetch_public_bytes(url, 1024)
    assert calls == []


def test_default_port_depends_on_scheme(monkeypatch):
    assert netguard.parse_public_url("http://a.test/x") == ("http", "a.test", 80)
    assert netguard.parse_public_url("https://a.test/x") == ("https", "a.test", 443)
    assert netguard.parse_public_url("http://a.test:8080/")[2] == 8080
    calls = fake_dns(monkeypatch, {"a.test": [PUBLIC]})
    netguard.validate_public_url("http://a.test/x")
    assert calls == [("a.test", 80)]


def test_oversize_body_and_http_error(monkeypatch, server):
    handler, _ = server
    handler.routes["/big"] = (200, {"Content-Type": "image/png"}, b"x" * 100)
    fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC]})
    with pytest.raises(netguard.ResponseTooLarge):
        netguard.fetch_public_bytes("http://cdn.example.test/big", 50)
    with pytest.raises(netguard.FetchError) as ei:
        netguard.fetch_public_bytes("http://cdn.example.test/missing", 50)
    assert ei.value.status == 404


# ----- the three consumers go through the guard ------------------------------
def test_images_load_remote_uses_guard_and_maps_errors(monkeypatch, server):
    handler, _ = server
    handler.routes["/r"] = (302, {"Location": "http://169.254.169.254/"}, b"")
    handler.routes["/ok.png"] = (200, {"Content-Type": "image/png"}, PNG)
    fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC]})
    ok = images.load_image(occ("http://cdn.example.test/ok.png"))
    assert ok.mime == "image/png"
    with pytest.raises(images.ImageLoadError, match="blocked"):
        images.load_image(occ("http://cdn.example.test/r"))
    with pytest.raises(images.ImageLoadError, match="HTTP 404"):
        images.load_image(occ("http://cdn.example.test/zz"))


def test_vision_tools_load_image_blocks_redirect_to_metadata(monkeypatch, server):
    from bondy.app_utils import vision_tools

    handler, _ = server
    handler.routes["/r"] = (302, {"Location": "http://169.254.169.254/"}, b"")
    handler.routes["/ok.png"] = (200, {"Content-Type": "image/png"}, PNG)
    fake_dns(monkeypatch, {"cdn.example.test": [PUBLIC]})
    assert vision_tools._load_image("http://cdn.example.test/ok.png") == (
        PNG,
        "image/png",
    )
    with pytest.raises(ValueError, match=r"non-public|not allowed"):
        vision_tools._load_image("http://cdn.example.test/r")


def test_fetch_image_script_blocks_internal_hosts(monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch_image_script", FETCH_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fake_dns(monkeypatch, {"intranet.test": ["10.1.2.3"]})
    for url in ("http://intranet.test/a.png", "http://169.254.169.254/", "file:///x"):
        out = json.loads(mod.fetch_image_as_base64(url))
        assert "error" in out and "data" not in out


# ----- security.py path prefix -----------------------------------------------
def test_path_prefix_requires_a_separator():
    a = os.path.abspath(os.sep + "a")
    root = os.path.join(a, "Bondy")
    assert security._is_within(os.path.join(root, "examples", "x"), root)
    assert security._is_within(root, root)
    assert not security._is_within(os.path.join(a, "Bondy-evil", "examples"), root)
    assert not security._is_within(root + "examples", root)


def test_sibling_directory_with_same_prefix_is_path_traversal():
    base = os.path.abspath(os.path.join(os.path.dirname(security.__file__), "..", ".."))
    sibling = os.path.basename(base) + "-evil"
    with pytest.raises(ValueError, match="Path traversal"):
        security.validate_input_before_audit(f"../{sibling}/examples/site_1_bad_alt")


def test_examples_and_lookalike_folder_are_distinguished():
    security.validate_input_before_audit("examples/site_1_bad_alt")  # allowed
    with pytest.raises(ValueError, match="not allowed"):
        security.validate_input_before_audit("examples_evil/site_1_bad_alt")
