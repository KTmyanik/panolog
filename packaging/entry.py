"""PyInstaller giriş noktası (paket göreli içe aktarma kullandığı için ayrı bir betik gerekir)."""
import sys

from panolog.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
