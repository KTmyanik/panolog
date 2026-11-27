"""Yerel OCR modelleri (PP-OCRv6: metin bulucu + tanıyıcı) ile okuma.

Windows OCR kod ve numaralarda zayıf kaldığı için eklendi (`1`/`l` karışması, yalnızca
noktalama içeren satırların atlanması). Modeller ONNX Runtime ile doğrudan çalıştırılır;
görüntü işleme Qt ve NumPy ile yapılır. Böylece OpenCV gibi büyük bağımlılıklar ve ağdan
model indiren kodlar pakete girmez. Her şey yereldir.

Akış:
1. Metin bulucu görseldeki metin bölgelerini verir (olasılık haritası -> kutular).
2. Bulucunun atladığı küçük parçalar (ör. yalnızca "..." içeren satır) görseldeki
   "mürekkep" parçalarından bulunur.
3. Her kutu kesilip tanıyıcıya verilir (CTC çözümleme).

Ekran görüntülerinde metin yataydır; kutular eksenlere paralel dikdörtgen kabul edilir.
"""
from __future__ import annotations

import math
import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .lines import Line

MODEL_DIR = Path(__file__).parent / "models"
DET_MODEL = "PP-OCRv6_det_small.onnx"
REC_MODEL = "PP-OCRv6_rec_small.onnx"

# Metin bulucu (DB) ayarları; modelin eğitildiği değerler.
_DET_MIN_SIDE = 736  # kısa kenar bundan küçükse büyütülür
_DET_MAX_UPSCALE = 99.0
_DET_MAX_SIDE = 2000
_DET_THRESH = 0.3
_DET_BOX_THRESH = 0.5
_DET_UNCLIP = 1.6
# Tanıyıcı ayarları
_REC_HEIGHT = 48
_REC_MIN_WIDTH = 320
_REC_BATCH = 6
_MIN_TEXT_SCORE = 0.5


_LOCK = threading.Lock()


class ModelOcrUnavailable(Exception):
    """Model motoru kullanılamıyor (kütüphane ya da model dosyası yok)."""


def is_available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return (MODEL_DIR / DET_MODEL).is_file() and (MODEL_DIR / REC_MODEL).is_file()


