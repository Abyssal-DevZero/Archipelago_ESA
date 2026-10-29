"""Tests for the ESA logic graph and the rules built from it.

* '|' binds tighter than '&' in the ini
* Dropped tokens must not cut whole areas out of the graph, or fill cannot place everything.
"""

from __future__ import annotations
 
import unittest
 
from test.bases import WorldTestBase
 
from .. import logic
from ..rules import CLASS_A_NODE, TOKEN_RULES
 
EXPECTED_FINGERPRINT = "30e5cea60639f659"
EXPECTED_NODES = 121
EXPECTED_EDGES = 275
EXPECTED_LOCATIONS = 49
EXPECTED_TELEPORTERS = 13
EXPECTED_DOOR_EDGES = 42  # 21 room transitions, both directions
 
FLAG_TOKENS = frozenset(logic.FLAG_TOKEN_LOCATIONS) | frozenset(logic.FLAG_TOKEN_EVENTS)
 
 
def _edge(source: str, target: str) -> logic.Edge | None:
    return next((e for e in logic.EDGES if (e.source, e.target) == (source, target)), None)
 
 
def _terms(*terms: set[str]) -> set[frozenset[str]]:
    return {frozenset(term) for term in terms}
 
 
def _region(node_id: str) -> str:
    return logic.NODES[node_id].region
 
 
def _reachable(items: frozenset[str]) -> set[str]:
    """Node ids reachable with ``items`` (ini tokens, flag tokens excluded).
 
    Flag tokens are granted the way the world grants them: by reaching their node. Teleporters work like the hub in regions.py: a pad is usable once its find node was reached
    """
    teleport_access = "tpaccess" in items
    inventory = set(items)
    seen = {logic.START_NODE}
    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for token, node in logic.FLAG_GRANTS.items():
            if node in seen and token not in inventory:
                inventory.add(token)
                changed = True
        for pad, find_node in logic.TELEPORT_FINDS.items():
            if find_node in seen and pad not in found:
                found.add(pad)
                changed = True
        for edge in logic.EDGES:
            if edge.source in seen and edge.target not in seen:
                if any(term <= inventory for term in edge.terms):
                    seen.add(edge.target)
                    changed = True
        if teleport_access:
            for pad in found:
                node = logic.TELEPORT_PADS[pad]
                if node not in seen:
                    seen.add(node)
                    changed = True
    return seen
 
 
FULL_INVENTORY = frozenset(logic.ALL_TOKENS - FLAG_TOKENS) | {"tpaccess"}
 
 
class TestParseExpression(unittest.TestCase):
    """The ini's expression grammar: '&' separates requirements, '|' lists alternatives within one."""
 
    parse = staticmethod(logic._parse_expression)
 
    def test_pipe_binds_tighter_than_ampersand(self) -> None:
        self.assertEqual(
            _terms({"jump", "vdash"}, {"jump", "xv"}, {"hook", "vdash"}, {"hook", "xv"}),
            set(self.parse("jump|hook&vdash|xv")),
        )
 
    def test_single_alternative_does_not_bypass_other_clauses(self) -> None:
        """The exact shape of the Pillar 1 bug: 'jump' alone must never satisfy 'jump|hook&vdash|xv&classa'."""
        terms = self.parse("jump|hook&vdash|xv&classa")
        self.assertNotIn(frozenset({"jump"}), terms)
        self.assertTrue(all("classa" in term for term in terms))
 
    def test_nothing_is_free(self) -> None:
        self.assertEqual((frozenset(),), self.parse("nothing"))
 
    def test_nothing_satisfies_its_clause_only(self) -> None:
        self.assertEqual((frozenset({"gold"}),), self.parse("jump|nothing&gold"))
 
    def test_dropped_token_alone_makes_the_edge_impassable(self) -> None:
        self.assertEqual((), self.parse("jumporv&poweroff"))
 
    def test_dropped_token_is_only_removed_from_its_alternatives(self) -> None:
        self.assertEqual(_terms({"jump"}, {"vdash"}), set(self.parse("jump|vdash|poweroff")))
 
    def test_growth_on_is_free(self) -> None:
        self.assertEqual((frozenset({"poweron"}),), self.parse("growthon&poweron"))
 
    def test_growth_off_means_teleport_access(self) -> None:
        self.assertEqual((frozenset({"jumporv", "tpaccess"}),), self.parse("jumporv&growthoff"))
 
    def test_mender_is_free(self) -> None:
        self.assertEqual((frozenset({"gold"}),), self.parse("gold&mender"))
 
    def test_absorption_removes_redundant_terms(self) -> None:
        self.assertEqual((frozenset({"jump"}),), self.parse("jump&jump|vdash"))
 
    def test_whitespace_is_ignored(self) -> None:
        self.assertEqual(self.parse("jump|hook&vdash"), self.parse(" jump | hook & vdash "))
 
    def test_order_is_deterministic(self) -> None:
        terms = self.parse("bike|hdash&hook&jump&vdash|xv&charge&heatsuit")
        self.assertEqual(sorted(terms, key=lambda t: (len(t), sorted(t))), list(terms))
        self.assertEqual(terms, self.parse("bike|hdash&hook&jump&vdash|xv&charge&heatsuit"))
 
 
