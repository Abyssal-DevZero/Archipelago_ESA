"""Turns the parsed logic expressions into rule_builder rules.

Every requirement in ESA's logic is an edge requirement, so there are no
location rules here at all: a location is reachable exactly when its node's
region is
"""
from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING

from rule_builder.rules import CanReachRegion, Has, HasAll, HasGroupUnique, Rule

from . import logic
from .options import Goal

if TYPE_CHECKING:
    from .world import ESAWorld

# One entry per token the ini can put on an edge.

TOKEN_RULES: dict[str, Rule] = {
    "jump": Has("Jump Booster"),
    "hook": Has("Hookshot"),
    "vdash": Has("Dash Booster V"),
    "hdash": Has("Dash Booster H"),
    "xdash": Has("Dash Booster X"),
    "bike": Has("The Bike"),
    "charge": Has("Charge Shot"),
    "gold": Has("Gold Keycard"),
    "heatsuit": Has("Heat-Resistant Suit"),
    "propeller": Has("Propeller"),
    "triple": Has("Triple Shot"),
    "jumporv": Has("Jump Booster") | Has("Dash Booster V"),
    "jumporhook": Has("Jump Booster") | Has("Hookshot"),
    "xv": HasAll("Dash Booster V", "Dash Booster X"),
    "xh": HasAll("Dash Booster H", "Dash Booster X"),
    "attack": Has("Charge Shot"),
    "supercharge": Has("Supercharge Module"),
    "switch": Has("Propeller"),
    "poweron": Has("Power"),
    "gates": HasGroupUnique("Gates", count=4),
    "pillars": HasGroupUnique("Pillars", count=4),
    "disks": HasGroupUnique("Diskettes", count=12),
    "lavaswim1": HasGroupUnique("Health Packs", count=logic.DAMAGE_BOOST_HEALTH_PACKS),
    "lavaswim2": HasGroupUnique("Health Packs", count=logic.DAMAGE_BOOST_HEALTH_PACKS),
    "acidswim": HasGroupUnique("Health Packs", count=logic.DAMAGE_BOOST_HEALTH_PACKS),
}
 
TELEPORT_ACCESS = Has("Teleport Access")
AI_MAINFRAME_NODE = "116"

def rule_for_term(term: frozenset[str]) -> Rule | None:
    """AND the tokens of one product together. An empty product is free passage."""
    if not term:
        return None
    try:
        rules = [TOKEN_RULES[token] for token in sorted(term)]
    except KeyError as error:
        raise KeyError(
            f"glitchlesslogic.ini uses token {error.args[0]!r}, which rules.py does not define"
        ) from error
    return reduce(lambda left, right: left & right, rules)

def rule_for_edge(edge: logic.Edge) -> Rule | None:
    """OR the products together. Returns None when the edge is free."""
    if edge.is_free:
        return None
    term_rules = [rule_for_term(term) for term in edge.terms]
    return reduce(lambda left, right: left | right, term_rules)

def set_all_rules(world: ESAWorld) -> None:
    set_all_entrance_rules(world)
    set_completion_condition(world)

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

def set_completion_condition(world: ESAWorld) -> None:
    beat_the_mainframe = CanReachRegion(logic.NODES[AI_MAINFRAME_NODE].region)
 
    if world.options.goal == Goal.option_postgame:
        # Setting goal to four pillars for now even tho it should include beating Mwyah
        world.set_completion_condition(beat_the_mainframe & HasGroupUnique("Pillars", count=4))
    else:
        world.set_completion_condition(beat_the_mainframe)
