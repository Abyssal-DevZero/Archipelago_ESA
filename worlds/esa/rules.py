"""Turns the parsed logic expressions into rule_builder rules.
"""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING

from rule_builder.rules import Has, HasAll, HasGroupUnique, Rule
from .data import MAZE_PILLAR, PILLAR_ITEM, SIGN_ITEMS 

from . import logic
from .options import Goal

if TYPE_CHECKING:
    from .world import ESAWorld

def _health(count: int) -> Rule:
    return HasGroupUnique("Health Packs", count=count)
    
#Logic definitions
TOKEN_RULES: dict[str, Rule] = {
    "jump": Has("Jump Booster"),
    "hook": Has("Hookshot"),
    "vdash": Has("Dash Booster V"),
    "hdash": Has("Dash Booster H"),
    "xdash": Has("Dash Booster X"),
    "bike": Has("The Bike"),
    "charge": Has("Charge Shot") | Has("Supercharge Module"),
    "gold": Has("Gold Keycard"),
    "map": Has("Rough Map"), 
    "heatsuit": Has("Heat-Resistant Suit"),
    "propeller": Has("Propeller"),
    "triple": Has("Triple Shot"),
    "jumporv": Has("Jump Booster") | Has("Dash Booster V"),
    "jumporhook": Has("Jump Booster") | Has("Hookshot"),
    "xv": HasAll("Dash Booster V", "Dash Booster X"),
    "xh": HasAll("Dash Booster H", "Dash Booster X"),
    "attack": Has("Charge Shot") | Has("Supercharge Module") | Has("Plasma Shield") | Has("The Bike"),
    "tpaccess": Has("Teleport Access"),
    "jungletp": Has("Teleport Access") & Has(logic.TELEPORT_EVENTS[logic.JUNGLE_TELEPORT_PAD]), 
    "supercharge": Has("Supercharge Module"),
    "switch": Has(logic.FLAG_TOKEN_EVENTS["switch"]),
    "classa": Has(logic.FLAG_TOKEN_EVENTS["classa"]),
    "poweron": Has("Power"),
    "password": Has("Password"),
    "keys": HasGroupUnique("Keys", count=4),
    "gates": HasGroupUnique("Gates", count=4),
    "pillars": HasGroupUnique("Pillars", count=4),
    "disks": HasGroupUnique("Diskettes", count=12),
    "lavaswim1": (_health(4) & (Has("Propeller") | Has("The Bike"))) | _health(6),
    "lavaswim2": (_health(4) & Has("Propeller")) | (_health(2) & Has("The Bike")),
    "acidswim": (_health(4) & Has("Propeller")) | _health(6),
}
 
TELEPORT_ACCESS = Has("Teleport Access")
AI_MAINFRAME_NODE = "116"
CLASS_A_NODE = "115"

BIKE_SPOT = "Bike Spot"
DASH_BOOSTERS = ("Dash Booster H", "Dash Booster V", "Dash Booster X")
GATE_MONITORS = (
    "Gate Alpha Monitor (11-19)",
    "Gate Beta Monitor (19-19)",
    "Gate Gamma Monitor (11-20)",
    "Gate Delta Monitor (19-20)",
)
def base_game() -> Rule:
    """Defeat the virus: Power, all four Gates, and Class A unlocked."""
    return (
        Has("Power")
        & HasGroupUnique("Gates", count=4)
        & Has(logic.FLAG_TOKEN_EVENTS["classa"])
    )

def rule_for_term(term: frozenset[str]) -> Rule | None:
    """AND the tokens of one product together. An empty product is free passage."""
    if not term:
        return None
    try:
        rules = [TOKEN_RULES[token] for token in sorted(term)]
    except KeyError as error:
        raise KeyError(
            f"logic uses token {error.args[0]!r}, which rules.py does not define"
        ) from error
    return reduce(lambda left, right: left & right, rules)

def rule_for_edge(edge: logic.Edge) -> Rule | None:
    """OR the products together. Returns None when the edge is free."""
    return rule_for_terms(edge.terms)
    
def rule_for_terms(terms: tuple[frozenset[str], ...]) -> Rule | None:
    """OR the products together. Returns None when one of them is free."""
    if any(not term for term in terms):
        return None
    return reduce(lambda left, right: left | right, [rule_for_term(term) for term in terms])

def set_all_rules(world: ESAWorld) -> None:
    set_all_entrance_rules(world)
    set_gate_monitor_rules(world)
    if world.signs_included:
        set_sign_rules(world)
    set_completion_rule(world)
    set_bike_spot_rule(world)

def set_all_entrance_rules(world: ESAWorld) -> None:
    for edge in logic.EDGES:
        rule = rule_for_edge(edge)
        if rule is not None:
            world.set_rule(world.get_entrance(edge.name), rule)
 
    for pad_id, pad_node in logic.TELEPORT_PADS.items():
        pad_region = logic.NODES[pad_node].region
        world.set_rule(
            world.get_entrance(f"{pad_region} -> {logic.TELEPORT_HUB_REGION}"),
            TELEPORT_ACCESS,
        )
        world.set_rule(
            world.get_entrance(f"{logic.TELEPORT_HUB_REGION} -> {pad_region}"),
            TELEPORT_ACCESS & Has(logic.TELEPORT_EVENTS[pad_id]),
        )
        
def set_bike_spot_rule(world: ESAWorld) -> None:
    """Excluding the bike from having any advancement items when picking the normal final_boss ending
    """
    location = world.get_location(BIKE_SPOT)
    world.set_rule(location, base_game())
    if world.options.goal != Goal.option_postgame:
        location.item_rule = lambda item: not item.advancement
        
def set_gate_monitor_rules(world: ESAWorld) -> None:
    """Puts Power before Gates in logic"""
    for name in GATE_MONITORS:
        world.set_rule(world.get_location(name), TOKEN_RULES["poweron"])
        
def maze_pillar() -> Rule:
    """MWYA Pillar check: every Sign item received (the real mark it checks) and the route from the notes."""
    return HasAll(*SIGN_ITEMS) & rule_for_terms(logic.MAZE_PILLAR_TERMS)

def set_sign_rules(world: ESAWorld) -> None:
    """Code spots: item rules straight from the notes, no graph behind them. The MWYA Pillar with them."""
    for name, terms in logic.SIGN_TERMS.items():
        rule = rule_for_terms(terms)
        if rule is not None:
            world.set_rule(world.get_location(name), rule)
    world.set_rule(world.get_location(MAZE_PILLAR), maze_pillar())

def maze_ending() -> Rule:
    """Sets all Signs and MWYA Pillar as requirements."""
    return HasAll(*SIGN_ITEMS, PILLAR_ITEM) & rule_for_terms(logic.MAZE_PILLAR_TERMS)

def set_completion_rule(world: ESAWorld) -> None:
    if world.options.goal == Goal.option_maze:
        world.set_completion_rule(maze_ending())    
    elif world.options.goal == Goal.option_postgame:
        # Second ending: defeat Mwyah. The Dash Boosters are required on top so the randomizer has to put all three in reach before the goal.
        world.set_completion_rule(
            base_game()
            & HasGroupUnique("Pillars", count=4)
            & HasAll(*DASH_BOOSTERS)
        )
    else:
        # First ending: defeat the virus
        world.set_completion_rule(base_game())
