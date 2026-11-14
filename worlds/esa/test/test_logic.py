"""Tests for the ESA logic graph and the rules built from it.

* '|' binds tighter than '&' in the ini
* Dropped tokens must not cut whole areas out of the graph, or fill cannot place everything.
"""

from __future__ import annotations

import unittest

from BaseClasses import CollectionState
from test.bases import WorldTestBase

from .. import logic
from ..data import (
    BASE_ID, CHECK_CHAR, CHECK_EXACT, CODE_SPOT_LOCATIONS, FREE_SIGN_FLAG, GRANT_FLAG, ITEM_NAME_TO_ID,
    LOCATION_FLAG, LOCATION_NAME_TO_ID, MAZE_ENDING_FLAG, MAZE_PILLAR, MIRROR_FLAGS, PILLAR_DONE, PILLAR_FLAG,
    PILLAR_ITEM, READ_REAL_FLAG, SIGN_DONE, SIGN_FLAG, SIGN_ITEMS, SIGN_LOCATIONS,
)
from ..rules import CLASS_A_NODE, TOKEN_RULES

EXPECTED_FINGERPRINT = "30e5cea60639f659"
EXPECTED_NODES = 121
EXPECTED_EDGES = 275
EXPECTED_LOCATIONS = 49
EXPECTED_TELEPORTERS = 13
EXPECTED_DOOR_EDGES = 42  # 21 room transitions, both directions
EXPECTED_SIGNS = 13       # 14 code spots, Sign 8 is entered by the game

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

    def test_alternatives_are_an_or_with_absorption(self) -> None:
        self.assertEqual((frozenset({"vdash"}),), logic._parse_alternatives(("vdash&gold", "vdash")))
        self.assertEqual(_terms({"gold", "jump"}, {"vdash"}), set(logic._parse_alternatives(("gold&jump", "vdash"))))


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
        self.assertEqual("Propeller Spot (01-20)", logic.ITEM_NODES[node], "the node still holds its own shuffled item")

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


def _sign_number(name: str) -> int:
    return int(name.split()[2])        # "Sign Location 3 (Planet Surface)" -> 3


