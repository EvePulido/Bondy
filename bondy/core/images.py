"""Finding and loading the ``<img>`` elements of a page (no LLM, no browser).

Everything read from the HTML (``src``, ``alt``, surrounding markup) is
untrusted data: ``src`` is only ever resolved inside the project root or, for
http(s), through the public-host guard; nothing in it is executed or followed
outside those rules.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from bondy.core.models import ImageOccurrence

MAX_IMAGE_BYTES = 10 * 1024 * 1024
CONTEXT_MAX_CHARS = 2000
# Formats the vision models accept (PNG, JPEG, WebP, HEIC/HEIF). GIF, AVIF and
# SVG are reported for manual review instead of being sent.
SUPPORTED_MIME = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
}
REMOTE_TIMEOUT_S = 10

_LANG = re.compile(
    r"""<html\b[^>]*?\blang\s*=\s*["']?([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)""", re.I
)


REMOTE_DISABLED_REASON = (
    "remote image download disabled; remove --no-remote-images "
    "(or set remote_images = true) to verify it"
)


def is_remote_src(src: str | None) -> bool:
    return (src or "").strip().lower().startswith(("http://", "https://", "//"))


class ImageLoadError(Exception):
    """The image cannot be verified; ``str(e)`` is the human-readable reason."""


@dataclass(frozen=True)
class LoadedImage:
    data: bytes
    mime: str


ImageLoader = Callable[[ImageOccurrence], LoadedImage]


# ----- Extraction -----
class _ImgCollector(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.html = html
        self._line_starts = [0]
        for m in re.finditer(r"\n", html):
            self._line_starts.append(m.end())
        self.found: list[dict] = []
        self._open: list[dict] = []  # open <a>/<button>: {tag, start, imgs}

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in ("a", "button"):
            self._open.append({"tag": tag, "start": self._offset(), "imgs": []})
            return
        if tag != "img":
            return
        raw = self.get_starttag_text() or ""
        start = self._offset()
        item = {
            "start": start,
            "end": start + len(raw),
            "raw": raw,
            "attrs": dict(attrs),
            "line": self.getpos()[0],
            "context": None,
        }
        self.found.append(item)
        if self._open:
            self._open[-1]["imgs"].append(item)

    def handle_endtag(self, tag):
        if tag not in ("a", "button"):
            return
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i]["tag"] == tag:
                el = self._open.pop(i)
                close = self.html.find(">", self._offset())
                end = close + 1 if close != -1 else len(self.html)
                for img in el["imgs"]:
                    if img["context"] is None:
                        img["context"] = self.html[el["start"] : end]
                break


def extract_images(
    html: str, file: str, page_dir: str = "", root_dir: str = ""
) -> list[ImageOccurrence]:
    """Every ``<img>`` in ``html`` with its exact tag and a short context.

    Inside a link/button the context is that whole element (the heuristics need
    it to see whether the image is the control's only content); elsewhere it is
    a small window around the tag.
    """
    collector = _ImgCollector(html)
    collector.feed(html)
    collector.close()
    lang_match = _LANG.search(html)
    lang = lang_match.group(1) if lang_match else ""
    out = []
    for it in collector.found:
        context = it["context"]
        if context is None:
            context = html[max(0, it["start"] - 150) : it["end"] + 150]
        attrs = it["attrs"]
        src = attrs.get("src") or attrs.get("data-src")
        out.append(
            ImageOccurrence(
                file=file,
                line=it["line"],
                tag=it["raw"],
                src=src.strip() if src else None,
                alt=attrs.get("alt") if "alt" in attrs else None,
                context=context[:CONTEXT_MAX_CHARS],
                lang=lang,
                page_dir=page_dir,
                root_dir=root_dir,
            )
        )
    return out


