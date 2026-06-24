"""Abstract DB lineage provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LineageResult:
    nodes: list[dict]   # each: {name: str, type: str, depth: int}
    edges: list[dict]   # each: {source: str, target: str}
    cycles: list[str]   # object names involved in detected cycles


class DBLineageProvider(ABC):
    """Implement this to add a new database lineage source.
    Register the implementation in db_lineage/registry.py — that is the only file to change.
    """

    @abstractmethod
    def get_lineage(self, objects: list[str], direction: str, depth: int) -> LineageResult:
        """Return upstream/downstream lineage for the given objects.

        direction: "upstream" | "downstream" | "both"
        depth: max BFS hops
        """
