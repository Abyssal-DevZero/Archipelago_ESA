"""Parses glitchlesslogic.ini into a node graph at import time.
The ini is the specification for ESA's logic. Every edge in it says what it takes to get from one node to the next
"""

from __future__ import annotations

import configparser
import hashlib
import pkgutil
from dataclasses import dataclass
from itertools import product

from .data import (
    ITEMDATA_INDEX,
    KEY_INDEX,
    LOCATION_FLAG,
    LOCATION_NAME_TO_ID,
    MAZE_PILLAR,
    MONITOR_INDEX,
    SIGN_LOCATIONS,
)

INI_RESOURCE = "data/glitchlesslogic.ini"
DROPPED_TOKENS = frozenset({"poweroff"})

# Node 121 "Derelict 5" is an orphan
SKIPPED_NODES = frozenset({"121"})
FREE_TOKENS: frozenset[str] = frozenset({"growthon", "mender"})
TOKEN_ALIASES = {"growthoff": "tpaccess"} 

FLAG_TOKEN_EVENTS = {
    "switch": "Propeller Room Switch",
    "classa": "Class A Unlocked",
}
# Tokens a node grants by being reached (the ini writes them as `<token>="1"` on the node, exactly like teleportfind)
FLAG_TOKEN_LOCATIONS = {
    "password": "Password Monitor",
}

TELEPORT_HUB_REGION = "Teleport Network"
JUNGLE_TELEPORT_PAD = "1"           # "Jungle Start tp": the [Jungle Teleport] of the sign notes

# Edges where the ini gets adjusted for Archipelago: (source, target) -> replacement expression.
EDGE_OVERRIDES = {
    # Jungle 1 -> Deep Jungle tp. ini: "jump&hook|vdash&charge" (This change attempts at moving the teleportaccess outside of the jungle, making it much harder to softlock oneself out of the jungle and temple)
    ("114", "49"): "jump&hook|vdash&charge&tpaccess&poweron&hdash",
}
# EYE SIGN LOGIC (Thanks to Greendjssa)
SIGN_LOGIC: dict[str, tuple[str, ...]] = {
    "Sign Location 1 (03-08)": ("jump&hook&charge", "vdash&charge"),                 # @03-08, middle of the room
    "Sign Location 2 (21-14)": ("jump&hook&charge", "vdash&charge"),                 # @21-14, in front of the statue
    "Sign Location 3 (Planet Surface)": ("poweron&gold&triple&charge&vdash&hdash&xdash",),    # planet surface, after the gauntlet
    "Sign Location 4 (07-11)": ("vdash&hdash", "vdash&charge"),                      # @07-11, under the warp
    "Sign Location 5 (11-06)": ("gold&jump", "vdash"),                               # @11-06, above the Dash Booster V spot
    "Sign Location 6 (12-18)": ("vdash&gold", "vdash&charge&jump", "vdash&charge&hook",
                        "vdash&bike&jump&hook", "xv"),                       # @12-18, blue flower
    "Sign Location 7 (15-22)": ("gates&vdash&charge&hook", "gates&vdash&charge&hdash&gold",
                        "gates&vdash&charge&hdash&jump"),                    # @15-22, on top of the boss (all four gates)
    # Sign Location 8: the game enters it itself, no check
    "Sign Location 9 (Death-Laser Room)": ("xv&poweron&keys&map&charge&heatsuit",),             # death-laser room, the crystal
    "Sign Location 10 (24-20)": ("hdash&poweron&charge&jump&hook&password",          # @24-20, round window
                         "hdash&poweron&charge&vdash&jump&password",
                         "hdash&poweron&charge&vdash&triple&password",
                         "hdash&poweron&charge&vdash&gold",
                         "hdash&poweron&xv&password",
                         "hdash&poweron&xv&gold",
                         "xv&charge",                                        # secret room, lower path
                         "jungletp&vdash&poweron",                           # secret room, through the temple
                         "jungletp&jump&hook&hdash&poweron"),
    "Sign Location 11 (26-17)": ("charge&vdash",),                                   # @26-17, the missing Supercharge Module
    "Sign Location 12 (18-01)": ("jungletp&xv",),                                    # @18-01, where you met the Eagle
    "Sign Location 13 (28-08)": ("hook&vdash", "hook&jump", "xv"),                   # @28-08, end of the hookshot course
    "Sign Location 14 (25-00)": ("jungletp&poweron&hook&jump",                       # @25-00, floating block (no way out without hdash)
                         "jungletp&poweron&hook&vdash",
                         "xv"),
}

