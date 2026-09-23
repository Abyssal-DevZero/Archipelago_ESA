"""Parses glitchlesslogic.ini into a node graph at import time.

The ini is the specification for ESA's logic. Every edge in it says what it
takes to get from one node to the next

This module is pure data 
Token meanings live in rules.py, because only that module needs rule_builder.
"""

from __future__ import annotations

import configparser
import hashlib
import pkgutil
from dataclasses import dataclass

from .data import (
    ITEMDATA_INDEX,
    KEY_INDEX,
    LOCATION_NAME_TO_ID,
    MONITOR_INDEX,
)

INI_RESOURCE = "data/glitchlesslogic.ini"
DROPPED_TOKENS = frozenset({"poweroff", "growthoff", "growthon", "mender"})

# Node 121 "Derelict 5" is an orphan
SKIPPED_NODES = frozenset({"121"})
# classa is still unmapped
FREE_TOKENS = frozenset({"classa"})

FLAG_TOKEN_EVENTS = {
    "switch": "Propeller Room Switch",
}
# Tokens a node grants by being reached (the ini writes them as `<token>="1"` on the node, exactly like teleportfind)
FLAG_TOKEN_LOCATIONS = {
    "password": "Password Monitor",
}

TELEPORT_HUB_REGION = "Teleport Network"

# The ini's item index is also its node id. Location names do not always match item names ("The Bike" lives at "Bike Spot"), so the mapping is explicit and checked against data.py at import.
# TODO: Index 39 (CROWN) is not implemented yet as the crown has some... unique coding attached to it
ITEM_INDEX_TO_LOCATION = {
    0: "Jump Booster Spot",
    1: "Hookshot Spot",
    2: "Teleport Access Spot",
    3: "Propeller Spot",
    4: "Charge Shot Spot",
    5: "Dash Booster H Spot",
    6: "Heat-Resistant suit Spot",
    7: "Gold Keycard Spot",
    8: "Dash Booster V Spot",
    9: "Rough Map Spot",
    10: "Triple Shot Spot",
    11: "Plasma Shield Spot",
    12: "Supercharge Module Spot",
    13: "Dash Booster X Spot",
    14: "Bike Spot",
    15: "Health Pack Beetle Spot",
    16: "Health Pack SandTop Spot",
    17: "Health Pack FireLow Spot",
    18: "Health Pack Temple Spot",
    19: "Health Pack FireHigh Spot",
    20: "Health Pack SandBottom Spot",
    21: "Health Pack Ship Spot",
    22: "Health Pack Water Spot",
    23: "Diskette Water Spot",
    24: "Diskette Depthsmaze Spot",
    25: "Diskette Caves Spot",
    26: "Diskette Jungle Spot",
    27: "Diskette TempleLeft Spot",
    28: "Diskette FireLava Spot",
    29: "Diskette TempleTall Spot",
    30: "Diskette Security Spot",
    31: "Diskette SandMid Spot",
    32: "Diskette SandBot Spot",
    33: "Diskette FireTop Spot",
    34: "Diskette Ship Spot",
    35: "Key Mwyah Spot",
    36: "Key Fire Spot",
    37: "Key Caves Spot",
    38: "Key Temple Spot",
    40: "Power Monitor",
    41: "Gate Alpha Monitor",
    42: "Gate Beta Monitor",
    43: "Gate Gamma Monitor",
    44: "Gate Delta Monitor",
    45: "Pillar 1 Monitor",
    46: "Pillar 2 Monitor",
    47: "Pillar 3 Monitor",
    48: "Pillar 4 Monitor",
}


@dataclass(frozen=True)
class Node:
    """One node of the ini graph, which becomes one AP Region."""

    id: str
    name: str
    region: str
    item_index: int | None
    location: str | None


@dataclass(frozen=True)
class Edge:
    """One directed connection, which becomes one AP Entrance.

    ``terms`` is a sum of products: the edge is passable if any one term has all its tokens satisfied. An empty tuple of terms never happens, a single empty term means the edge is free.
    """

    source: str
    target: str
    name: str
    terms: tuple[frozenset[str], ...]

    @property
    def is_free(self) -> bool:
        return any(not term for term in self.terms)


def _read_ini() -> str:
    raw = pkgutil.get_data(__name__, INI_RESOURCE)
    if raw is None:
        raise FileNotFoundError(
            f"{INI_RESOURCE} is missing from the ESA apworld. The logic graph is parsed from it at import time, so the world cannot load without it."
        )
    return raw.decode("utf-8", errors="ignore")


