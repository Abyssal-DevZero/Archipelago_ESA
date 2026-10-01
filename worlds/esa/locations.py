"""Locations live in the node region that holds them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Location

from . import items, logic
from .data import LOCATION_NAME_TO_ID

if TYPE_CHECKING:
    from .world import ESAWorld


class ESALocation(Location):
    game = "Environmental Station Alpha"


def create_all_locations(world: ESAWorld) -> None:
    create_regular_locations(world)
    create_events(world)


def create_regular_locations(world: ESAWorld) -> None:
    for node_id, location_name in logic.ITEM_NODES.items():
        region = world.get_region(logic.NODES[node_id].region)
        region.add_locations({location_name: LOCATION_NAME_TO_ID[location_name]}, ESALocation)


def create_events(world: ESAWorld) -> None:
    """The only events left in the world.

    Thirteen teleporter finds
    """
    for pad_id, find_node in logic.TELEPORT_FINDS.items():
        event_name = logic.TELEPORT_EVENTS[pad_id]
        region = world.get_region(logic.NODES[find_node].region)
        region.add_event(
            event_name, event_name,
            location_type=ESALocation, item_type=items.ESAItem,
        )
    for token, event_name in logic.FLAG_TOKEN_EVENTS.items():
        region = world.get_region(logic.NODES[logic.FLAG_GRANTS[token]].region)
        region.add_event(
            event_name, event_name,
            location_type=ESALocation, item_type=items.ESAItem,
        )