class TestSignTables(unittest.TestCase):
    """The hardcoded code spot tables in data.py: the checks fill mark[11..23] in sign order, location id 80 + n,
    '5' once "esa" was entered. The sign numbering skips 8, the mark entries don't."""

    def test_sign_checks_fill_mark_11_to_23_without_a_gap(self) -> None:
        ordered = sorted(SIGN_LOCATIONS, key=_sign_number)
        self.assertEqual([(8, 11 + i) for i in range(len(ordered))], [LOCATION_FLAG[name] for name in ordered])

    def test_code_spots_cover_mark_11_to_24_once(self) -> None:
        """13 checks and the game's own spot: every '5' of the end-of-game mark dump, none twice."""
        indices = [LOCATION_FLAG[name][1] for name in SIGN_LOCATIONS] + [i for _, i in FREE_SIGN_FLAG.values()]
        self.assertEqual(list(range(11, 25)), sorted(indices))

    def test_sign_n_has_id_80_plus_n(self) -> None:
        for name in SIGN_LOCATIONS:
            with self.subTest(sign=name):
                self.assertEqual(80 + _sign_number(name), LOCATION_NAME_TO_ID[name])

    def test_every_code_spot_is_listed_once(self) -> None:
        numbers = sorted(_sign_number(name) for name in (*SIGN_LOCATIONS, *FREE_SIGN_FLAG))
        self.assertEqual(list(range(1, 15)), numbers)

    def test_the_free_sign_is_no_location(self) -> None:
        self.assertEqual(EXPECTED_SIGNS, len(SIGN_LOCATIONS))
        self.assertEqual({"Sign Location 8": (8, 24)}, FREE_SIGN_FLAG)
        for name in FREE_SIGN_FLAG:
            self.assertNotIn(name, LOCATION_NAME_TO_ID)
            self.assertNotIn(name, LOCATION_FLAG)
        self.assertNotIn(88, LOCATION_NAME_TO_ID.values(), "id 88 stays reserved for Sign 8")

    def test_sign_item_n_sets_the_flag_of_sign_location_n(self) -> None:
        self.assertEqual(len(SIGN_LOCATIONS), len(SIGN_ITEMS))
        by_number = {_sign_number(name): name for name in SIGN_LOCATIONS}
        for item in SIGN_ITEMS:
            n = int(item.split()[1])
            with self.subTest(item=item):
                self.assertEqual((*LOCATION_FLAG[by_number[n]], SIGN_DONE), SIGN_FLAG[item])
                self.assertEqual(BASE_ID + 50 + n, ITEM_NAME_TO_ID[item])

    def test_signs_count_only_on_their_character(self) -> None:
        for name in SIGN_LOCATIONS:
            self.assertEqual(SIGN_DONE, CHECK_CHAR[name])
            self.assertIn(name, CHECK_EXACT)

    def test_mwya_pillar(self) -> None:
        """'mwya' at 22-16 writes 'T' into superjump[2]; superjump_all covers that slot, so it is read real."""
        self.assertEqual("MWYA Pillar (22-16)", MAZE_PILLAR)
        self.assertEqual(95, LOCATION_NAME_TO_ID[MAZE_PILLAR])
        self.assertEqual((6, 2), LOCATION_FLAG[MAZE_PILLAR])
        self.assertEqual("T", PILLAR_DONE)
        self.assertEqual(PILLAR_DONE, CHECK_CHAR[MAZE_PILLAR])
        self.assertIn(MAZE_PILLAR, CHECK_EXACT)
        self.assertIn(MAZE_PILLAR, READ_REAL_FLAG)
        self.assertNotIn(MAZE_PILLAR, MIRROR_FLAGS, "an item owns the pillar flag now")
        self.assertNotIn(MAZE_PILLAR, SIGN_LOCATIONS)
        self.assertEqual((*SIGN_LOCATIONS, MAZE_PILLAR), CODE_SPOT_LOCATIONS)

    def test_mwya_pillar_item(self) -> None:
        """Receiving the MWYA Pillar item writes the pillar's own flag into the real superjump: the labyrinth opens."""
        self.assertEqual("MWYA Pillar", PILLAR_ITEM)
        self.assertEqual(BASE_ID + 65, ITEM_NAME_TO_ID[PILLAR_ITEM])
        self.assertEqual({PILLAR_ITEM: (6, 2, PILLAR_DONE)}, PILLAR_FLAG)
        self.assertEqual(PILLAR_FLAG[PILLAR_ITEM], GRANT_FLAG[PILLAR_ITEM])
        self.assertEqual(LOCATION_FLAG[MAZE_PILLAR], PILLAR_FLAG[PILLAR_ITEM][:2])
        self.assertNotIn(PILLAR_ITEM, SIGN_ITEMS)

    def test_mirrored_flags_are_no_item_flags(self) -> None:
        """A mirrored flag is set from either copy; an item projecting onto it would fight that."""
        granted = {(slot, index) for slot, index, _ in GRANT_FLAG.values()}
        for name, (slot, index, _) in MIRROR_FLAGS.items():
            self.assertNotIn((slot, index), granted, name)
        self.assertEqual((8, 24, SIGN_DONE), MIRROR_FLAGS["Sign Location 8"])

    def test_maze_ending_flag(self) -> None:
        self.assertEqual((8, 27, "B"), MAZE_ENDING_FLAG)

    def test_no_two_locations_share_a_flag(self) -> None:
        flags = list(LOCATION_FLAG.values())
        self.assertEqual(len(flags), len(set(flags)))

    def test_ids_are_unique(self) -> None:
        self.assertEqual(len(LOCATION_NAME_TO_ID), len(set(LOCATION_NAME_TO_ID.values())))


