"""Builds one Region per logic node, plus the teleporter hub.

Entrances are created here without rules; rules.py attaches them afterwards by
entrance name, which is why edge names have to be unique and stable
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Region

from . import logic

if TYPE_CHECKING:
    from .world import ESAWorld


def create_and_connect_regions(world: ESAWorld) -> None:
    create_all_regions(world)
    connect_regions(world)


def create_all_regions(world: ESAWorld) -> None:
    for region_name in logic.REGION_NAMES:
        world.multiworld.regions.append(Region(region_name, world.player, world.multiworld))

    world.multiworld.regions.append(
        Region(logic.TELEPORT_HUB_REGION, world.player, world.multiworld)
    )


def connect_regions(world: ESAWorld) -> None:
    for edge in logic.EDGES:
        source = world.get_region(logic.NODES[edge.source].region)
        target = world.get_region(logic.NODES[edge.target].region)
        source.connect(target, edge.name)

    connect_teleport_network(world)


def connect_teleport_network(world: ESAWorld) -> None:
    """Every teleporter leads into the hub; the hub leads back out to any teleporter already found.

    Without this, Sandrock tp and the Diskette behind it are unreachable with a
    full inventory, because nothing else leads there
    """
    hub = world.get_region(logic.TELEPORT_HUB_REGION)

    for pad_node in logic.TELEPORT_PADS.values():
        pad = world.get_region(logic.NODES[pad_node].region)
        pad.connect(hub, f"{pad.name} -> {hub.name}")
        hub.connect(pad, f"{hub.name} -> {pad.name}")
