from __future__ import annotations

import json
from pathlib import Path

from ..models import Item


class DirectorySink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    def write_item(self, item: Item) -> None:
        out = self.path / f"{item.id}.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(item.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out)

    def close(self) -> None:
        pass
