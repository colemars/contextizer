from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TextIO

from ..models import Item

log = logging.getLogger(__name__)


class JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO | None = None

    def _open(self) -> TextIO:
        if self._fh is None:
            self._fh = self.path.open("a", encoding="utf-8")
        return self._fh

    def write_item(self, item: Item) -> None:
        fh = self._open()
        fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
