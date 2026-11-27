"""Bileşenleri birbirine bağlayan uygulama denetleyicisi."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QSystemTrayIcon

from . import APP_NAME, paths, winapi
from .classifier import Category, classify
from .hotkey import GlobalHotkey, HotkeyError
from .monitor import ClipboardListener, read_clipboard
from .ocr import OcrResult, OcrService, OcrUnavailable, pipeline
from .paste import return_focus, write_text_to_clipboard, write_to_clipboard
from .sensitive import evaluate
from .settings import Settings, SettingsStore, autostart
from .snippets import SnippetRepository, expand
from .storage import FileRef, Repository, connect
from .storage.images import ImageStore, hash_image
from .storage.repository import files_hash, text_hash
from .ui.popup import Popup
from .ui.settings_dialog import SettingsDialog
from .ui.snippet_dialogs import SnippetEditDialog, SnippetManagerDialog
from .ui.tray import Tray

_MAINTENANCE_MS = 30_000
_MAX_HTML_CHARS = 2_000_000
_OCR_IDLE_RELEASE_MS = 120_000


class Controller(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._paused = False
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
        self._popup.pasteRequested.connect(self._paste)
        self._popup.snippetRequested.connect(self._paste_snippet)
        self._popup.saveAsSnippetRequested.connect(self._save_as_snippet)
        self._popup.editSnippetRequested.connect(self._edit_snippet)
        self._popup.ocrRequested.connect(self._ocr_requested)

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
        self._tray.clearRequested.connect(self._clear_history)
        self._tray.settingsRequested.connect(self._open_settings)
        self._tray.snippetsRequested.connect(self._open_snippet_manager)
        self._tray.quitRequested.connect(self.quit)
        self._tray.show()

        self._listener = ClipboardListener()
        self._listener.changed.connect(self._on_clipboard_changed)

        self._hotkey = GlobalHotkey()
        self._hotkey.activated.connect(self.toggle_popup)
        self._register_hotkey()

        self._timer = QTimer(self)
        self._timer.setInterval(_MAINTENANCE_MS)
        self._timer.timeout.connect(self._maintain)
        self._timer.start()
        QTimer.singleShot(2000, self._index_next)

    # ---- clipboard izleme ---------------------------------------------------
    def _on_clipboard_changed(self, source_app: str | None) -> None:
        if self._paused:
            return
        payload = read_clipboard()
        if payload.internal or payload.private or self._settings.is_excluded(source_app):
            return
        category = classify(
            has_files=bool(payload.files), has_image=payload.image is not None, text=payload.text
        )
        if category is None:
            return
        limit = self._settings.limit_for(category)
        if category is Category.FILE:
            self._repo.add_item(
                category,
                files_hash(payload.files),
                files=[FileRef.from_path(p) for p in payload.files],
                source_app=source_app,
                limit=limit,
            )
        elif category is Category.IMAGE:
            image = payload.image
            digest = hash_image(image)
            full, thumb = self._images.save(image, digest)
            item, _created = self._repo.add_item(
                category,
                digest,
                image_path=str(full),
                thumb_path=str(thumb),
                width=image.width(),
                height=image.height(),
                source_app=source_app,
                limit=limit,
            )
            if self._settings.ocr_auto and not item.ocr_done and not self._ocr_disabled:
                # Tam boy PNG henüz diske yazılıyor olabilir; görselin kendisi verilir.
                self._ocr.request(item.id, image.copy(), interactive=False)
        else:
            html = payload.html if category is Category.TEXT else None
            if not self._record_text(category, payload.text or "", html, source_app):
                return
        if self._popup.isVisible():
            self._popup.refresh()

    def _record_text(
        self, category: Category, text: str, html: str | None, source_app: str | None
    ) -> bool:
        """Metni/linki hassas veri ayarına göre geçmişe ekler. Kaydedildiyse True."""
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
            return False
        ttl = decision.ttl_seconds
        self._repo.add_item(
            category,
            text_hash(text),
            text=text,
            html=html,
            source_app=source_app,
            sensitive=decision.sensitive,
            masked_text=decision.masked_text,
            expires_at=time.time() + ttl if ttl else None,
            limit=self._settings.limit_for(category),
        )
        if ttl:  # süre dolar dolmaz sil; periyodik bakımı bekleme
            QTimer.singleShot(int(ttl * 1000) + 250, self._maintain)
        return True

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
        stored = self._record_text(category, text, None, "OCR")
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
        write_text_to_clipboard(expand(snippet.content, clipboard_text=current))
        return_focus(self._prev_window, send_paste=self._settings.auto_paste)
        self._popup.hide()

    def _save_as_snippet(self, item_id: int) -> None:
        item = self._repo.get(item_id)
        if item is None:
            return
        if item.category is Category.FILE:
            content = "\n".join(f.path for f in item.files)
        else:
            content = item.text or ""
        if not content.strip():
            self._popup.hide()
            self._notify("Görseller şablon olarak kaydedilemez; şablonlar yalnızca metindir.")
            return
        self._run_snippet_editor(initial_content=content)

    def _edit_snippet(self, snippet_id: int) -> None:
        snippet = self._snippets.get(snippet_id) if snippet_id else None
        if snippet_id and snippet is None:
            return
        self._run_snippet_editor(snippet=snippet)

    def _run_snippet_editor(self, snippet=None, initial_content: str = "") -> None:
        if self._dialog_open:
            return
        self._popup.hide()
        self._dialog_open = True
        try:
            dialog = SnippetEditDialog(self._snippets, snippet, initial_content)
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
        self._paused = paused

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

    def _open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self._settings, lambda: self._repo.clear(include_pinned=True))
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
        try:
            if new.autostart != autostart.is_enabled():
                autostart.set_enabled(new.autostart)
        except OSError as exc:
            self._notify(f"Başlangıç ayarı değiştirilemedi: {exc}")
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
        self._listener.stop()
        self._tray.hide()
        self._images.wait()
        self._ocr.wait()
        self._conn.close()
        self._app.quit()