# ----- Loading -----
def sniff_mime(data: bytes) -> str | None:
    """Image type from magic bytes (never trusts the extension/Content-Type)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx"):
            return "image/heic"
        if brand in (b"mif1", b"msf1"):
            return "image/heif"
    head = data[:512].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml")) and b"<svg" in data[:2048].lower():
        return "image/svg+xml"
    if head.startswith((b"<!doctype html", b"<html")):
        return "text/html"
    return None


def _check_type(data: bytes) -> str:
    mime = sniff_mime(data)
    if mime in SUPPORTED_MIME:
        return mime
    if mime == "text/html":
        raise ImageLoadError("the URL returned HTML, not an image")
    if mime:
        raise ImageLoadError(f"format {mime} is not supported by the vision model")
    raise ImageLoadError("not a recognized image format")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """Re-validates every redirect target against the public-host guard."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from bondy.app_utils.security import validate_public_url

        try:
            validate_public_url(newurl)
        except ValueError as e:
            raise urllib.error.URLError(f"redirect blocked: {e}") from e
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _load_remote(url: str, max_bytes: int) -> bytes:
    from bondy.app_utils.security import validate_public_url

    try:
        validate_public_url(url)
    except ValueError as e:
        raise ImageLoadError(f"remote image blocked: {e}") from e
    opener = urllib.request.build_opener(_PublicRedirects)
    req = urllib.request.Request(url, headers={"User-Agent": "Bondy/1.0"})
    try:
        with opener.open(req, timeout=REMOTE_TIMEOUT_S) as res:
            data = res.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        raise ImageLoadError(f"HTTP {e.code} when downloading the image") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ImageLoadError(f"could not download the image: {e}") from e
    if len(data) > max_bytes:
        raise ImageLoadError(f"image larger than {max_bytes // (1024 * 1024)} MB")
    return data


def _load_local(occ: ImageOccurrence, ref: str, max_bytes: int) -> bytes:
    page_dir = Path(occ.page_dir or ".")
    root = Path(occ.root_dir or occ.page_dir or ".").resolve()
    rel = urllib.parse.unquote(urllib.parse.urlsplit(ref).path)
    base = root if rel.startswith("/") else page_dir
    try:
        target = (base / rel.lstrip("/")).resolve()
    except (OSError, ValueError) as e:
        raise ImageLoadError(f"invalid image path: {e}") from e
    # Containment (also defeats ../ and symlinks pointing outside the project)
    if not target.is_relative_to(root):
        raise ImageLoadError("image path is outside the project root")
    if not target.is_file():
        raise ImageLoadError("image file not found (404)")
    try:
        if target.stat().st_size > max_bytes:
            raise ImageLoadError(f"image larger than {max_bytes // (1024 * 1024)} MB")
        return target.read_bytes()
    except OSError as e:
        raise ImageLoadError(f"image cannot be read: {e}") from e


def load_image(
    occ: ImageOccurrence, *, allow_remote: bool = True, max_bytes: int = MAX_IMAGE_BYTES
) -> LoadedImage:
    """Default loader. Raises ``ImageLoadError`` with an actionable reason."""
    src = occ.src
    if not src:
        raise ImageLoadError("no src attribute to load")
    lower = src.lower()
    if lower.startswith("data:"):
        raise ImageLoadError("data: URI is not verified (embedded image)")
    if src.startswith("//"):
        src, lower = "https:" + src, "https:" + lower
    if lower.startswith(("http://", "https://")):
        if not allow_remote:
            raise ImageLoadError(REMOTE_DISABLED_REASON)
        data = _load_remote(src, max_bytes)
    elif (m := re.match(r"^([a-z][a-z0-9+.-]*):", lower)) and len(m.group(1)) > 1:
        # (a one-letter scheme is a Windows drive letter, i.e. a local path)
        raise ImageLoadError(f"unsupported URL scheme in src: {m.group(1)}:")
    else:
        data = _load_local(occ, src, max_bytes)
    return LoadedImage(data, _check_type(data))


def source_key(occ: ImageOccurrence) -> str:
    """Stable identity of the image file/URL (for de-duplication across pages)."""
    src = occ.src or ""
    low = src.lower()
    if low.startswith(("http://", "https://", "data:", "//")):
        return src
    rel = urllib.parse.unquote(urllib.parse.urlsplit(src).path)
    root = Path(occ.root_dir or occ.page_dir or ".")
    base = root if rel.startswith("/") else Path(occ.page_dir or ".")
    return os.path.normpath(str(base / rel.lstrip("/")))
