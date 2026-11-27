from __future__ import annotations

import json

from ..storage.repository import Repository
from .schema import Settings

_KEY = "app"


class SettingsStore:
    """Ayarları DB'deki settings tablosunda tek bir JSON kaydı olarak tutar."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def load(self) -> Settings:
        raw = self._repo.get_setting(_KEY)
        if not raw:
            return Settings()
        try:
            data = json.loads(raw)
        except ValueError:
            return Settings()
        return Settings.from_dict(data) if isinstance(data, dict) else Settings()

    def save(self, settings: Settings) -> None:
        self._repo.set_setting(_KEY, json.dumps(settings.to_dict(), ensure_ascii=False))