class TestSignLogic(unittest.TestCase):
    def test_every_sign_has_a_rule(self) -> None:
        self.assertEqual(set(SIGN_LOCATIONS), set(logic.SIGN_TERMS))
        self.assertTrue(all(logic.SIGN_TERMS.values()))

    def test_every_sign_token_has_a_rule(self) -> None:
        missing = logic.SIGN_TOKENS - set(TOKEN_RULES)
        self.assertEqual(set(), missing, f"sign tokens with no rule: {sorted(missing)}")

    def test_no_sign_is_free(self) -> None:
        self.assertFalse(any(not term for terms in logic.SIGN_TERMS.values() for term in terms))

    def test_signs_live_in_the_start_region(self) -> None:
        self.assertEqual(logic.START_REGION, logic.SIGN_REGION)

    def test_jungle_teleport_is_jungle_start(self) -> None:
        self.assertEqual("Jungle Start tp", logic.NODES[logic.TELEPORT_PADS[logic.JUNGLE_TELEPORT_PAD]].name)


class ESATestBase(WorldTestBase):
    """Shared base. Subclasses that set options also run AP's default reachability and fill tests."""

    game = "Environmental Station Alpha"

    def collect_event(self, name: str) -> None:
        """Events are locked items on their own location; collect_by_name only searches the itempool."""
        self.collect(self.multiworld.get_location(name, self.player).item)

    def reach_without(self, location: str, *missing: str) -> bool:
        """Everything but ``missing`` in a fresh state, events included."""
        state = CollectionState(self.multiworld)
        self.collect_all_but(missing, state)
        return self.multiworld.get_location(location, self.player).can_reach(state)


class TestRules(ESATestBase):
    """Rule-level checks on a generated world. Also runs AP's default fill tests with this option set."""

    options = {"start_with_jump_booster": False}

    def test_pillar_1_needs_more_than_jump(self) -> None:
        """Seed 91618731083770012827 put Pillar 1 Monitor in sphere 2 with only the Jump Booster."""
        self.collect_by_name("Jump Booster")
        self.assertFalse(self.can_reach_location("Pillar 1 Monitor (14-08)"))
        self.collect_by_name("Dash Booster V")
        self.assertTrue(self.can_reach_location("Pillar 1 Monitor (14-08)"))

    def test_jump_alone_reaches_no_movement_upgrade(self) -> None:
        """The opening that seed got stuck in: Charge, V-Dash, Hookshot and Supercharge all stay out of reach."""
        self.collect_by_name("Jump Booster")
        self.assertTrue(self.can_reach_location("Health Pack Beetle Spot (15-12)"))
        self.assertTrue(self.can_reach_location("Hookshot Spot (26-10)"))
        for location in ("Diskette Caves Spot (18-10)", "Diskette Depthsmaze Spot (17-16)",
                         "Pillar 1 Monitor (14-08)", "Dash Booster V Spot (11-07)"):
            with self.subTest(location=location):
                self.assertFalse(self.can_reach_location(location))

    def test_gate_monitors_need_power(self) -> None:
        from ..rules import GATE_MONITORS
        self.collect_all_but("Power")
        for location in GATE_MONITORS:
            with self.subTest(location=location, power=False):
                self.assertFalse(self.can_reach_location(location))
        self.collect_by_name("Power")
        for location in GATE_MONITORS:
            with self.subTest(location=location, power=True):
                self.assertTrue(self.can_reach_location(location))

    def test_mainframe_shortcut_needs_class_a(self) -> None:
        entrance = f"{_region('54')} -> {_region('85')}"
        self.collect_by_name(["Jump Booster", "Hookshot", "Dash Booster V"])
        self.assertTrue(self.can_reach_region(_region("54")))
        self.assertFalse(self.can_reach_entrance(entrance))
        self.collect_event("Class A Unlocked")
        self.assertTrue(self.can_reach_entrance(entrance))

    def test_gold_keycard_gates_its_own_vanilla_spot(self) -> None:
        self.collect_all_but("Gold Keycard")
        self.assertFalse(self.can_reach_location("Dash Booster X Spot (22-12)"))
        self.assertFalse(self.can_reach_location("Diskette Ship Spot (25-19)"))

    def test_supercharge_module_needs_heat_suit(self) -> None:
        self.collect_all_but("Heat-Resistant Suit")
        self.assertFalse(self.can_reach_location("Supercharge Module Spot (28-15)"))

    def test_teleport_access_gates_sandrock_jungle_and_temple(self) -> None:
        gated = ("Diskette SandMid Spot (10-14)", "Dash Booster H Spot (05-03)", "Triple Shot Spot (15-04)", "Diskette Jungle Spot (17-00)",
                 "Diskette TempleLeft Spot (23-07)", "Diskette TempleTall Spot (29-03)", "Key Temple Spot (22-02)")
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
        gated = {"Diskette SandMid Spot (10-14)", "Dash Booster H Spot (05-03)", "Triple Shot Spot (15-04)", "Diskette Jungle Spot (17-00)",
                 "Diskette TempleLeft Spot (23-07)", "Diskette TempleTall Spot (29-03)", "Key Temple Spot (22-02)"}
        for seed in range(5):
            with self.subTest(seed=seed):
                self.world_setup(seed)
                distribute_items_restrictive(self.multiworld)
                spot = self.multiworld.find_item("Teleport Access", self.player)
                self.assertNotIn(spot.name, gated)

    def test_jump_booster_is_in_the_pool(self) -> None:
        self.assertIn("Jump Booster", {item.name for item in self.multiworld.itempool})
        self.assertNotIn("Jump Booster", {item.name for item in self.multiworld.precollected_items[self.player]})


