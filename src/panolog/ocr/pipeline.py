"""Görselden metin okumanın tek giriş noktası: uygun motorları seçer ve sonucu birleştirir.

- Model motoru (yerel PP-OCR modelleri) varsa temel okuma ondan gelir: kod, numara ve
  noktalamada Windows OCR'dan belirgin iyidir.
- Windows'ta Türkçe OCR dili yüklüyse görsel onunla da okunur ve Türkçe satırlardaki
  harf düzeltmeleri (ı/İ, ş, ğ ...) oradan alınır (bkz. merge.py).
- Model motoru yoksa (hafif kurulum) yalnızca Windows OCR kullanılır.
"""
from __future__ import annotations

from PySide6.QtGui import QImage

from . import engine, merge, model_engine
from .engine import INSTALL_HELP, OcrError, OcrResult, OcrUnavailable


def _turkish_tag(available: list[str]) -> str | None:
    return next((t for t in available if t.split("-")[0].lower() == "tr"), None)


def _windows_languages() -> list[str]:
    try:
        return engine.available_languages()
    except OcrUnavailable:
        return []


def read_image(image: QImage) -> OcrResult:
    """Görseldeki metni okur. Bloklar; arayüz iş parçacığından çağrılmamalı."""
    if image.isNull():
        raise OcrError("Görsel okunamadı.")
    if not model_engine.is_available():
        return engine.recognize(image)
    try:
        model_lines = model_engine.ModelOcr.instance().read(image)
    except Exception as exc:  # noqa: BLE001 - model çalışmazsa Windows OCR'a düş
        try:
            return engine.recognize(image)
        except OcrUnavailable:
            raise OcrError(f"Metin okunamadı: {exc}") from exc
    windows_lines: list = []
    tag = _turkish_tag(_windows_languages())
    if tag is not None:
        try:
            windows_lines = list(engine.recognize(image, tag).lines)
        except (OcrError, OcrUnavailable):
            windows_lines = []  # Türkçe düzeltme olmadan devam
    text = merge.merge(model_lines, windows_lines)
    return OcrResult(text.strip(), "model+tr" if windows_lines else "model")


def release() -> None:
    """Model motorunu bellekten bırakır; sonraki okumada yeniden yüklenir."""
    model_engine.ModelOcr.release()


def warning(*, short: bool = False) -> str | None:
    """Kullanıcıya gösterilecek OCR uyarısı; her şey yerindeyse None."""
    available = _windows_languages()
    if not model_engine.is_available():
        try:
            return engine.language_warning(engine.available_languages(), short=short)
        except OcrUnavailable as exc:
            return str(exc)
    if _turkish_tag(available) is None:
        help_text = "Kurulum adımları: Ayarlar penceresi, OCR bölümü." if short else INSTALL_HELP
        return (
            "Türkçe OCR dil paketi yüklü değil; kod ve numaralar doğru okunur ama Türkçe "
            "metinde ı/i ve İ/I harfleri karışabilir. " + help_text
        )
    return None


def status() -> str:
    """Ayarlar penceresinde gösterilen durum metni."""
    problem = warning()
    if problem:
        return "⚠ " + problem
    if model_engine.is_available():
        return (
            "Kod ve numaralar yerel OCR modeliyle, Türkçe harfler Windows'un Türkçe OCR "
            "motoruyla okunur; ikisi otomatik birleştirilir. Tek görsel için: Ctrl+O."
        )
    return "Yüklü OCR dilleri: " + ", ".join(_windows_languages()) + ". Tek görsel için: Ctrl+O."
