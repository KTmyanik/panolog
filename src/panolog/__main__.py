from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_NAME, paths, winapi
from .settings import autostart


def main() -> int:
    if "--self-test" in sys.argv:  # paket doğrulaması; çalışan kopyaya ve verilere dokunmaz
        from .selftest import run

        rest = sys.argv[sys.argv.index("--self-test") + 1 :]
        return run(rest[0] if rest else None)

    if "--ocr" in sys.argv:  # tek görseli oku, metni dosyaya yaz; geçmişe ve clipboard'a dokunmaz
        from .selftest import ocr_file

        rest = sys.argv[sys.argv.index("--ocr") + 1 :]
        if len(rest) < 2:
            return 2
        return ocr_file(rest[0], rest[1])

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if not winapi.acquire_single_instance("Local\\Panolog.SingleInstance"):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} zaten çalışıyor (tray ikonuna bakın).")
        return 0
    # Eski addaki sürüm (Clipboarder) aynı veriyi kullanır; ikisi birlikte çalışmamalı. Bu
    # kilit alındığı sürece eski sürüm de "zaten çalışıyor" diyerek açılmaz.
    if not winapi.acquire_single_instance(f"Local\\{paths.LEGACY_NAME}.SingleInstance"):
        QMessageBox.information(
            None,
            APP_NAME,
            f"Eski sürüm ({paths.LEGACY_NAME}) çalışıyor. Önce onu tray menüsünden kapatın, "
            f"sonra {APP_NAME}'u yeniden başlatın; geçmişiniz otomatik taşınacak.",
        )
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "Sistem tepsisi kullanılamıyor.")
        return 1
    try:
        paths.migrate_legacy_data()
        autostart.migrate_legacy()
    except paths.LegacyMigrationError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    from .app import Controller

    controller = Controller(app)  # noqa: F841 (referans yaşamalı)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
