from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Location
from .data import LOCATION_NAME_TO_ID
from . import items
from .options import Goal
if TYPE_CHECKING:
    from .world import ESAWorld


class ESALocation(Location):
    game = "Environmental Station Alpha"

#Doing Region Locations as dictionary instead of old method
REGION_LOCATIONS: dict[str, list[str]] = {
    "Cave_Complex": [
        "Jump Booster Spot", "Dash Booster V Spot", "Rough Map Spot",
        "Health Pack Beetle Spot", "Diskette Caves Spot",
        "Key Caves Spot",
        "Pillar 1 Monitor", "Pillar 3 Monitor", "Pillar 4 Monitor",
    ],
    "The Depths": [
        "Diskette Depthsmaze Spot",
        "Key Mwyah Spot",
    ],
    "The Volcanic Sector": [
        "Hookshot Spot", "Heat-Resistant suit Spot", "Supercharge Module Spot",
        "Dash Booster X Spot", "Health Pack FireLow Spot", "Health Pack FireHigh Spot",
        "Diskette FireLava Spot", "Diskette FireTop Spot",
        "Key Fire Spot",
        "Pillar 2 Monitor",
    ],
    "The Underwater Sector": [
        "Charge Shot Spot", "Propeller Spot", "Plasma Shield Spot",
        "Health Pack Water Spot", "Diskette Water Spot",
    ],
    "The Sandrock Sector": [
        "Health Pack SandTop Spot", "Health Pack SandBottom Spot",
        "Diskette SandMid Spot", "Diskette SandBot Spot",
    ],
    "The Jungle Sector": [
        "Triple Shot Spot", "Dash Booster H Spot", "Diskette Jungle Spot",
    ],
    "The Temple": [
        "Health Pack Temple Spot", "Diskette TempleLeft Spot", "Diskette TempleTall Spot",
        "Key Temple Spot",
    ],
    "The Derelict Ship": [
        "Gold Keycard Spot", "Bike Spot", "Health Pack Ship Spot", "Diskette Ship Spot",
    ],
    "The Control Hub": [
        "Teleport Access Spot", "Diskette Security Spot",
        "Power Monitor",
        "Gate Alpha Monitor",
        "Gate Beta Monitor",
        "Gate Gamma Monitor",   
        "Gate Delta Monitor",
    ],
    "The A.I. Mainframe": [],

}

def get_location_names_with_ids(location_names: list[str]) -> dict[str, int | None]:
    return {location_name: LOCATION_NAME_TO_ID[location_name] for location_name in location_names}


def create_all_locations(world: ESAWorld) -> None:
    create_regular_locations(world)
    create_events(world)


def create_regular_locations(world: ESAWorld) -> None:
    for region_name, location_names in REGION_LOCATIONS.items():
        if not location_names:
            continue
        region = world.get_region(region_name)
        region.add_locations(get_location_names_with_ids(location_names), ESALocation)

#Event for Endbosses AI Mainframe and Mywah when Postgame is included
def create_events(world: ESAWorld) -> None:
    ai_mainframe = world.get_region("The A.I. Mainframe")
    ai_mainframe.add_event(
        "A.I. Mainframe Boss Defeated", "A.I. Mainframe Boss Defeated",
        location_type=ESALocation, item_type=items.ESAItem,
    )

    if world.options.goal == Goal.option_postgame:
        forlorn_planet = world.get_region("The Forlorn Planet")
        forlorn_planet.add_event(
            "Mwyah Defeated", "Mwyah Defeated",
            location_type=ESALocation, item_type=items.ESAItem,
        )
