from __future__ import annotations

from ..collector.state import SeenStore


class DigestedStore(SeenStore):
    """Tracks item IDs already included in a digest. Used by `--unseen` mode."""
