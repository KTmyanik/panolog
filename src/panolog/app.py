"""Bileşenleri birbirine bağlayan uygulama denetleyicisi."""
from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QSystemTrayIcon

from . import APP_NAME, backup, codekind, paths, winapi
from .classifier import Category, classify
from .hotkey import GlobalHotkey, HotkeyError
from .linkmeta import LinkMetaService
from .monitor import ClipboardListener, PauseState, read_clipboard
from .ocr import OcrResult, OcrService, OcrUnavailable, pipeline
from .paste import (
    return_focus,
    write_files_to_clipboard,
    write_image_to_clipboard,
    write_text_to_clipboard,
    write_to_clipboard,
)
from .sensitive import evaluate
from .settings import Settings, SettingsStore, autostart
from .snippets import SnippetRepository, expand
from .storage import FileRef, Repository, connect
from .storage.images import ImageStore, hash_image
from .storage.repository import files_hash, text_hash
from .ui.image_editor import ImageEditorDialog
from .ui.popup import Popup
from .ui.settings_dialog import SettingsDialog
from .ui.draw_canvas import to_png
from .ui.snippet_dialogs import SnippetEditDialog, SnippetManagerDialog
from .ui.stats_dialog import StatsDialog
from .ui.tray import Tray

_MAINTENANCE_MS = 30_000
_MAX_HTML_CHARS = 2_000_000
_OCR_IDLE_RELEASE_MS = 120_000


def default_image_name(now: datetime | None = None) -> str:
    """Kaydedilen görsel için önerilen dosya adı (Windows'ta geçerli karakterlerle)."""
    return f"{APP_NAME} {(now or datetime.now()):%Y-%m-%d %H%M%S}.png"