class TestLogicGraph(unittest.TestCase):
    def test_fingerprint(self) -> None:
        self.assertEqual(
            EXPECTED_FINGERPRINT, logic.GRAPH_FINGERPRINT,
            "The parsed graph changed (ini edit, parser change or override). "
            "Re-check reachability, then update the fingerprint and the counts.",
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
 
    def test_free_dropped_and_aliased_tokens_never_reach_the_rules(self) -> None:
        self.assertEqual(set(), logic.ALL_TOKENS & logic.FREE_TOKENS)
        self.assertEqual(set(), logic.ALL_TOKENS & logic.DROPPED_TOKENS)
        self.assertEqual(set(), logic.ALL_TOKENS & set(logic.TOKEN_ALIASES))
 
    def test_token_meanings_are_pinned(self) -> None:
        """Changing how a game state token is treated changes every seed, so it has to be deliberate."""
        self.assertEqual({"poweroff"}, logic.DROPPED_TOKENS)
        self.assertEqual({"growthon", "mender"}, logic.FREE_TOKENS)
        self.assertEqual({"growthoff": "tpaccess"}, logic.TOKEN_ALIASES)
 
    def test_no_edge_is_impassable(self) -> None:
        """Impassable edges are skipped by the parser, never built with an empty rule."""
        self.assertTrue(all(edge.terms for edge in logic.EDGES))
 
    def test_entrance_names_are_unique(self) -> None:
        names = [edge.name for edge in logic.EDGES]
        self.assertEqual(len(names), len(set(names)))
 
    def test_region_names_are_unique(self) -> None:
        self.assertEqual(len(logic.REGION_NAMES), len(set(logic.REGION_NAMES)))
 
    def test_doors_are_free(self) -> None:
        doors = [edge for edge in logic.EDGES if edge.name.endswith("(door)")]
        self.assertEqual(EXPECTED_DOOR_EDGES, len(doors))
        self.assertTrue(all(edge.is_free for edge in doors))
 
    def test_flag_tokens_are_real_items(self) -> None:
        """A mapped flag token is granted by exactly one node, and has a rule on every edge that uses it."""
        self.assertEqual({"password": "116", "switch": "3", "classa": "115"}, logic.FLAG_GRANTS)
        for token in FLAG_TOKENS:
            self.assertIn(token, logic.ALL_TOKENS, f"{token} gates nothing, so its item would be dead weight")
            self.assertIn(token, TOKEN_RULES)
        for token, location in logic.FLAG_TOKEN_LOCATIONS.items():
            self.assertEqual(location, logic.ITEM_NODES[logic.FLAG_GRANTS[token]])
 
    def test_switch_is_an_event_on_the_propeller_node(self) -> None:
        """The switch is flipped in the Propeller room, so it cannot be Has("Propeller"): that item is shuffled."""
        node = logic.FLAG_GRANTS["switch"]
        self.assertEqual("Propeller", logic.NODES[node].name)
        self.assertNotIn("switch", logic.FLAG_TOKEN_LOCATIONS)
        self.assertEqual("Propeller Spot", logic.ITEM_NODES[node], "the node still holds its own shuffled item")
 
    def test_overrides_are_applied(self) -> None:
        for source, target in logic.EDGE_OVERRIDES:
            self.assertIsNotNone(_edge(source, target), f"override {source}->{target} built no edge")
 
 
class TestEdgeRegressions(unittest.TestCase):
    """Edges whose meaning flipped with the precedence fix. Each one was exploitable under the old parse."""
 
    def test_mainframe_shortcut_needs_class_a(self) -> None:
        """Mainframe tp -> Mainframe to Caves, the edge from the UT path of the Pillar 1 bug report."""
        self.assertEqual(
            _terms({"classa", "jump", "vdash"}, {"classa", "jump", "xv"},
                   {"classa", "hook", "vdash"}, {"classa", "hook", "xv"}),
            set(_edge("54", "85").terms),
        )
 
    def test_start_to_pillar_1_needs_jump_and_vdash(self) -> None:
        self.assertEqual((frozenset({"jump", "vdash"}),), _edge("65", "45").terms)
 
    def test_password_gates_derelict(self) -> None:
        edge = _edge("119", "120")
        self.assertEqual(
            _terms({"hook", "jumporv", "password", "vdash"}, {"jumporv", "password", "triple", "vdash"}),
            set(edge.terms),
        )
 
    def test_supercharge_module_needs_heat_suit(self) -> None:
        """Old parse: the Bike alone reached the Supercharge Module in the fire zone."""
        for term in _edge("108", "12").terms:
            self.assertTrue({"charge", "heatsuit", "hook", "jump"} <= term, sorted(term))
 
    def test_disk_room_needs_gold(self) -> None:
        """The Disk Room is the only way to Dash Booster X Spot, so a Gold Keycard placed there locks itself."""
        self.assertTrue(all("gold" in term for term in _edge("108", "110").terms))
        self.assertEqual({"110"}, {e.source for e in logic.EDGES if e.target == "13"})
 
    def test_deep_jungle_override_keeps_both_movement_options(self) -> None:
        """ini: 'jump&hook|vdash&charge' == jump & (hook|vdash) & charge. The override only adds requirements."""
        added = {"tpaccess", "poweron", "hdash", "charge"}
        self.assertEqual(
            _terms({"jump", "hook"} | added, {"jump", "vdash"} | added),
            set(_edge("114", "49").terms),
        )
 
 
class TestJungleGrowth(unittest.TestCase):
    """The jungle in its growth-on end state. The growth-off routes need Teleport Access instead."""
 
    def test_walking_in_from_jungle_start_needs_teleport_access(self) -> None:
        self.assertEqual(
            _terms({"jump", "hook", "tpaccess"}, {"jump", "vdash", "tpaccess"}),
            set(_edge("50", "114").terms),
        )
 
    def test_growth_off_exits_need_teleport_access(self) -> None:
        self.assertEqual((frozenset({"tpaccess"}),), _edge("114", "102").terms)
        self.assertEqual((frozenset({"jumporv", "tpaccess"}),), _edge("114", "50").terms)
 
    def test_deep_jungle_into_jungle_1_with_growth_on(self) -> None:
        self.assertEqual((frozenset({"charge", "hdash", "jumporv", "poweron"}),), _edge("49", "114").terms)
 
    def test_jungle_diskette_needs_no_mender_token(self) -> None:
        terms = _edge("114", "26").terms
        self.assertTrue(all({"charge", "gold"} <= term for term in terms))
        self.assertFalse(any("mender" in term for term in terms))
 
    def test_no_route_into_the_jungle_without_teleport_access(self) -> None:
        """Every edge from outside into the jungle or temple needs Teleport Access, so nobody walks into a trap."""
        inside = {"114", "68", "69", "51", "49", "5", "10", "26", "27", "29", "38", "66", "67"}
        for edge in logic.EDGES:
            if edge.target in inside and edge.source not in inside:
                with self.subTest(edge=edge.name):
                    self.assertTrue(all("tpaccess" in term for term in edge.terms))
 
 
class TestReachability(unittest.TestCase):
    """Everything must be reachable with a full inventory, or fill cannot work."""
 
    def test_all_nodes_reachable(self) -> None:
        unreachable = sorted(set(logic.NODES) - _reachable(FULL_INVENTORY), key=int)
        self.assertEqual(
            [], unreachable,
            f"unreachable nodes: {[_region(n) for n in unreachable]}",
        )
 
    def test_all_locations_reachable(self) -> None:
        reachable = _reachable(FULL_INVENTORY)
        stranded = sorted(name for node, name in logic.ITEM_NODES.items() if node not in reachable)
        self.assertEqual([], stranded)
 
    def test_teleport_access_gates_sandrock_jungle_and_temple(self) -> None:
        """Sandrock tp has no other way in, and the jungle and temple need it so the player can always come back."""
        lost = _reachable(FULL_INVENTORY) - _reachable(FULL_INVENTORY - {"tpaccess"})
        self.assertEqual(
            {"60", "31",                                       # Sandrock tp, Diskette sandmid
             "114", "68", "69", "51", "49", "66", "67",        # Jungle 1, temple entrances, Deep Jungle
             "5", "10", "26", "27", "29", "38"},               # the six jungle and temple locations
            lost,
        )
 
    def test_flag_nodes_do_not_need_their_own_token(self) -> None:
        """The node granting a token must be reachable without that token, or its location locks itself."""
        reachable = _reachable(FULL_INVENTORY)
        for token, node in logic.FLAG_GRANTS.items():
            self.assertIn(node, reachable, token)
 
    def test_goal_node_reachable(self) -> None:
        self.assertIn(CLASS_A_NODE, _reachable(FULL_INVENTORY))
 
 
class ESATestBase(WorldTestBase):
    """Shared base. Subclasses that set options also run AP's default reachability and fill tests."""
 
    game = "Environmental Station Alpha"
 
    def collect_event(self, name: str) -> None:
        """Events are locked items on their own location; collect_by_name only searches the itempool."""
        self.collect(self.multiworld.get_location(name, self.player).item)
 
 
class TestRules(ESATestBase):
    """Rule-level checks on a generated world. Also runs AP's default fill tests with this option set."""
 
    options = {"start_with_jump_booster": False}
 
    def test_pillar_1_needs_more_than_jump(self) -> None:
        """Seed 91618731083770012827 put Pillar 1 Monitor in sphere 2 with only the Jump Booster."""
        self.collect_by_name("Jump Booster")
        self.assertFalse(self.can_reach_location("Pillar 1 Monitor"))
        self.collect_by_name("Dash Booster V")
        self.assertTrue(self.can_reach_location("Pillar 1 Monitor"))
 
    def test_jump_alone_reaches_no_movement_upgrade(self) -> None:
        """The opening that seed got stuck in: Charge, V-Dash, Hookshot and Supercharge all stay out of reach."""
        self.collect_by_name("Jump Booster")
        self.assertTrue(self.can_reach_location("Health Pack Beetle Spot"))
        self.assertTrue(self.can_reach_location("Hookshot Spot"))
        for location in ("Diskette Caves Spot", "Diskette Depthsmaze Spot",
                         "Pillar 1 Monitor", "Dash Booster V Spot"):
            with self.subTest(location=location):
                self.assertFalse(self.can_reach_location(location))
 
    def test_mainframe_shortcut_needs_class_a(self) -> None:
        entrance = f"{_region('54')} -> {_region('85')}"
        self.collect_by_name(["Jump Booster", "Hookshot", "Dash Booster V"])
        self.assertTrue(self.can_reach_region(_region("54")))
        self.assertFalse(self.can_reach_entrance(entrance))
        self.collect_event("Class A Unlocked")
        self.assertTrue(self.can_reach_entrance(entrance))
 
    def test_gold_keycard_gates_its_own_vanilla_spot(self) -> None:
        self.collect_all_but("Gold Keycard")
        self.assertFalse(self.can_reach_location("Dash Booster X Spot"))
        self.assertFalse(self.can_reach_location("Diskette Ship Spot"))
 
    def test_supercharge_module_needs_heat_suit(self) -> None:
        self.collect_all_but("Heat-Resistant Suit")
        self.assertFalse(self.can_reach_location("Supercharge Module Spot"))
 
    def test_teleport_access_gates_sandrock_jungle_and_temple(self) -> None:
        gated = ("Diskette SandMid Spot", "Dash Booster H Spot", "Triple Shot Spot", "Diskette Jungle Spot",
                 "Diskette TempleLeft Spot", "Diskette TempleTall Spot", "Key Temple Spot")
        self.collect_all_but("Teleport Access")
        for location in gated:
            with self.subTest(location=location, teleport_access=False):
                self.assertFalse(self.can_reach_location(location))
        self.collect_by_name("Teleport Access")
        for location in gated:
            with self.subTest(location=location, teleport_access=True):
                self.assertTrue(self.can_reach_location(location))
 
    def test_teleport_access_is_never_placed_behind_itself(self) -> None:
        """Fill must keep Teleport Access out of the jungle and temple. Checked by generating a few seeds."""
        from Fill import distribute_items_restrictive
        gated = {"Diskette SandMid Spot", "Dash Booster H Spot", "Triple Shot Spot", "Diskette Jungle Spot",
                 "Diskette TempleLeft Spot", "Diskette TempleTall Spot", "Key Temple Spot"}
        for seed in range(5):
            with self.subTest(seed=seed):
                self.world_setup(seed)
                distribute_items_restrictive(self.multiworld)
                spot = self.multiworld.find_item("Teleport Access", self.player)
                self.assertNotIn(spot.name, gated)
 
    def test_jump_booster_is_in_the_pool(self) -> None:
        self.assertIn("Jump Booster", {item.name for item in self.multiworld.itempool})
        self.assertNotIn("Jump Booster", {item.name for item in self.multiworld.precollected_items[self.player]})
 
 
class TestStartWithJumpBooster(ESATestBase):
    options = {"start_with_jump_booster": True}
 
    def test_jump_booster_is_precollected(self) -> None:
        self.assertIn("Jump Booster", {item.name for item in self.multiworld.precollected_items[self.player]})
        self.assertNotIn("Jump Booster", {item.name for item in self.multiworld.itempool})
 
 
BASE_GAME_ITEMS = ["Power", "Gate Alpha", "Gate Beta", "Gate Gamma", "Gate Delta"]
 
 
class TestGoalBaseGame(ESATestBase):
    options = {"goal": "base_game", "start_with_jump_booster": False}
 
    def test_needs_power_gates_and_class_a(self) -> None:
        self.collect_by_name(BASE_GAME_ITEMS)
        self.assertBeatable(False)
        self.collect_event("Class A Unlocked")
        self.assertBeatable(True)
        self.remove_by_name("Gate Beta")
        self.assertBeatable(False)
 
    def test_bike_spot_holds_no_progression(self) -> None:
        rule = self.multiworld.get_location("Bike Spot", self.player).item_rule
        self.assertFalse(rule(self.world.create_item("Hookshot")))
        self.assertTrue(rule(self.world.create_item("Data Fragment")))
 
 
class TestGoalPostgame(ESATestBase):
    options = {"goal": "postgame", "start_with_jump_booster": False}
 
    def test_needs_pillars_and_all_dash_boosters_on_top(self) -> None:
        self.collect_by_name(BASE_GAME_ITEMS)
        self.collect_event("Class A Unlocked")
        self.assertBeatable(False)
        self.collect_by_name(["Pillar 1", "Pillar 2", "Pillar 3", "Pillar 4"])
        self.assertBeatable(False)
        self.collect_by_name(["Dash Booster H", "Dash Booster V", "Dash Booster X"])
        self.assertBeatable(True)
 
    def test_bike_spot_may_hold_progression(self) -> None:
        rule = self.multiworld.get_location("Bike Spot", self.player).item_rule
        self.assertTrue(rule(self.world.create_item("Hookshot")))