def _parse_expression(expression: str) -> tuple[frozenset[str], ...]:
    """Turn 'jump&hook|vdash' into ((jump, hook), (vdash,)).
    '&' binds tighter than '|' and there is no grouping syntax, so every expression is a flat sum of products. Products containing a dropped token are removed, 'nothing' becomes the empty product, meaning free passage.
    """
    terms: list[frozenset[str]] = []
    for product in expression.split("|"):
        tokens = {token.strip() for token in product.split("&") if token.strip()}
        if tokens & DROPPED_TOKENS:
            continue
        tokens.discard("nothing")
        tokens -= FREE_TOKENS
        term = frozenset(tokens)
        if term not in terms:
            terms.append(term)
    return tuple(terms)


def _region_name(node_id: str, name: str) -> str:
    """Region names must be unique and stable; ini names are neither on their own."""
    return f"{name} ({node_id})"


class _Graph:
    def __init__(self) -> None:
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read_string(_read_ini())

        sections = {
            section: {key: value.strip('"') for key, value in parser[section].items()}
            for section in parser.sections()
        }
        main = sections.pop("main", {})
        for skipped in SKIPPED_NODES:
            sections.pop(skipped, None)

        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.teleport_pads: dict[str, str] = {}
        self.teleport_finds: dict[str, str] = {}
        self.flag_grants: dict[str, str] = {}

        self._build_nodes(sections)
        self._build_edges(sections)
        self._build_doors(sections)
        self._build_teleports(sections)

        self.start_node = main.get("start", "65")
        if self.start_node not in self.nodes:
            raise ValueError(f"start node {self.start_node} is not in the logic graph")
        self.start_region = self.nodes[self.start_node].region

        self.fingerprint = self._fingerprint()

    def _build_nodes(self, sections: dict[str, dict[str, str]]) -> None:
        for node_id, fields in sections.items():
            item = fields.get("item")
            item_index = int(item) if item is not None else None
            name = fields.get("name", f"Node {node_id}")
            location = ITEM_INDEX_TO_LOCATION.get(item_index) if item_index is not None else None

            flag_location = self._scan_flags(node_id, fields)
            if flag_location is not None:
                if location is not None:
                    raise ValueError(
                        f"node {node_id} holds both {location!r} and {flag_location!r}; a node holds one location")
                location = flag_location

            self.nodes[node_id] = Node(
                id=node_id,
                name=name,
                region=_region_name(node_id, name),
                item_index=item_index,
                location=location,
            )

    def _scan_flags(self, node_id: str, fields: dict[str, str]) -> str | None:
        """Record every flag token this node grants, and return the one that is a real location, if any."""
        found = None
        for token in (*FLAG_TOKEN_LOCATIONS, *FLAG_TOKEN_EVENTS):
            if fields.get(token) != "1":
                continue
            if token in self.flag_grants:
                raise ValueError(
                    f"token {token!r} is granted by nodes {self.flag_grants[token]} and {node_id}, one granting node per token")
            self.flag_grants[token] = node_id
            if token not in FLAG_TOKEN_LOCATIONS:
                continue
            if found is not None:
                raise ValueError(f"node {node_id} grants more than one flag location")
            found = FLAG_TOKEN_LOCATIONS[token]
        return found

    def _add_edge(self, source: str, target: str, terms: tuple[frozenset[str], ...], suffix: str = "") -> None:
        if not terms:
            return
        name = f"{self.nodes[source].region} -> {self.nodes[target].region}{suffix}"
        self.edges.append(Edge(source=source, target=target, name=name, terms=terms))

    def _build_edges(self, sections: dict[str, dict[str, str]]) -> None:
        for node_id, fields in sections.items():
            for target in fields.get("nodelist", "").split(","):
                target = target.strip()
                if not target or target not in self.nodes:
                    continue
                self._add_edge(node_id, target, _parse_expression(fields.get(target, "nothing")))

    def _build_doors(self, sections: dict[str, dict[str, str]]) -> None:
        doors: dict[str, dict[str, str]] = {}
        for node_id, fields in sections.items():
            if "entrance" in fields and "side" in fields:
                doors.setdefault(fields["entrance"], {})[fields["side"]] = node_id

        free = (frozenset(),)
        for entrance_id, sides in sorted(doors.items()):
            if len(sides) != 2:
                continue
            near, far = sides["0"], sides["1"]
            self._add_edge(near, far, free, suffix=" (door)")
            self._add_edge(far, near, free, suffix=" (door)")

    def _build_teleports(self, sections: dict[str, dict[str, str]]) -> None:
        for node_id, fields in sections.items():
            if "teleport" in fields:
                self.teleport_pads[fields["teleport"]] = node_id
            if "teleportfind" in fields:
                self.teleport_finds[fields["teleportfind"]] = node_id

    def _fingerprint(self) -> str:
        """Hash of the parsed graph, so a test can catch the ini changing under us."""
        digest = hashlib.sha256()
        for node in sorted(self.nodes.values(), key=lambda n: int(n.id)):
            digest.update(f"{node.id}|{node.name}|{node.item_index}\n".encode())
        for edge in sorted(self.edges, key=lambda e: e.name):
            terms = ";".join(sorted("&".join(sorted(term)) for term in edge.terms))
            digest.update(f"{edge.source}>{edge.target}|{terms}\n".encode())
        for token, node_id in sorted(self.flag_grants.items()):
            digest.update(f"grant {token}>{node_id}\n".encode())
        return digest.hexdigest()[:16]