class TestSignRules(ESATestBase):
    """The code spots on a generated world, item by item from the notes."""

    options = {"start_with_jump_booster": False, "include_signs": True}

    def test_all_signs_exist_in_the_start_region(self) -> None:
        for name in SIGN_LOCATIONS:
            with self.subTest(sign=name):
                self.assertEqual(logic.START_REGION, self.multiworld.get_location(name, self.player).parent_region.name)

    def test_rough_map_is_progression_now(self) -> None:
        self.assertTrue(self.world.create_item("Rough Map").advancement)

    def test_sign_1_charge_and_a_way_up(self) -> None:
        self.collect_by_name(["Charge Shot", "Jump Booster"])
        self.assertFalse(self.can_reach_location("Sign Location 1 (03-08)"))
        self.collect_by_name("Hookshot")
        self.assertTrue(self.can_reach_location("Sign Location 1 (03-08)"))

    def test_sign_3_needs_every_piece_of_the_gauntlet(self) -> None:
        for missing in ("Power", "Gold Keycard", "Triple Shot", "Dash Booster V", "Dash Booster H", "Dash Booster X"):
            with self.subTest(missing=missing):
                self.assertFalse(self.reach_without("Sign Location 3 (Planet Surface)", missing))
        self.assertTrue(self.reach_without("Sign Location 3 (Planet Surface)"))

    def test_sign_7_needs_all_four_gates(self) -> None:
        for gate in ("Gate Alpha", "Gate Beta", "Gate Gamma", "Gate Delta"):
            with self.subTest(missing=gate):
                self.assertFalse(self.reach_without("Sign Location 7 (15-22)", gate))

    def test_sign_9_needs_map_keys_and_heat_suit(self) -> None:
        for missing in ("Rough Map", "Key Mwyah", "Key Fire", "Key Caves", "Key Temple", "Heat-Resistant Suit",
                        "Power", "Dash Booster V", "Dash Booster X"):
            with self.subTest(missing=missing):
                self.assertFalse(self.reach_without("Sign Location 9 (Death-Laser Room)", missing))

    def test_sign_12_needs_the_jungle_teleporter(self) -> None:
        self.assertFalse(self.reach_without("Sign Location 12 (18-01)", "Teleport Access"))
        self.assertTrue(self.reach_without("Sign Location 12 (18-01)"))

    def test_pillar_needs_every_sign_item_and_its_route(self) -> None:
        """The pillar check itself does not need the MWYA Pillar item: typing "mwya" works without it."""
        self.assertEqual(logic.START_REGION, self.multiworld.get_location(MAZE_PILLAR, self.player).parent_region.name)
        self.collect_by_name(SIGN_ITEMS + ["Charge Shot", "Dash Booster V"])
        self.assertTrue(self.can_reach_location(MAZE_PILLAR))
        self.assertTrue(self.reach_without(MAZE_PILLAR, PILLAR_ITEM))
        self.assertFalse(self.reach_without(MAZE_PILLAR, "Sign 7"))
        self.assertFalse(self.reach_without(MAZE_PILLAR, "Charge Shot"))
        self.assertFalse(self.reach_without(MAZE_PILLAR, "Jump Booster", "Dash Booster V"))
        self.assertTrue(self.reach_without(MAZE_PILLAR, "Jump Booster"))

    def test_vxdash_alone_reaches_signs_6_13_and_14(self) -> None:
        self.collect_by_name(["Dash Booster V", "Dash Booster X"])
        for name in ("Sign Location 6 (12-18)", "Sign Location 13 (28-08)", "Sign Location 14 (25-00)"):
            with self.subTest(sign=name):
                self.assertTrue(self.can_reach_location(name))
        self.assertFalse(self.can_reach_location("Sign Location 12 (18-01)"))


