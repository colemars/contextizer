from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..models import Item

log = logging.getLogger(__name__)


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: dict[str, str] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._seen = {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not load seen-items state %s: %s", self.path, e)
            self._seen = {}

    def contains(self, item: Item) -> bool:
        return item.id in self._seen

    def add(self, item: Item) -> None:
        if item.id not in self._seen:
            self._seen[item.id] = datetime.now(timezone.utc).isoformat()
            self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._seen, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False

    def __len__(self) -> int:
        return len(self._seen)