_GRAPH = _Graph()

NODES: dict[str, Node] = _GRAPH.nodes
EDGES: list[Edge] = _GRAPH.edges
REGION_NAMES: list[str] = [node.region for node in NODES.values()]
START_NODE: str = _GRAPH.start_node
START_REGION: str = _GRAPH.start_region
TELEPORT_PADS: dict[str, str] = _GRAPH.teleport_pads
TELEPORT_FINDS: dict[str, str] = _GRAPH.teleport_finds
FLAG_GRANTS: dict[str, str] = _GRAPH.flag_grants
GRAPH_FINGERPRINT: str = _GRAPH.fingerprint

# node id -> AP location name, for every node holding a randomized item
ITEM_NODES: dict[str, str] = {
    node.id: node.location for node in NODES.values() if node.location is not None
}

# teleporter id -> the event item granted by reaching its find node
TELEPORT_EVENTS: dict[str, str] = {
    pad_id: f"Teleporter {pad_id} Found" for pad_id in sorted(TELEPORT_PADS, key=int)
}

ALL_TOKENS: frozenset[str] = frozenset(
    token for edge in EDGES for term in edge.terms for token in term
)


def _validate() -> None:
    """Fail at import rather than halfway through generation."""
    mapped = set(ITEM_INDEX_TO_LOCATION.values()) | set(FLAG_TOKEN_LOCATIONS.values())

    unknown = mapped - set(LOCATION_NAME_TO_ID)
    if unknown:
        raise ValueError(f"logic maps locations that data.py does not define: {sorted(unknown)}")

    unmapped = set(LOCATION_NAME_TO_ID) - mapped
    if unmapped:
        raise ValueError(f"data.py defines locations no ini node holds: {sorted(unmapped)}")

    flag_tokens = set(FLAG_TOKEN_LOCATIONS) | set(FLAG_TOKEN_EVENTS)

    overlap = set(FLAG_TOKEN_LOCATIONS) & set(FLAG_TOKEN_EVENTS)
    if overlap:
        raise ValueError(f"tokens cannot be a location and an event at once: {sorted(overlap)}")

    both = (FREE_TOKENS | DROPPED_TOKENS) & flag_tokens
    if both:
        raise ValueError(f"tokens cannot be free and granted at once: {sorted(both)}")

    ungranted = flag_tokens - set(FLAG_GRANTS)
    if ungranted:
        raise ValueError(f"no ini node grants these flag tokens: {sorted(ungranted)}")

    unused = flag_tokens - ALL_TOKENS
    if unused:
        raise ValueError(f"flag tokens that gate no edge, so their item would be dead weight: {sorted(unused)}")

    known_indices = set(ITEMDATA_INDEX.values()) | set(KEY_INDEX.values()) | set(MONITOR_INDEX.values())
    stray = set(ITEM_INDEX_TO_LOCATION) - known_indices
    if stray:
        raise ValueError(f"logic maps item indices data.py does not know: {sorted(stray)}")

    placed = set(ITEM_NODES.values())
    missing = mapped - placed
    if missing:
        raise ValueError(f"locations with no node to live in: {sorted(missing)}")

    orphan_pads = set(TELEPORT_PADS) - set(TELEPORT_FINDS)
    if orphan_pads:
        raise ValueError(f"teleporters that can never be found: {sorted(orphan_pads)}")
_validate()