class Controller(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._pause = PauseState()
        self._save_dir: str | None = None  # "PNG olarak kaydet" için son kullanılan klasör
        self._prev_window: int | None = None
        self._settings_dialog: SettingsDialog | None = None

        self._conn = connect(paths.db_path())
        self._images = ImageStore(paths.images_dir())
        self._repo = Repository(self._conn, on_delete=self._images.remove_for)
        self._snippets = SnippetRepository(self._conn)
        self._dialog_open = False
        self._store = SettingsStore(self._repo)
        self._settings: Settings = self._store.load()

        self._maintain()
        self._images.sweep_orphans(self._repo.image_files())

        self._popup = Popup(self._repo, self._snippets)
        self._popup.set_theme(self._settings.theme, self._settings.animations)
        self._popup.pasteRequested.connect(self._paste)
        self._popup.snippetRequested.connect(self._paste_snippet)
        self._popup.saveAsSnippetRequested.connect(self._save_as_snippet)
        self._popup.editSnippetRequested.connect(self._edit_snippet)
        self._popup.ocrRequested.connect(self._ocr_requested)
        self._popup.editImageRequested.connect(self._edit_image)
        self._popup.saveImageRequested.connect(self._save_image)
        self._popup.pasteTextRequested.connect(self._paste_text)
        self._popup.pasteManyRequested.connect(self._paste_many)
        self._popup.queueRequested.connect(self._start_queue)
        self._popup.exportRequested.connect(self._export)
        self._popup.ruleRequested.connect(lambda app: self._open_settings(rule_app=app))

        self._ocr = OcrService()
        self._ocr.finished.connect(self._ocr_finished)
        self._ocr.failed.connect(self._ocr_failed)
        self._ocr_disabled = False  # OCR bu oturumda kullanılamıyor; indeksleme durur
        self._ocr_warned = False  # dil uyarısı oturumda bir kez gösterilir
        # OCR modeli bellekte yüzlerce MB tutar; bir süre kullanılmayınca bırakılır.
        self._ocr_idle = QTimer(self)
        self._ocr_idle.setSingleShot(True)
        self._ocr_idle.setInterval(_OCR_IDLE_RELEASE_MS)
        self._ocr_idle.timeout.connect(self._release_ocr)

        self._tray = Tray()
        self._tray.openRequested.connect(self.show_popup)
        self._tray.pauseToggled.connect(self._set_paused)
        self._tray.pauseForRequested.connect(self._pause_for)
        self._tray.skipNextToggled.connect(self._set_skip_next)
        self._tray.menuOpening.connect(self._sync_pause)
        # Süreli duraklatma ya da "sonraki kopya" kendiliğinden bitince tray güncellensin.
        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.timeout.connect(self._sync_pause)
        self._tray.clearRequested.connect(self._clear_history)
        self._tray.settingsRequested.connect(self._open_settings)
        self._tray.snippetsRequested.connect(self._open_snippet_manager)
        self._tray.statsRequested.connect(self._open_stats)
        self._tray.exportRequested.connect(lambda: self._export(None))
        self._tray.importRequested.connect(self._import)
        self._tray.queueCancelRequested.connect(self._cancel_queue)
        self._tray.quitRequested.connect(self.quit)
        self._tray.show()

        self._listener = ClipboardListener()
        self._listener.changed.connect(self._on_clipboard_changed)

        self._hotkey = GlobalHotkey()
        self._hotkey.activated.connect(self.toggle_popup)
        self._register_hotkey()
        # Sıralı yapıştırma: kuyruktaki öğeleri ikinci bir global kısayol birer birer yapıştırır.
        # Klavye kancası kurulmadığı için Ctrl+V'nin kendisi izlenemez; ayrı kısayol bu yüzden.
        self._queue: list[int] = []
        self._seq_hotkey = GlobalHotkey()
        self._seq_hotkey.activated.connect(self._paste_next)
        self._register_seq_hotkey(notify=False)

        self._links = LinkMetaService()
        self._links.finished.connect(self._link_meta_ready)
        self._scan_existing_code()

        self._timer = QTimer(self)
        self._timer.setInterval(_MAINTENANCE_MS)
        self._timer.timeout.connect(self._maintain)
        self._timer.start()
        QTimer.singleShot(2000, self._index_next)

    # ---- clipboard izleme ---------------------------------------------------
    def _on_clipboard_changed(self, source_app: str | None) -> None:
        if self._pause.is_paused():
            return
        payload = read_clipboard()
        if payload.internal or payload.private or self._settings.is_excluded(source_app):
            return
        category = classify(
            has_files=bool(payload.files), has_image=payload.image is not None, text=payload.text
        )
        if category is None:
            return
        rule = self._settings.rule_for(source_app)
        if rule is not None and rule["action"] == "skip":
            return  # kullanıcı bu uygulamadan gelenlerin kaydedilmemesini istedi
        # Buraya gelen kopya normalde kaydedilirdi; "sonraki kopyayı kaydetme" onu tüketir.
        if not self._pause.allow():
            self._sync_pause()
            return
        limit = self._settings.limit_for(category)
        if category is Category.FILE:
            item, _created = self._repo.add_item(
                category,
                files_hash(payload.files),
                files=[FileRef.from_path(p) for p in payload.files],
                source_app=source_app,
                limit=limit,
            )
        elif category is Category.IMAGE:
            item = self._record_image(payload.image, source_app)
        else:
            html = payload.html if category is Category.TEXT else None
            item = self._record_text(category, payload.text or "", html, source_app)
            if item is None:
                return
        self._repo.bump_stat(category, source_app)  # yalnızca sayaç; içerik yazılmaz
        self._apply_rule(rule, item.id)
        if category is Category.LINK and self._settings.link_fetch and not item.link_title:
            self._links.request(item.id, item.text or "")
        if self._popup.isVisible():
            self._popup.refresh()

    def _apply_rule(self, rule: dict | None, item_id: int) -> None:
        """Uygulama kuralının kayıttan sonraki etkisi: etiketleme ya da süreli silme."""
        if rule is None:
            return
        if rule["action"] == "tag":
            self._repo.set_tag([item_id], rule["value"])
        elif rule["action"] == "expire":
            seconds = int(rule["value"]) * 60
            self._repo.set_expiry(item_id, time.time() + seconds)
            if seconds <= 3600:  # kısa süreler periyodik bakımı beklemeden silinsin
                QTimer.singleShot(seconds * 1000 + 250, self._maintain)

    def _scan_existing_code(self) -> None:
        """Bir kereliğine: Kod sekmesi eklenmeden önce kaydedilmiş metinleri oraya taşır."""
        if self._repo.get_setting("code_scan") == "1":
            return
        for item in self._repo.list_items(Category.TEXT):
            kind = codekind.detect(item.text or "")
            if kind:
                self._repo.reclassify(item.id, Category.CODE, kind)
        self._repo.set_setting("code_scan", "1")

    def _link_meta_ready(self, item_id: int, title, icon) -> None:
        """Arka planda alınan sayfa başlığı ve simgeyi kaydeder (simge küçük PNG'ye çevrilir)."""
        png = None
        if icon:
            image = QImage.fromData(icon)
            if not image.isNull():
                png = to_png(image.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        if title or png:
            self._repo.set_link_meta(item_id, title, png)
            if self._popup.isVisible():
                self._popup.refresh()

    def _record_image(self, image: QImage, source_app: str | None):
        """Görseli diske ve geçmişe ekler; otomatik OCR açıksa okumayı başlatır."""
        digest = hash_image(image)
        full, thumb = self._images.save(image, digest)
        item, _created = self._repo.add_item(
            Category.IMAGE,
            digest,
            image_path=str(full),
            thumb_path=str(thumb),
            width=image.width(),
            height=image.height(),
            source_app=source_app,
            limit=self._settings.limit_for(Category.IMAGE),
        )
        if self._settings.ocr_auto and not item.ocr_done and not self._ocr_disabled:
            # Tam boy PNG henüz diske yazılıyor olabilir; görselin kendisi verilir.
            self._ocr.request(item.id, image.copy(), interactive=False)
        return item

    def _record_text(
        self, category: Category, text: str, html: str | None, source_app: str | None
    ):
        """Metni/linki/kodu hassas veri ayarına göre geçmişe ekler. Kaydedilen öğeyi, hassas
        veri ayarı nedeniyle kaydedilmediyse None döndürür."""
        if category is Category.LINK:
            text = text.strip()
        if html and len(html) > _MAX_HTML_CHARS:
            html = None
        s = self._settings
        decision = evaluate(
            text,
            s.sensitive_mode,
            email=s.detect_email,
            phone=s.detect_phone,
            ttl_seconds=s.sensitive_ttl_seconds,
        )
        if not decision.store:
            return None
        ttl = decision.ttl_seconds
        item, _created = self._repo.add_item(
            category,
            text_hash(text),
            text=text,
            html=html,
            kind=codekind.detect(text) if category is Category.CODE else None,
            source_app=source_app,
            sensitive=decision.sensitive,
            masked_text=decision.masked_text,
            expires_at=time.time() + ttl if ttl else None,
            limit=self._settings.limit_for(category),
        )
        if ttl:  # süre dolar dolmaz sil; periyodik bakımı bekleme
            QTimer.singleShot(int(ttl * 1000) + 250, self._maintain)
        return item

    # ---- popup ve yapıştırma ------------------------------------------------
    def toggle_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self.show_popup()

    def show_popup(self) -> None:
        self._prev_window = winapi.GetForegroundWindow()
        self._popup.open_at_cursor()

    def _paste(self, item_id: int, plain: bool) -> None:
        item = self._repo.get(item_id)
        if item is None or not write_to_clipboard(item, plain):
            self._notify("Öğe clipboard'a yazılamadı (dosya silinmiş veya taşınmış olabilir).")
            return
        self._repo.touch(item_id)
        # Önce odağı geri ver, sonra gizle: popup hâlâ öndeyken odak değiştirmeye izin var.
        return_focus(self._prev_window, send_paste=self._settings.auto_paste)
        self._popup.hide()

    def _paste_text(self, text: str) -> None:
        """Dönüştürülmüş metni yapıştırır; asıl öğe değişmez, sonuç geçmişe eklenmez."""
        write_text_to_clipboard(text)
        return_focus(self._prev_window, send_paste=self._settings.auto_paste)
        self._popup.hide()

    def _paste_many(self, item_ids: list) -> None:
        """Çoklu seçim: metinleri ayraçla birleştirir, dosyaları tek listede yapıştırır."""
        items = [i for i in (self._repo.get(item_id) for item_id in item_ids) if i is not None]
        if not items:
            return
        category = items[0].category
        if category is Category.IMAGE:
            self._popup.show_status("Görseller birleştirilemez; Ctrl+Enter ile sıralı yapıştırın")
            return
        if category is Category.FILE:
            paths = [f.path for item in items for f in item.files]
            if not write_files_to_clipboard(paths):
                self._notify("Dosyalar bulunamadı (silinmiş veya taşınmış olabilir).")
                return
        else:
            write_text_to_clipboard(
                self._settings.join_separator.join(item.text or "" for item in items)
            )
        return_focus(self._prev_window, send_paste=self._settings.auto_paste)
        self._popup.hide()

    # ---- sıralı yapıştırma --------------------------------------------------
    def _start_queue(self, item_ids: list) -> None:
        self._queue = [item_id for item_id in item_ids if self._repo.get(item_id) is not None]
        self._sync_queue()
        return_focus(self._prev_window, send_paste=False)
        self._popup.hide()
        if self._queue:
            self._tray.showMessage(
                APP_NAME,
                f"{len(self._queue)} öğe sıraya alındı. Her {self._settings.seq_hotkey} basışında "
                "sıradaki öğe yapıştırılır.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _cancel_queue(self) -> None:
        self._queue = []
        self._sync_queue()

    def _sync_queue(self) -> None:
        self._tray.set_queue(len(self._queue), self._settings.seq_hotkey)

    def _paste_next(self) -> None:
        """Sıralı yapıştırma kısayolu: kuyruktaki sıradaki öğeyi etkin pencereye yapıştırır."""
        item = None
        while self._queue and item is None:
            item = self._repo.get(self._queue.pop(0))  # bu arada silinmiş öğeler atlanır
        self._sync_queue()
        if item is None:
            self._notify(
                "Sıralı yapıştırma kuyruğu boş. Geçmiş penceresinde öğeleri Shift+↓ ile "
                "işaretleyip Ctrl+Enter'a basın."
            )
            return
        if not write_to_clipboard(item):
            self._notify("Öğe clipboard'a yazılamadı (dosya silinmiş veya taşınmış olabilir).")
            return
        # Kısayolun tuşları hâlâ basılı olabilir; clipboard yerleşsin diye kısa bir bekleme.
        QTimer.singleShot(80, winapi.send_ctrl_v)
        if not self._queue:
            self._tray.showMessage(
                APP_NAME, "Sıralı yapıştırma bitti.", QSystemTrayIcon.MessageIcon.Information, 3000
            )

    def _register_seq_hotkey(self, notify: bool = True) -> None:
        try:
            self._seq_hotkey.register(self._settings.seq_hotkey)
        except HotkeyError as exc:
            if notify:
                self._notify(f"Sıralı yapıştırma kısayolu: {exc}")

    # ---- dışa aktarma, yedek, istatistik -----------------------------------------
    def _run_dialog(self, run):
        """Tek seferde bir pencere: popup kapatılır, pencere bitene kadar başkası açılmaz."""
        if self._dialog_open:
            return None
        self._popup.hide()
        self._dialog_open = True
        try:
            return run()
        finally:
            self._dialog_open = False

    def _export(self, item_ids: list | None) -> None:
        """Seçili öğeleri (None ise tüm geçmişi) JSON yedek ya da Markdown olarak yazar."""
        if item_ids is None:
            items = self._repo.all_items()
        else:
            items = [i for i in (self._repo.get(x) for x in item_ids) if i is not None]
        if not items:
            self._notify("Dışa aktarılacak öğe yok.")
            return
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        name = f"{APP_NAME.lower()}-{datetime.now():%Y%m%d-%H%M}"
        chosen = self._run_dialog(
            lambda: QFileDialog.getSaveFileName(
                None,
                f"{APP_NAME} - Dışa aktar ({len(items)} öğe)",
                str(Path(folder) / f"{name}.json"),
                "JSON yedek (*.json);;Markdown belgesi (*.md)",
            )
        )
        if not chosen or not chosen[0]:
            return
        self._export_to(items, chosen[0], markdown="Markdown" in chosen[1])

    def _export_to(self, items, target: str, markdown: bool = False) -> int | None:
        path = Path(target)
        if path.suffix.lower() == ".md":
            markdown = True
        elif path.suffix.lower() != ".json":
            path = path.with_name(path.name + (".md" if markdown else ".json"))
        try:
            self._images.wait()  # arka planda yazılan görseller bitsin
            count = (backup.export_markdown if markdown else backup.export_json)(items, path)
        except OSError as exc:
            self._notify(f"Dışa aktarılamadı: {exc}")
            return None
        self._tray.showMessage(
            APP_NAME, f"{count} öğe dışa aktarıldı: {path}",
            QSystemTrayIcon.MessageIcon.Information, 5000,
        )  # fmt: skip
        return count

    def _import(self) -> None:
        chosen = self._run_dialog(
            lambda: QFileDialog.getOpenFileName(
                None, f"{APP_NAME} - Yedekten içe aktar", "", "JSON yedek (*.json)"
            )
        )
        if chosen and chosen[0]:
            self._import_from(chosen[0])

    def _import_from(self, source: str) -> tuple[int, int] | None:
        try:
            added, skipped = backup.import_json(Path(source), self._repo, self._images)
        except (backup.BackupError, OSError) as exc:
            self._notify(f"İçe aktarılamadı: {exc}")
            return None
        self._scan_code_after_import()
        self._tray.showMessage(
            APP_NAME, f"{added} öğe eklendi, {skipped} öğe zaten vardı.",
            QSystemTrayIcon.MessageIcon.Information, 5000,
        )  # fmt: skip
        return added, skipped

    def _scan_code_after_import(self) -> None:
        if self._popup.isVisible():
            self._popup.refresh()

    def _open_stats(self) -> None:
        self._run_dialog(lambda: StatsDialog(self._repo).exec())

    # ---- görsel düzenleme ---------------------------------------------------
    def _edit_image(self, item_id: int) -> None:
        """Ctrl+E: görseli düzenleyicide aç; sonuç yeni bir görsel olarak kaydedilir."""
        item = self._repo.get(item_id)
        if item is None or item.category is not Category.IMAGE or self._dialog_open:
            return
        image = QImage(item.image_path) if item.image_path else QImage()
        if image.isNull():
            self._popup.show_status("Görsel dosyası okunamadı")
            return
        self._popup.hide()
        self._dialog_open = True
        try:
            dialog = ImageEditorDialog(image)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            result = dialog.result_image
            dialog.deleteLater()  # geri alma yığınındaki görseller bellekte kalmasın
        finally:
            self._dialog_open = False
        if not accepted or result is None:
            return
        # Asıl görsel yerinde kalır; düzenlenen kopya ayrı bir öğe olur.
        self._record_image(result, APP_NAME)
        write_image_to_clipboard(result)
        return_focus(self._prev_window, send_paste=False)
        self._tray.showMessage(
            APP_NAME,
            "Düzenlenen görsel clipboard'a kopyalandı ve geçmişe eklendi.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def _save_image(self, item_id: int) -> None:
        """Ctrl+Shift+S: görseli kullanıcının seçtiği yere PNG dosyası olarak kaydeder."""
        item = self._repo.get(item_id)
        if item is None or item.category is not Category.IMAGE or self._dialog_open:
            return
        if not item.image_path or not Path(item.image_path).is_file():
            self._popup.show_status("Görsel dosyası okunamadı")
            return
        folder = self._save_dir or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        self._popup.hide()
        self._dialog_open = True
        try:
            target, _filter = QFileDialog.getSaveFileName(
                None,
                f"{APP_NAME} - Görseli kaydet",
                str(Path(folder) / default_image_name()),
                "PNG görseli (*.png)",
            )
        finally:
            self._dialog_open = False
        if not target:
            return
        self._save_image_to(item.image_path, target)

    def _save_image_to(self, source: str, target: str) -> Path | None:
        path = Path(target)
        if path.suffix.lower() != ".png":
            path = path.with_name(path.name + ".png")
        try:
            shutil.copyfile(source, path)  # görseller zaten PNG olarak saklanır
        except OSError as exc:
            self._notify(f"Görsel kaydedilemedi: {exc}")
            return None
        self._save_dir = str(path.parent)
        self._tray.showMessage(
            APP_NAME, f"Görsel kaydedildi: {path}", QSystemTrayIcon.MessageIcon.Information, 4000
        )
        return path

    # ---- OCR ----------------------------------------------------------------
    def _ocr_requested(self, item_id: int) -> None:
        """Ctrl+O: seçili görseldeki metni çıkar, Metinler'e ekle ve clipboard'a kopyala."""
        item = self._repo.get(item_id)
        if item is None or item.category is not Category.IMAGE:
            return
        if item.ocr_done:  # daha önce okunmuş; yeniden çalıştırmaya gerek yok
            self._deliver_ocr_text(item.ocr_text or "")
            return
        if not item.image_path:
            self._popup.show_status("Görsel dosyası bulunamadı")
            return
        self._popup.show_status("Görseldeki metin okunuyor…")
        self._ocr.request(item_id, item.image_path, interactive=True)

    def _ocr_finished(self, item_id: int, result: OcrResult, interactive: bool) -> None:
        self._repo.set_ocr(item_id, result.text)  # öğe bu arada silindiyse etkisizdir
        if interactive:
            self._deliver_ocr_text(result.text)
            self._warn_ocr_language()
        elif self._popup.isVisible() and result.text:
            self._popup.refresh()
        self._index_next()

    def _ocr_failed(self, item_id: int, error: Exception, interactive: bool) -> None:
        if isinstance(error, OcrUnavailable):
            self._ocr_disabled = True  # her görselde aynı hatayı tekrarlama
        else:
            self._repo.set_ocr(item_id, None)
        if interactive:
            self._popup.show_status("Metin okunamadı")
            self._notify(str(error))
        elif isinstance(error, OcrUnavailable) and not self._ocr_warned:
            self._ocr_warned = True
            self._notify(f"Otomatik OCR çalışmıyor. {error}")
        self._index_next()

    def _deliver_ocr_text(self, text: str) -> None:
        if not text.strip():
            self._popup.show_status("Bu görselde okunabilir metin bulunamadı")
            return
        category = classify(has_files=False, has_image=False, text=text) or Category.TEXT
        stored = self._record_text(category, text, None, "OCR") is not None
        write_text_to_clipboard(text)
        if not self._popup.isVisible():
            self._notify("Görseldeki metin clipboard'a kopyalandı.")
            return
        if stored:
            self._popup.show_category(category)
            self._popup.show_status("Metin çıkarıldı ve clipboard'a kopyalandı · Enter ile yapıştır")
        else:
            self._popup.show_status(
                "Metin clipboard'a kopyalandı (hassas veri ayarı nedeniyle geçmişe eklenmedi)"
            )
        self._popup.refresh()

    def _warn_ocr_language(self) -> None:
        if self._ocr_warned:
            return
        warning = pipeline.warning(short=True)
        if warning:
            self._ocr_warned = True
            self._notify(warning)

    def _release_ocr(self) -> None:
        if self._ocr.is_busy():
            self._ocr_idle.start()
        else:
            pipeline.release()

    def _index_next(self) -> None:
        """Arka plan indekslemesi: açıksa, okunmamış görselleri birer birer OCR'lar."""
        self._ocr_idle.start()  # her OCR etkinliği boşta kalma sayacını yeniden başlatır
        if not self._settings.ocr_auto or self._ocr_disabled or self._ocr.is_busy():
            return
        item = self._repo.next_pending_ocr()
        if item is None:
            return
        if not item.image_path:
            self._repo.set_ocr(item.id, None)
            QTimer.singleShot(0, self._index_next)
            return
        self._ocr.request(item.id, item.image_path, interactive=False)

    # ---- şablonlar ----------------------------------------------------------
    def _paste_snippet(self, snippet_id: int) -> None:
        snippet = self._snippets.get(snippet_id)
        if snippet is None:
            return
        # {pano}: şablon seçildiği andaki clipboard metni
        current = QGuiApplication.clipboard().text()
        if snippet.is_image:
            image = QImage.fromData(snippet.image)
            if image.isNull():
                self._notify("Şablon görseli okunamadı.")
                return
            write_image_to_clipboard(image)
        else:
            write_text_to_clipboard(expand(snippet.content, clipboard_text=current))
        return_focus(self._prev_window, send_paste=self._settings.auto_paste)
        self._popup.hide()

    def _save_as_snippet(self, item_id: int) -> None:
        item = self._repo.get(item_id)
        if item is None:
            return
        if item.category is Category.IMAGE:
            # Görsel (ör. taranmış imza) çizim alanına gelir; üzerine çizilip kaydedilebilir.
            image = QImage(item.image_path) if item.image_path else QImage()
            if image.isNull():
                self._popup.show_status("Görsel dosyası okunamadı")
                return
            self._run_snippet_editor(initial_image=image)
            return
        if item.category is Category.FILE:
            content = "\n".join(f.path for f in item.files)
        else:
            content = item.text or ""
        if not content.strip():
            return
        self._run_snippet_editor(initial_content=content)

    def _edit_snippet(self, snippet_id: int) -> None:
        snippet = self._snippets.get(snippet_id) if snippet_id else None
        if snippet_id and snippet is None:
            return
        self._run_snippet_editor(snippet=snippet)

    def _run_snippet_editor(
        self, snippet=None, initial_content: str = "", initial_image: QImage | None = None
    ) -> None:
        if self._dialog_open:
            return
        self._popup.hide()
        self._dialog_open = True
        try:
            dialog = SnippetEditDialog(
                self._snippets, snippet, initial_content, initial_image=initial_image
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            dialog.exec()
        finally:
            self._dialog_open = False

    def _open_snippet_manager(self) -> None:
        if self._dialog_open:
            return
        self._dialog_open = True
        try:
            SnippetManagerDialog(self._snippets).exec()
        finally:
            self._dialog_open = False

    # ---- tray eylemleri -----------------------------------------------------
    def _set_paused(self, paused: bool) -> None:
        self._pause.pause() if paused else self._pause.resume()
        self._sync_pause()

    def _pause_for(self, seconds: int) -> None:
        self._pause.pause_for(seconds)
        self._sync_pause()

    def _set_skip_next(self, armed: bool) -> None:
        self._pause.skip_next(armed)
        self._sync_pause()

    def _sync_pause(self) -> None:
        """Tray'i duraklatma durumuyla eşitler; durum kendiliğinden değişecekse o ana kurulur."""
        self._tray.set_status(self._pause.status())
        change = self._pause.next_change()
        if change is None:
            self._pause_timer.stop()
        else:
            self._pause_timer.start(max(0, int((change - time.time()) * 1000)) + 200)

    def _clear_history(self) -> None:
        answer = QMessageBox.question(
            None,
            APP_NAME,
            "Sabitlenmemiş tüm öğeler silinecek. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._repo.clear(include_pinned=False)

    def _open_settings(self, rule_app: str | None = None) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        self._popup.hide()
        dialog = SettingsDialog(
            self._settings,
            lambda: self._repo.clear(include_pinned=True),
            known_apps=self._repo.known_apps(),
            rule_app=rule_app,
        )
        self._settings_dialog = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._apply_settings(dialog.result_settings)
        finally:
            self._settings_dialog = None

    def _apply_settings(self, new: Settings) -> None:
        old, self._settings = self._settings, new
        self._store.save(new)
        if new.hotkey != old.hotkey:
            self._register_hotkey()
        if new.seq_hotkey != old.seq_hotkey:
            self._register_seq_hotkey()
            self._sync_queue()
        try:
            if new.autostart != autostart.is_enabled():
                autostart.set_enabled(new.autostart)
        except OSError as exc:
            self._notify(f"Başlangıç ayarı değiştirilemedi: {exc}")
        if (new.theme, new.animations) != (old.theme, old.animations):
            self._popup.set_theme(new.theme, new.animations)
        for category in Category:
            self._repo.enforce_limit(category, new.limit_for(category))
        self._maintain()
        if new.ocr_auto and not old.ocr_auto:
            self._ocr_disabled = False  # dil paketi bu arada kurulmuş olabilir
        self._index_next()

    def _register_hotkey(self) -> None:
        try:
            self._hotkey.register(self._settings.hotkey)
        except HotkeyError as exc:
            self._notify(f"{exc}\nAyarlardan başka bir kısayol seçebilirsiniz.")

    # ---- bakım --------------------------------------------------------------
    def _maintain(self) -> None:
        removed = self._repo.purge_expired()
        if self._settings.retention_enabled:
            removed += self._repo.purge_older_than(self._settings.retention_days)
        popup = getattr(self, "_popup", None)
        if removed and popup is not None and popup.isVisible():
            popup.refresh()

    def _notify(self, message: str) -> None:
        self._tray.showMessage(APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def quit(self) -> None:
        self._hotkey.unregister()
        self._seq_hotkey.unregister()
        self._links.wait()
        self._listener.stop()
        self._tray.hide()
        self._images.wait()
        self._ocr.wait()
        self._conn.close()
        self._app.quit()
