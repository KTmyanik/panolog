"""Windows'un yerleşik OCR motoru (Windows.Media.Ocr) için ince sarmalayıcı.

Tamamen yerel çalışır; ağ bağlantısı kurmaz. `winrt` paketleri yalnızca ihtiyaç anında
içe aktarılır, böylece paketler eksikse uygulamanın geri kalanı etkilenmez.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .lines import Line

# Tercih sırası. Türkçe motoru Latin harfli İngilizce metni de okur; tersi doğru değil
# (İngilizce motoru ş, ğ, ı, İ, ç harflerini bozar).
PREFERRED_LANGUAGES = ("tr", "en")

LANGUAGE_NAMES = {"tr": "Türkçe", "en": "İngilizce"}

INSTALL_HELP = (
    "Kurmak için: Ayarlar > Zaman ve dil > Dil ve bölge > Dil ekle > Türkçe "
    "(\"Optik karakter tanıma\" bileşeni seçili olsun). "
    "Ya da yönetici PowerShell'de:\n"
    'Add-WindowsCapability -Online -Name "Language.OCR~~~tr-TR~0.0.1.0"'
)


class OcrUnavailable(Exception):
    """OCR hiç kullanılamıyor (paket yok ya da yüklü dil paketi yok)."""


class OcrError(Exception):
    """Tek bir görsel okunamadı."""


@dataclass(frozen=True)
class OcrResult:
    text: str
    language: str  # kullanılan motorun dil etiketi, ör. "tr" veya "en-US"
    lines: tuple[Line, ...] = ()  # satırlar ve asıl görseldeki yerleri


def _primary(tag: str) -> str:
    return tag.split("-")[0].lower()


def pick_language(available: list[str], preferred: tuple[str, ...] = PREFERRED_LANGUAGES) -> str | None:
    """Yüklü OCR dilleri içinden kullanılacak olanı seçer; hiçbiri yoksa None."""
    for want in preferred:
        for tag in available:
            if _primary(tag) == want:
                return tag
    return available[0] if available else None


def missing_languages(available: list[str], preferred: tuple[str, ...] = PREFERRED_LANGUAGES) -> list[str]:
    have = {_primary(t) for t in available}
    return [p for p in preferred if p not in have]


def language_warning(available: list[str], *, short: bool = False) -> str | None:
    """Kullanıcıya gösterilecek dil uyarısı; her şey yerindeyse None.

    `short`: tray bildirimi için (Windows uzun bildirimleri keser); kurulum adımları
    yerine Ayarlar penceresine yönlendirir."""
    help_text = "Kurulum adımları: Ayarlar penceresi, OCR bölümü." if short else INSTALL_HELP
    if not available:
        return (
            "Windows'ta yüklü bir OCR dil paketi yok; görsellerden metin okunamıyor. "
            + help_text
        )
    if "tr" in missing_languages(available):
        used = pick_language(available)
        return (
            f"Türkçe OCR dil paketi yüklü değil; metinler {used} motoruyla okunuyor, "
            "bu yüzden ş, ğ, ı, İ, ç gibi harfler yanlış çıkabilir. " + help_text
        )
    return None


def available_languages() -> list[str]:
    """Yüklü OCR dil etiketleri. winrt paketleri yoksa OcrUnavailable fırlatır."""
    try:
        from winrt.windows.media.ocr import OcrEngine
    except ImportError as exc:
        raise OcrUnavailable(f"OCR bileşenleri yüklenemedi: {exc}") from exc
    try:
        return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    except OSError as exc:
        raise OcrUnavailable(f"Windows OCR kullanılamıyor: {exc}") from exc


# Ekran görüntülerindeki metin motor için küçüktür (ör. alt çizgi boşluk okunur). Yumuşak
# büyütme doğruluğu belirgin artırır: 4 yazı tipi x 5 boyut x açık/koyu tema denemesinde
# ortalama karakter doğruluğu 0,88 -> 0,92. 1,5x ve 2x benzer; 3x ek kazanç getirmiyor.
UPSCALE = 2.0
# Büyütülmüş görselin uzun kenarı bunu aşmasın (süre ve bellek sınırlı kalsın).
UPSCALE_MAX_SIDE = 4000


def upscale_factor(width: int, height: int, max_dimension: int) -> float:
    """Görselin kaç kat büyütüleceği; büyütmeye değmeyecekse 1.0."""
    side = max(width, height, 1)
    factor = min(UPSCALE, min(UPSCALE_MAX_SIDE, max_dimension) / side)
    return factor if factor >= 1.2 else 1.0


def prepare_image(image: QImage, max_dimension: int) -> QImage:
    """Motorun beklediği biçime (BGRA8) çevirir; küçükse büyütür, çok büyükse küçültür."""
    factor = upscale_factor(image.width(), image.height(), max_dimension)
    if factor > 1.0:
        image = image.scaled(
            round(image.width() * factor),
            round(image.height() * factor),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if max(image.width(), image.height()) > max_dimension:
        image = image.scaled(
            max_dimension,
            max_dimension,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    # Format_ARGB32 küçük-uçlu makinede bellekte B, G, R, A sırasındadır.
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def recognize(image: QImage, language: str | None = None) -> OcrResult:
    """Görseldeki metni okur. Bloklar; arayüz iş parçacığından ÇAĞRILMAMALI
    (tek iş parçacıklı apartmanda winrt beklemesi hata verir)."""
    if image.isNull():
        raise OcrError("Görsel okunamadı.")
    available = available_languages()
    tag = language if language in available else pick_language(available)
    if tag is None:
        raise OcrUnavailable(language_warning(available) or "OCR dili yok.")

    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    try:
        engine = OcrEngine.try_create_from_language(Language(tag))
        if engine is None:
            raise OcrUnavailable(f"OCR motoru oluşturulamadı ({tag}).")
        img = prepare_image(image, int(OcrEngine.max_image_dimension))
        writer = DataWriter()
        writer.write_bytes(bytes(img.constBits()))
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, img.width(), img.height()
        )
        result = engine.recognize_async(bitmap).get()
        scale = img.width() / max(1, image.width())  # kutular asıl görsele çevrilir
        lines = []
        for line in result.lines:
            rects = [word.bounding_rect for word in line.words]
            if not rects:
                continue
            lines.append(
                Line(
                    line.text,
                    min(r.x for r in rects) / scale,
                    min(r.y for r in rects) / scale,
                    max(r.x + r.width for r in rects) / scale,
                    max(r.y + r.height for r in rects) / scale,
                )
            )
        text = "\n".join(line.text for line in result.lines)
    except OSError as exc:
        raise OcrError(f"Metin okunamadı: {exc}") from exc
    return OcrResult(text.strip(), tag, tuple(lines))
