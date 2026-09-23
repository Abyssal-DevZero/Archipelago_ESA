"""
The ini is parsed at import instead of being converted into a checked-in table, which means an upstream edit to glitchlesslogic.ini would otherwise change every
seed
"""

from __future__ import annotations

import unittest

from .. import logic
from ..rules import TOKEN_RULES

EXPECTED_FINGERPRINT = "5afceee97fb2dd0a"
EXPECTED_NODES = 121
EXPECTED_EDGES = 272
EXPECTED_LOCATIONS = 49
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
 
    def test_free_and_dropped_tokens_never_reach_the_rules(self) -> None:
        self.assertEqual(set(), logic.ALL_TOKENS & logic.FREE_TOKENS)
        self.assertEqual(set(), logic.ALL_TOKENS & logic.DROPPED_TOKENS)
 
    def test_entrance_names_are_unique(self) -> None:
        names = [edge.name for edge in logic.EDGES]
        self.assertEqual(len(names), len(set(names)))
 
    def test_region_names_are_unique(self) -> None:
        self.assertEqual(len(logic.REGION_NAMES), len(set(logic.REGION_NAMES)))
 
    def test_flag_tokens_are_real_items(self) -> None:
        """A mapped flag token is granted by exactly one node, and has a rule on every edge that uses it."""
        self.assertEqual({"password": "116", "switch": "3"}, logic.FLAG_GRANTS)
        for token in (*logic.FLAG_TOKEN_LOCATIONS, *logic.FLAG_TOKEN_EVENTS):
            self.assertIn(token, logic.ALL_TOKENS, f"{token} gates nothing, so its item would be dead weight")
            self.assertIn(token, TOKEN_RULES)

        for token, location in logic.FLAG_TOKEN_LOCATIONS.items():
            self.assertEqual(location, logic.ITEM_NODES[logic.FLAG_GRANTS[token]])

    def test_switch_is_an_event_on_the_propeller_node(self) -> None:
        """The switch is flipped in the Propeller room, so it cannot be Has("Propeller"): that item is shuffled elsewhere."""
        node = logic.FLAG_GRANTS["switch"]
        self.assertEqual("Propeller", logic.NODES[node].name)
        self.assertNotIn("switch", logic.FLAG_TOKEN_LOCATIONS)
        self.assertEqual("Propeller Spot", logic.ITEM_NODES[node], "the node still holds its own shuffled item")

    def test_password_gates_derelict(self) -> None:
        edge = next(e for e in logic.EDGES if (e.source, e.target) == ("119", "120"))
        self.assertIn(frozenset({"hook", "jumporv", "password"}), edge.terms)

    def test_doors_are_free(self) -> None:
        """The 21 room transitions carry no requirement, 42 edges in total."""
        doors = [edge for edge in logic.EDGES if edge.name.endswith("(door)")]
        self.assertEqual(42, len(doors))
        self.assertTrue(all(edge.is_free for edge in doors))
 
 
class TestReachability(unittest.TestCase):
    """Everything must be reachable with a full inventory, or fill cannot work."""
 
    def _reachable(self, *, teleports: bool = True, without: frozenset[str] = frozenset()) -> set[str]:
        inventory = set(logic.ALL_TOKENS) - without
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
                for pad in list(found):
                    target = logic.TELEPORT_PADS.get(pad)
                    if target and target not in seen:
                        seen.add(target)
                        queue.append(target)
        return seen
 
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
 
    def test_flag_nodes_do_not_need_their_own_token(self) -> None:
        """The node granting a token must be reachable without that token, or its location locks itself."""
        for token, node in logic.FLAG_GRANTS.items():
            self.assertIn(node, self._reachable(without=frozenset({token})), token)

    def test_goal_region_reachable(self) -> None:
        from ..rules import AI_MAINFRAME_NODE
 
        self.assertIn(AI_MAINFRAME_NODE, self._reachable())