class TestSignsOff(ESATestBase):
    """Default: no code spots, no Sign items."""

    options = {"start_with_jump_booster": False}

    def test_no_code_spot_locations(self) -> None:
        names = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertEqual(set(), names & set(CODE_SPOT_LOCATIONS))

    def test_no_sign_items(self) -> None:
        self.assertEqual(set(), {item.name for item in self.multiworld.itempool} & {*SIGN_ITEMS, PILLAR_ITEM})

    def test_slot_data_says_so(self) -> None:
        self.assertFalse(self.world.fill_slot_data()["include_signs"])


class TestSignsAsExtraChecks(ESATestBase):
    """include_signs without the maze goal: 14 more checks and 14 more items. Sign items are progression (they gate
    the pillar check), the MWYA Pillar item is only useful (the labyrinth holds no check)."""

    options = {"start_with_jump_booster": False, "include_signs": True, "goal": "postgame"}

    def test_code_spot_locations_and_items(self) -> None:
        names = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertLessEqual(set(CODE_SPOT_LOCATIONS), names)
        pool = [item for item in self.multiworld.itempool if item.name in SIGN_ITEMS]
        self.assertEqual(sorted(SIGN_ITEMS), sorted(item.name for item in pool))
        self.assertTrue(all(item.advancement for item in pool))

    def test_pillar_item_is_in_the_pool_as_useful(self) -> None:
        pillar = [item for item in self.multiworld.itempool if item.name == PILLAR_ITEM]
        self.assertEqual(1, len(pillar))
        self.assertFalse(pillar[0].advancement)
        self.assertTrue(pillar[0].useful)

    def test_code_spots_bring_as_many_items_as_checks(self) -> None:
        """14 locations, 14 items: the code spots add no Data Fragments."""
        added = [item for item in self.multiworld.itempool if item.name in (*SIGN_ITEMS, PILLAR_ITEM)]
        self.assertEqual(len(CODE_SPOT_LOCATIONS), len(added))


class TestGoalMaze(ESATestBase):
    options = {"goal": "maze", "start_with_jump_booster": False}

    def test_maze_forces_the_signs_in(self) -> None:
        self.assertTrue(self.world.options.include_signs)
        self.assertTrue(self.world.fill_slot_data()["include_signs"])
        names = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertLessEqual(set(SIGN_LOCATIONS), names)

    def test_sign_and_pillar_items_are_progression(self) -> None:
        pool = [item for item in self.multiworld.itempool if item.name in (*SIGN_ITEMS, PILLAR_ITEM)]
        self.assertEqual(len(SIGN_ITEMS) + 1, len(pool))
        self.assertTrue(all(item.advancement for item in pool))

    def test_needs_every_sign_and_the_pillar_item(self) -> None:
        self.collect_by_name(SIGN_ITEMS[:-1] + [PILLAR_ITEM, "Charge Shot", "Jump Booster"])
        self.assertBeatable(False)
        self.collect_by_name(SIGN_ITEMS[-1])
        self.assertBeatable(True)
        self.remove_by_name(PILLAR_ITEM)
        self.assertBeatable(False)
        self.collect_by_name(PILLAR_ITEM)
        self.remove_by_name("Charge Shot")
        self.assertBeatable(False)


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
