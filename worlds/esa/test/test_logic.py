"""Guards the parsed logic graph.

The ini is parsed at import instead of being converted into a checked-in table, which means an upstream edit to glitchlesslogic.ini would otherwise change every
seed silently.

If a change to the ini is intended, update EXPECTED_FINGERPRINT and the counts.
"""

from __future__ import annotations

import unittest

from .. import logic
from ..rules import TOKEN_RULES

EXPECTED_FINGERPRINT = "2108723bf7e469ee"
EXPECTED_NODES = 121
EXPECTED_EDGES = 272
EXPECTED_LOCATIONS = 48
EXPECTED_TELEPORTERS = 13


class TestLogicGraph(unittest.TestCase):
    def test_fingerprint(self) -> None:
        self.assertEqual(
            EXPECTED_FINGERPRINT, logic.GRAPH_FINGERPRINT,
            "glitchlesslogic.ini changed. Re-check reachability, then update the fingerprint.",
        )

    def test_counts(self) -> None:
        self.assertEqual(EXPECTED_NODES, len(logic.NODES))
        self.assertEqual(EXPECTED_EDGES, len(logic.EDGES))
        self.assertEqual(EXPECTED_LOCATIONS, len(logic.ITEM_NODES))
        self.assertEqual(EXPECTED_TELEPORTERS, len(logic.TELEPORT_PADS))
        self.assertEqual(EXPECTED_TELEPORTERS, len(logic.TELEPORT_FINDS))

    def test_every_token_has_a_rule(self) -> None:
        missing = logic.ALL_TOKENS - set(TOKEN_RULES)
        self.assertEqual(set(), missing, f"tokens with no rule: {sorted(missing)}")

    def test_entrance_names_are_unique(self) -> None:
        names = [edge.name for edge in logic.EDGES]
        self.assertEqual(len(names), len(set(names)))

    def test_region_names_are_unique(self) -> None:
        self.assertEqual(len(logic.REGION_NAMES), len(set(logic.REGION_NAMES)))

    def test_doors_are_free(self) -> None:
        """The 21 room transitions carry no requirement, 42 edges in total."""
        doors = [edge for edge in logic.EDGES if edge.name.endswith("(door)")]
        self.assertEqual(42, len(doors))
        self.assertTrue(all(edge.is_free for edge in doors))


class TestReachability(unittest.TestCase):
    """Everything must be reachable with a full inventory, or fill cannot work."""

    ALL_ITEM_TOKENS = frozenset(
        token for token in logic.ALL_TOKENS if token not in logic.FLAG_EVENTS
    )

    def _reachable(self, *, teleports: bool = True) -> set[str]:
        inventory = set(self.ALL_ITEM_TOKENS)
        while True:
            seen = {logic.START_NODE}
            queue = [logic.START_NODE]
            found: set[str] = set()
            while queue:
                node = queue.pop()
                found |= {pad for pad, find in logic.TELEPORT_FINDS.items() if find == node}
                for edge in logic.EDGES:
                    if edge.source == node and edge.target not in seen:
                        if any(term <= inventory for term in edge.terms):
                            seen.add(edge.target)
                            queue.append(edge.target)
                if teleports:
                    for pad in found:
                        target = logic.TELEPORT_PADS.get(pad)
                        if target and target not in seen:
                            seen.add(target)
                            queue.append(target)
            granted = {token for token, node in logic.FLAG_GRANTS.items() if node in seen}
            if granted <= inventory:
                return seen
            inventory |= granted

    def test_all_nodes_reachable(self) -> None:
        unreachable = set(logic.NODES) - self._reachable()
        self.assertEqual(set(), unreachable, f"unreachable nodes: {sorted(unreachable)}")

    def test_all_locations_reachable(self) -> None:
        reachable = self._reachable()
        stranded = [name for node, name in logic.ITEM_NODES.items() if node not in reachable]
        self.assertEqual([], stranded)

    def test_teleport_network_is_load_bearing(self) -> None:
        """Sandrock tp and the Diskette behind it have no other way in."""
        without = self._reachable(teleports=False)
        self.assertEqual({"60", "31"}, set(logic.NODES) - without)

    def test_goal_region_reachable(self) -> None:
        from ..rules import AI_MAINFRAME_NODE

        self.assertIn(AI_MAINFRAME_NODE, self._reachable())
