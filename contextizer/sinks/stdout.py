from __future__ import annotations

import json
import sys

from ..models import Digest, Item


class StdoutSink:
    def write_item(self, item: Item) -> None:
        sys.stdout.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def write_digest(self, digest: Digest) -> None:
        sys.stdout.write(digest.rendered_markdown)
        if not digest.rendered_markdown.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    def close(self) -> None:
        pass
