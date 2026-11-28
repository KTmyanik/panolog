"""Linklerin sayfa başlığını ve site simgesini getirir. YALNIZCA kullanıcı ayarlardan açarsa
çalışır; varsayılan kapalıdır ve o durumda uygulama hiçbir ağ bağlantısı kurmaz.

Standart kütüphane (urllib) kullanılır; ek bağımlılık yoktur. Kimlik bilgisi, çerez ya da
kullanıcıya ait herhangi bir veri gönderilmez: yalnızca kopyalanan adrese düz bir GET yapılır.
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

TIMEOUT_SECONDS = 5
MAX_PAGE_BYTES = 256 * 1024  # başlık <head> içindedir; sayfanın tamamı indirilmez
MAX_ICON_BYTES = 200 * 1024
MAX_TITLE_CHARS = 200
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Panolog"
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_ICON = re.compile(
    r"<link\b[^>]*\brel\s*=\s*[\"']?[^\"'>]*\bicon\b[^\"'>]*[\"']?[^>]*>", re.IGNORECASE
)
_HREF = re.compile(r"\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE)
_CHARSET = re.compile(rb"charset\s*=\s*[\"']?([\w-]+)", re.IGNORECASE)


def is_fetchable(url: str) -> bool:
    """Yalnızca genel internet adresleri: http(s), kullanıcı adı/parola içermeyen, yerel ağ
    ya da tek sözcüklü (kurum içi) sunucu adı olmayan."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return False
    if "." not in host or host.endswith((".local", ".lan", ".internal", ".intranet", ".corp")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _resolves_to_public(host: str) -> bool:
    """Ad, yerel ya da özel bir adrese çözülüyorsa istek yapılmaz (iç ağa sızma olmasın)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def parse_title(page: str) -> str | None:
    m = _TITLE.search(page)
    if not m:
        return None
    title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).split())
    return title[:MAX_TITLE_CHARS] or None


def parse_icon_url(page: str, base_url: str) -> str:
    """Sayfadaki <link rel="icon"> adresi; yoksa sitenin /favicon.ico adresi."""
    for tag in _ICON.findall(page):
        m = _HREF.search(tag)
        href = next((g for g in m.groups() if g), "") if m else ""
        if href and not href.startswith("data:"):
            return urljoin(base_url, html.unescape(href))
    return urljoin(base_url, "/favicon.ico")


def decode_page(raw: bytes, header_charset: str | None) -> str:
    charset = header_charset
    if not charset:
        m = _CHARSET.search(raw[:4096])
        charset = m.group(1).decode("ascii", "replace") if m else "utf-8"
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


class _NoRedirectToPrivate(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_fetchable(newurl) or not _resolves_to_public(urlsplit(newurl).hostname or ""):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, limit: int) -> tuple[bytes, str | None, str]:
    opener = urllib.request.build_opener(_NoRedirectToPrivate)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(limit), response.headers.get_content_charset(), response.geturl()


def fetch(url: str) -> tuple[str | None, bytes | None]:
    """(başlık, simge baytları). Hiçbir hata dışarı taşmaz; alınamayan parça None olur."""
    if not is_fetchable(url) or not _resolves_to_public(urlsplit(url).hostname or ""):
        return None, None
    try:
        raw, charset, final_url = _get(url.strip(), MAX_PAGE_BYTES)
    except (OSError, ValueError, urllib.error.URLError):
        return None, None
    page = decode_page(raw, charset)
    title = parse_title(page)
    icon = None
    icon_url = parse_icon_url(page, final_url)
    if is_fetchable(icon_url) and _resolves_to_public(urlsplit(icon_url).hostname or ""):
        try:
            data, _charset, _final = _get(icon_url, MAX_ICON_BYTES + 1)
            if 0 < len(data) <= MAX_ICON_BYTES:
                icon = data
        except (OSError, ValueError, urllib.error.URLError):
            icon = None
    return title, icon


class _Task(QRunnable):
    def __init__(self, service: "LinkMetaService", item_id: int, url: str) -> None:
        super().__init__()
        self._service, self._item_id, self._url = service, item_id, url

    def run(self) -> None:
        title, icon = self._service.fetcher(self._url)
        self._service.finished.emit(self._item_id, title, icon)


class LinkMetaService(QObject):
    """Başlık/simge isteklerini arka planda tek tek çalıştırır."""

    finished = Signal(int, object, object)  # öğe id, başlık | None, simge baytları | None

    def __init__(self, fetcher=fetch) -> None:
        super().__init__()
        self.fetcher = fetcher
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    def request(self, item_id: int, url: str) -> bool:
        if not is_fetchable(url):
            return False
        self._pool.start(_Task(self, item_id, url))
        return True

    def wait(self) -> None:
        self._pool.waitForDone()