# ---- saf yardımcılar (model gerektirmez; birim testleri bunları sınar) -----------------
def components(mask) -> list[tuple[int, int, int, int, int]]:
    """İkili maskedeki bağlı bileşenler (8-komşuluk): (x0, y0, x1, y1, piksel sayısı),
    x1/y1 dahil değil. Satır içi "koşu"lar üzerinden birleştirme-bulma ile çalışır."""
    import numpy as np

    mask = np.asarray(mask, dtype=bool)
    height, width = mask.shape
    parent: list[int] = []
    box: list[list[int]] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    padded = np.zeros((height, width + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    previous: list[tuple[int, int, int]] = []
    for y in range(height):
        row = edges[y]
        starts = np.flatnonzero(row == 1)
        if starts.size == 0:
            previous = []
            continue
        ends = np.flatnonzero(row == -1)
        current: list[tuple[int, int, int]] = []
        j = 0
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            label = -1
            while j < len(previous) and previous[j][1] < x0:  # tamamen solda kalanlar
                j += 1
            k = j
            while k < len(previous) and previous[k][0] <= x1:  # çaprazlar dahil dokunanlar
                root = find(previous[k][2])
                if label == -1:
                    label = root
                elif root != label:
                    parent[root] = label
                    a, b = box[label], box[root]
                    a[0], a[1] = min(a[0], b[0]), min(a[1], b[1])
                    a[2], a[3], a[4] = max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]
                k += 1
            if label == -1:
                label = len(parent)
                parent.append(label)
                box.append([x0, y, x1, y + 1, 0])
            b = box[label]
            b[0], b[2], b[3], b[4] = min(b[0], x0), max(b[2], x1), y + 1, b[4] + (x1 - x0)
            current.append((x0, x1, label))
        previous = current
    return [tuple(box[i]) for i in range(len(parent)) if parent[i] == i]  # type: ignore[misc]


def unclip(x0: float, y0: float, x1: float, y1: float, ratio: float = _DET_UNCLIP):
    """Bulucu metnin çekirdeğini işaretler; kutu, alan/çevre oranı kadar genişletilir."""
    w, h = x1 - x0, y1 - y0
    d = w * h * ratio / (2 * (w + h)) if w > 0 and h > 0 else 0.0
    return x0 - d, y0 - d, x1 + d, y1 + d


def ctc_decode(indices, probabilities, characters: list[str]) -> tuple[str, float]:
    """Tanıyıcı çıktısını metne çevirir: yinelenenler ve boş (0) simge atılır."""
    chars: list[str] = []
    scores: list[float] = []
    last = 0
    for index, prob in zip(indices, probabilities):
        index = int(index)
        if index != 0 and index != last and index < len(characters):
            chars.append(characters[index])
            scores.append(float(prob))
        last = index
    return "".join(chars), (sum(scores) / len(scores) if scores else 0.0)


def median_height(boxes) -> float:
    heights = sorted(b[3] - b[1] for b in boxes)
    return heights[len(heights) // 2] if heights else 20.0


def join_neighbours(boxes, line_h: float):
    """Aynı satırda birbirine çok yakın kutuları tek kutu yapar.

    Bulucu bazen satır sonundaki virgülü ya da parantezi ayrı bir kutu olarak verir; tek
    başına okununca yanlış çıkar ("," -> "J"). Satırın parçası olarak okununca doğru çıkar.
    Sütunlar gibi aralarında belirgin boşluk olan kutular ayrı kalır.
    """
    boxes = sorted((list(b) for b in boxes), key=lambda b: b[0])
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                overlap = min(a[3], b[3]) - max(a[1], b[1])
                if overlap < 0.5 * min(a[3] - a[1], b[3] - b[1]):
                    continue
                gap = max(a[0], b[0]) - min(a[2], b[2])
                if gap < line_h * 0.8:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return [tuple(b) for b in boxes]


def attach_part(boxes, part, line_h: float) -> bool:
    """Bulucunun kaçırdığı küçük parça (ör. satır sonundaki "(") bir kutunun satırında ve
    hemen yanındaysa kutuyu o parçayı kapsayacak kadar genişletir. Eklendiyse True."""
    px0, py0, px1, py1 = part[:4]
    cy = (py0 + py1) / 2
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        if not (y0 <= cy <= y1):
            continue
        gap = max(x0, px0) - min(x1, px1)
        if gap < line_h * 1.2:
            boxes[i] = (min(x0, px0), min(y0, py0), max(x1, px1), max(y1, py1))
            return True
    return False


# ---- görüntü yardımcıları ------------------------------------------------------------
def to_array(image: QImage):
    """QImage -> (yükseklik, genişlik, 3) BGR uint8 dizi."""
    import numpy as np

    img = image.convertToFormat(QImage.Format.Format_BGR888)
    w, h = img.width(), img.height()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.bytesPerLine() * h)
    return raw.reshape(h, img.bytesPerLine())[:, : w * 3].reshape(h, w, 3).copy()


def _resize(array, width: int, height: int):
    import numpy as np

    h, w = array.shape[:2]
    if (w, h) == (width, height):
        return array
    src = QImage(np.ascontiguousarray(array).data, w, h, w * 3, QImage.Format.Format_BGR888)
    scaled = src.scaled(
        width,
        height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return to_array(scaled)


# ---- motor ---------------------------------------------------------------------------
class ModelOcr:
    """Modelleri ilk kullanımda yükler (yüzlerce MB bellek); tek örnek paylaşılır."""

    _instance: "ModelOcr | None" = None

    @classmethod
    def instance(cls) -> "ModelOcr":
        with _LOCK:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def release(cls) -> None:
        """Modelleri bellekten bırakır; sonraki okumada yeniden yüklenir."""
        with _LOCK:
            cls._instance = None

    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ModelOcrUnavailable(f"OCR model bileşenleri yüklenemedi: {exc}") from exc
        det, rec = model_dir / DET_MODEL, model_dir / REC_MODEL
        if not det.is_file() or not rec.is_file():
            raise ModelOcrUnavailable(f"OCR model dosyaları bulunamadı: {model_dir}")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        # Arka planda çalışırken makineyi kilitlemesin: çekirdeklerin en çok yarısı, en çok 4.
        options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
        providers = ["CPUExecutionProvider"]
        self._det = ort.InferenceSession(str(det), options, providers=providers)
        self._rec = ort.InferenceSession(str(rec), options, providers=providers)
        meta = self._rec.get_modelmeta().custom_metadata_map
        if "character" not in meta:
            raise ModelOcrUnavailable("Tanıyıcı modelde karakter listesi yok.")
        # 0 = CTC boş simgesi; sona boşluk karakteri eklenir (modelin sözleşmesi).
        self._characters = ["", *meta["character"].splitlines(), " "]

    # -- metin bulma --
    def detect(self, array) -> list[tuple[float, float, float, float]]:
        import numpy as np

        h, w = array.shape[:2]
        ratio = 1.0
        if min(h, w) < _DET_MIN_SIDE:
            ratio = min(_DET_MAX_UPSCALE, _DET_MIN_SIDE / min(h, w))
        if max(h, w) * ratio > _DET_MAX_SIDE:
            ratio = _DET_MAX_SIDE / max(h, w)
        rw = max(32, int(round(w * ratio / 32) * 32))
        rh = max(32, int(round(h * ratio / 32) * 32))
        resized = _resize(array, rw, rh).astype(np.float32)
        blob = ((resized / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[np.newaxis]
        prob = self._det.run(None, {self._det.get_inputs()[0].name: blob})[0][0, 0]
        mask = prob > _DET_THRESH
        # 2x2 genişletme: ince kopuklukları birleştirir (modelin varsayılan son işlemi).
        mask[:-1, :] |= mask[1:, :].copy()
        mask[:, :-1] |= mask[:, 1:].copy()
        boxes = []
        sx, sy = w / rw, h / rh
        for x0, y0, x1, y1, _area in components(mask):
            if min(x1 - x0, y1 - y0) < 3:
                continue
            if float(prob[y0:y1, x0:x1].mean()) < _DET_BOX_THRESH:
                continue
            ux0, uy0, ux1, uy1 = unclip(x0, y0, x1, y1)
            if min(ux1 - ux0, uy1 - uy0) < 5:
                continue
            boxes.append(
                (max(0.0, ux0 * sx), max(0.0, uy0 * sy), min(float(w), ux1 * sx), min(float(h), uy1 * sy))
            )
        return boxes

    # -- tanıma --
    def recognize(self, crops: list) -> list[tuple[str, float]]:
        import numpy as np

        results: list[tuple[str, float]] = [("", 0.0)] * len(crops)
        order = sorted(range(len(crops)), key=lambda i: crops[i].shape[1] / max(1, crops[i].shape[0]))
        name = self._rec.get_inputs()[0].name
        for start in range(0, len(order), _REC_BATCH):
            batch = order[start : start + _REC_BATCH]
            widest = max(crops[i].shape[1] / max(1, crops[i].shape[0]) for i in batch)
            width = max(_REC_MIN_WIDTH, int(_REC_HEIGHT * widest))
            blob = np.zeros((len(batch), 3, _REC_HEIGHT, width), dtype=np.float32)
            for n, i in enumerate(batch):
                crop = crops[i]
                ratio = crop.shape[1] / max(1, crop.shape[0])
                rw = max(1, min(width, int(math.ceil(_REC_HEIGHT * ratio))))
                resized = _resize(crop, rw, _REC_HEIGHT).astype(np.float32)
                blob[n, :, :, :rw] = ((resized / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)
            preds = self._rec.run(None, {name: blob})[0]
            indices, probs = preds.argmax(axis=2), preds.max(axis=2)
            for n, i in enumerate(batch):
                results[i] = ctc_decode(indices[n], probs[n], self._characters)
        return results

    # -- atlanan parçalar --
    @staticmethod
    def missed_regions(array, found: list[tuple[float, float, float, float]]):
        """Hiçbir metin kutusuna girmeyen küçük mürekkep parçalarını ele alır.

        (ayrı okunacak bölgeler, komşu parçaları içine alacak biçimde genişletilmiş kutular)
        döner."""
        import numpy as np

        gray = array.astype(np.int16).sum(axis=2) // 3
        ink = np.abs(gray - int(np.median(gray))) > 60
        line_h = median_height(found)
        found = list(found)
        for x0, y0, x1, y1 in found:  # bulunan metin zaten okunacak
            ink[max(0, int(y0) - 2) : int(y1) + 2, max(0, int(x0) - 2) : int(x1) + 2] = False
        parts = [
            c
            for c in components(ink)
            # çerçeve, ayırıcı çizgi, resim gibi büyük parçalar metin değildir
            if c[3] - c[1] <= line_h * 1.5 and c[2] - c[0] <= line_h * 3
        ]
        # Bir kutunun hemen yanındaki parçalar o kutuya katılır; kalanlar ayrı satır adayıdır.
        parts.sort(key=lambda p: p[0])
        parts = [p for p in parts if not attach_part(found, p, line_h)]
        parts.sort(key=lambda p: (p[1] + p[3]) / 2)
        rows: list[list] = []
        for p in parts:
            cy = (p[1] + p[3]) / 2
            if rows and abs(cy - sum((q[1] + q[3]) / 2 for q in rows[-1]) / len(rows[-1])) < line_h * 0.6:
                rows[-1].append(p)
            else:
                rows.append([p])
        regions = []
        for row in rows:
            row.sort()
            group = [row[0]]
            for p in row[1:]:  # aynı satırda uzak duran parçalar ayrı bölgedir
                if p[0] - group[-1][2] > line_h * 2:
                    regions.append(group)
                    group = [p]
                else:
                    group.append(p)
            regions.append(group)
        h, w = array.shape[:2]
        out = []
        for g in regions:
            x0, y0 = min(p[0] for p in g), min(p[1] for p in g)
            x1, y1 = max(p[2] for p in g), max(p[3] for p in g)
            cy = (y0 + y1) / 2
            # Noktalama küçüktür; tanıyıcıya tam satır yüksekliğinde bir şerit verilir.
            top, bottom = max(0.0, min(y0 - 3, cy - line_h * 0.55)), min(float(h), max(y1 + 3, cy + line_h * 0.55))
            pad = line_h * 0.9  # dar kesitlerde tanıyıcı kararsız; yanlarda boşluk bırakılır
            out.append((max(0.0, x0 - pad), top, min(float(w), x1 + pad), bottom))
        return out, found

    # -- tam okuma --
    def read(self, image: QImage, recover: bool = True) -> list[Line]:
        """Görseldeki metin parçaları (sırasız). Bloklar; arayüz iş parçacığından çağrılmamalı."""
        array = to_array(image)
        h, w = array.shape[:2]
        if h < 2 or w < 2:
            return []
        found = self.detect(array)
        found = join_neighbours(found, median_height(found))
        regions: list = []
        if recover:
            regions, found = self.missed_regions(array, found)
        boxes = [(b, False) for b in found] + [(b, True) for b in regions]
        crops, kept = [], []
        for (x0, y0, x1, y1), recovered in boxes:
            crop = array[int(y0) : int(math.ceil(y1)), int(x0) : int(math.ceil(x1))]
            if crop.shape[0] >= 2 and crop.shape[1] >= 2:
                crops.append(crop)
                kept.append(((x0, y0, x1, y1), recovered))
        # Kurtarılan dar kesitler tek tek okunur: toplu okumada geniş satırlarla aynı
        # genişliğe doldurulmaları sonucu bozuyor.
        normal = [i for i, (_b, recovered) in enumerate(kept) if not recovered]
        results: list[tuple[str, float]] = [("", 0.0)] * len(kept)
        for i, res in zip(normal, self.recognize([crops[i] for i in normal])):
            results[i] = res
        for i, (_b, recovered) in enumerate(kept):
            if recovered:
                results[i] = self.recognize([crops[i]])[0]
        out = []
        for ((x0, y0, x1, y1), recovered), (text, score) in zip(kept, results):
            text = text.strip().replace("…", "...") if recovered else text.strip()
            if text and score >= _MIN_TEXT_SCORE:
                out.append(Line(text, x0, y0, x1, y1, score))
        return out
