"""Normalized, closed semiconductor terminology graph."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from config import DATA_DIR, TERMINOLOGY_FILE

ALIASES_FILE = DATA_DIR / "entity_aliases.json"


def _node_id(kind: str, name: str) -> str:
    digest = hashlib.sha256(f"{kind}\x1f{name}".encode()).hexdigest()[:16]
    return f"{kind}_{digest}"


def _term_aliases(name: str, english: str) -> list[str]:
    aliases = {name, english}
    for value in (name, english):
        aliases.update(part.strip() for part in re.split(r"\s+/\s+", value) if part.strip())
        parenthetical = re.match(r"^(.+?)\s*[（(]([^）)]+)[）)]$", value)
        if parenthetical:
            aliases.update(part.strip() for part in parenthetical.groups())
    return sorted(alias for alias in aliases if alias)


class KnowledgeGraph:
    """Build term/company/concept nodes and typed, bidirectionally closed edges."""

    def __init__(
        self,
        terminology_path: Path = Path(TERMINOLOGY_FILE),
        aliases_path: Path = ALIASES_FILE,
    ):
        terminology = json.loads(terminology_path.read_text(encoding="utf-8"))["terms"]
        aliases = json.loads(aliases_path.read_text(encoding="utf-8"))["companies"]
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.alias_index: dict[str, str] = {}
        self.alias_collisions: dict[str, list[str]] = {}
        self._edge_keys: set[tuple[str, str, str]] = set()
        self._company_variants = {
            canonical: [canonical, *variants] for canonical, variants in aliases.items()
        }
        self._company_aliases = {
            alias.casefold(): canonical
            for canonical, variants in self._company_variants.items()
            for alias in variants
        }
        self._build(terminology)

    def _register_node(self, kind: str, name: str, aliases: list[str] | None = None) -> str:
        node_id = _node_id(kind, name)
        values = sorted(set(aliases or [name]))
        self.nodes.setdefault(
            node_id, {"id": node_id, "type": kind, "name": name, "aliases": values}
        )
        for alias in values:
            key = alias.casefold()
            existing = self.alias_index.get(key)
            if existing and existing != node_id:
                self.alias_collisions.setdefault(alias, sorted({existing, node_id}))
            else:
                self.alias_index[key] = node_id
        return node_id

    def _add_edge(
        self, source: str, target: str, relation: str, *, inferred_inverse: bool = False
    ) -> None:
        key = (source, target, relation)
        if source == target or key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            {
                "source": source,
                "target": target,
                "type": relation,
                "inferred_inverse": inferred_inverse,
            }
        )

    def _build(self, terms: dict) -> None:
        for name, info in terms.items():
            term_id = self._register_node(
                "term", name, _term_aliases(name, str(info.get("name_en") or ""))
            )
            self.nodes[term_id]["generation"] = info.get("generation", "")

        for name, info in terms.items():
            source = self.alias_index[name.casefold()]
            for related in info.get("related_terms", []):
                target = self.alias_index.get(str(related).casefold())
                if target is None:
                    target = self._register_node("concept", str(related))
                self._add_edge(source, target, "related_to")
                self._add_edge(target, source, "related_to", inferred_inverse=True)

            for raw_company in info.get("related_companies", []):
                canonical = self._company_aliases.get(str(raw_company).casefold(), raw_company)
                company_aliases = self._company_variants.get(canonical, [canonical])
                company = self._register_node("company", canonical, company_aliases)
                self._add_edge(source, company, "associated_with")
                self._add_edge(company, source, "associated_with", inferred_inverse=True)

    def resolve(self, name_or_alias: str) -> dict | None:
        node_id = self.alias_index.get(name_or_alias.casefold())
        return self.nodes.get(node_id) if node_id else None

    def neighbors(self, name_or_alias: str, relation: str | None = None) -> list[dict]:
        node = self.resolve(name_or_alias)
        if not node:
            return []
        targets = [
            edge["target"]
            for edge in self.edges
            if edge["source"] == node["id"] and (relation is None or edge["type"] == relation)
        ]
        return [self.nodes[target] for target in targets]

    def audit(self) -> dict:
        missing_endpoints = [
            edge
            for edge in self.edges
            if edge["source"] not in self.nodes or edge["target"] not in self.nodes
        ]
        missing_inverse = [
            edge
            for edge in self.edges
            if (edge["target"], edge["source"], edge["type"]) not in self._edge_keys
        ]
        type_counts: dict[str, int] = {}
        for node in self.nodes.values():
            type_counts[node["type"]] = type_counts.get(node["type"], 0) + 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_types": type_counts,
            "alias_collisions": self.alias_collisions,
            "missing_endpoints": missing_endpoints,
            "missing_inverse_edges": missing_inverse,
        }


@lru_cache(maxsize=1)
def get_knowledge_graph() -> KnowledgeGraph:
    return KnowledgeGraph()