# MWYA Pillar
MAZE_PILLAR_LOGIC: tuple[str, ...] = ("charge&jump", "charge&vdash")

# The logic ini's item index is also its node id. Location names do not always match item names ("The Bike" lives at "Bike Spot"), so the mapping is explicit and checked against data.py at import.
# TODO: Index 39 (CROWN) is not implemented yet as the crown has some... unique coding attached to it
ITEM_INDEX_TO_LOCATION = {
    0: "Jump Booster Spot (13-13)",
    1: "Hookshot Spot (26-10)",
    2: "Teleport Access Spot (11-19)",
    3: "Propeller Spot (01-20)",
    4: "Charge Shot Spot (00-08)",
    5: "Dash Booster H Spot (05-03)",
    6: "Heat-Resistant suit Spot (25-08)",
    7: "Gold Keycard Spot (29-19)",
    8: "Dash Booster V Spot (11-07)",
    9: "Rough Map Spot (19-12)",
    10: "Triple Shot Spot (15-04)",
    11: "Plasma Shield Spot (03-15)",
    12: "Supercharge Module Spot (28-15)",
    13: "Dash Booster X Spot (22-12)",
    14: "Bike Spot",
    15: "Health Pack Beetle Spot (15-12)",
    16: "Health Pack SandTop Spot (11-13)",
    17: "Health Pack FireLow Spot (26-14)",
    18: "Health Pack Temple Spot (23-04)",
    19: "Health Pack FireHigh Spot (26-12)",
    20: "Health Pack SandBottom Spot (06-16)",
    21: "Health Pack Ship Spot (31-24)",
    22: "Health Pack Water Spot (02-13)",
    23: "Diskette Water Spot (04-13)",
    24: "Diskette Depthsmaze Spot (17-16)",
    25: "Diskette Caves Spot (18-10)",
    26: "Diskette Jungle Spot (17-00)",
    27: "Diskette TempleLeft Spot (23-07)",
    28: "Diskette FireLava Spot (25-15)",
    29: "Diskette TempleTall Spot (29-03)",
    30: "Diskette Security Spot (19-18)",
    31: "Diskette SandMid Spot (10-14)",
    32: "Diskette SandBot Spot (07-18)",
    33: "Diskette FireTop Spot (23-09)",
    34: "Diskette Ship Spot (25-19)",
    35: "Key Mwyah Spot",
    36: "Key Fire Spot (19-13)",
    37: "Key Caves Spot (15-09)",
    38: "Key Temple Spot (22-02)",
    40: "Power Monitor (19-17)",
    41: "Gate Alpha Monitor (11-19)",
    42: "Gate Beta Monitor (19-19)",
    43: "Gate Gamma Monitor (11-20)",
    44: "Gate Delta Monitor (19-20)",
    45: "Pillar 1 Monitor (14-08)",
    46: "Pillar 2 Monitor (20-10)",
    47: "Pillar 3 Monitor (12-12)",
    48: "Pillar 4 Monitor (17-08)",
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
    
def _minimal(terms) -> tuple[frozenset[str], ...]:
    """Drop every term a smaller one already covers, in a deterministic order."""
    terms = set(terms)
    minimal = [t for t in terms if not any(other < t for other in terms)]  # absorption
    return tuple(sorted(minimal, key=lambda t: (len(t), sorted(t))))
    
def _parse_expression(expression: str) -> tuple[frozenset[str], ...]:
    """'|' binds tighter than '&': 'jump|hook&vdash|xv' == (jump|hook) & (vdash|xv).
    Returned as a sum of products. () means impassable, (frozenset(),) means free."""
    clauses: list[frozenset[str]] = []
    for raw_clause in expression.split("&"):
        options = {token.strip() for token in raw_clause.split("|") if token.strip()}
        options = {TOKEN_ALIASES.get(token, token) for token in options}
        if "nothing" in options or options & FREE_TOKENS:
            continue                      # clause always satisfied
        options -= DROPPED_TOKENS         # dropped tokens count as never true
        if not options:
            return ()                     # unsatisfiable clause -> no edge
        clauses.append(frozenset(options))
    if not clauses:
        return (frozenset(),)
    return _minimal(frozenset(combo) for combo in product(*clauses))
    
def _parse_alternatives(alternatives: tuple[str, ...]) -> tuple[frozenset[str], ...]:
    """Sum of products written out as a list, one ini expression per alternative."""
    return _minimal(term for alternative in alternatives for term in _parse_expression(alternative))
    
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
                expression = EDGE_OVERRIDES.get((node_id, target), fields.get(target, "nothing"))    #Include logic overrides
                self._add_edge(node_id, target, _parse_expression(expression))
        built = {(edge.source, edge.target) for edge in self.edges}
        stale = set(EDGE_OVERRIDES) - built
        if stale:
            raise ValueError(f"EDGE_OVERRIDES names edges the ini does not build: {sorted(stale)}")

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

# code spot location -> sum of products, all in the start region
SIGN_REGION: str = START_REGION
SIGN_TERMS: dict[str, tuple[frozenset[str], ...]] = {
    name: _parse_alternatives(alternatives) for name, alternatives in SIGN_LOGIC.items()
}
SIGN_TOKENS: frozenset[str] = frozenset(
    token for terms in SIGN_TERMS.values() for term in terms for token in term
)
MAZE_PILLAR_TERMS: tuple[frozenset[str], ...] = _parse_alternatives(MAZE_PILLAR_LOGIC)

def _validate() -> None:
    """Fail at import rather than halfway through generation."""
    mapped = (set(ITEM_INDEX_TO_LOCATION.values()) | set(FLAG_TOKEN_LOCATIONS.values()) | set(SIGN_LOGIC) | {MAZE_PILLAR})

    unknown = mapped - set(LOCATION_NAME_TO_ID)
    if unknown:
        raise ValueError(f"logic maps locations that data.py does not define: {sorted(unknown)}")

    unmapped = set(LOCATION_NAME_TO_ID) - mapped
    if unmapped:
        raise ValueError(f"data.py defines locations no ini node or sign rule holds: {sorted(unmapped)}")
        
    no_char = sorted(set(SIGN_LOGIC) - set(SIGN_LOCATIONS))
    if no_char:
        raise ValueError(f"code spots without a SIGN_DONE entry in data.CHECK_CHAR: {no_char}")
        
    no_rule = sorted(set(SIGN_LOCATIONS) - set(SIGN_LOGIC))
    if no_rule:
        raise ValueError(f"code spots without a rule in SIGN_LOGIC: {no_rule}")

    no_flag = sorted(name for name in (*SIGN_LOCATIONS, MAZE_PILLAR) if name not in LOCATION_FLAG)
    if no_flag:
        raise ValueError(f"code spots without a LOCATION_FLAG entry in data.py: {no_flag}")

    impassable = sorted(name for name, terms in SIGN_TERMS.items() if not terms)
    if impassable:
        raise ValueError(f"sign rules that can never be met: {impassable}")
    
    flag_tokens = set(FLAG_TOKEN_LOCATIONS) | set(FLAG_TOKEN_EVENTS)

    overlap = set(FLAG_TOKEN_LOCATIONS) & set(FLAG_TOKEN_EVENTS)
    if overlap:
        raise ValueError(f"tokens cannot be a location and an event at once: {sorted(overlap)}")

    both = (FREE_TOKENS | DROPPED_TOKENS) & flag_tokens
    if both:
        raise ValueError(f"tokens cannot be free and granted at once: {sorted(both)}")
        
    conflicting = (FREE_TOKENS & DROPPED_TOKENS) | (set(TOKEN_ALIASES) & (FREE_TOKENS | DROPPED_TOKENS))
    if conflicting:
        raise ValueError(f"tokens with more than one meaning (free, dropped, aliased): {sorted(conflicting)}")
        
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
        
    placed = set(ITEM_NODES.values()) | set(SIGN_TERMS) | {MAZE_PILLAR}
    missing = mapped - placed
    if missing:
        raise ValueError(f"locations with no node to live in: {sorted(missing)}")

    orphan_pads = set(TELEPORT_PADS) - set(TELEPORT_FINDS)
    if orphan_pads:
        raise ValueError(f"teleporters that can never be found: {sorted(orphan_pads)}")
        
    jungle = TELEPORT_PADS.get(JUNGLE_TELEPORT_PAD)
    if jungle is None or NODES[jungle].name != "Jungle Start tp":
        raise ValueError(f"teleporter {JUNGLE_TELEPORT_PAD} is not the Jungle Start tp the sign rules expect")
_validate()
