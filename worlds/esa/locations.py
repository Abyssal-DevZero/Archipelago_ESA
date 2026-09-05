from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import ItemClassification, Location

from . import items

if TYPE_CHECKING:
    from .world import ESAWorld


class ESALocation(Location):
    game = "Environmental Station Alpha"

LOCATION_NAME_TO_ID = {
    "Jump Booster Spot": 1,
    "Hookshot Spot": 2,
    "Teleport Access Spot": 3,
    "Propeller Spot": 4,
    "Charge Shot Spot": 5,
    "Dash Booster H Spot": 6,
    "Heat-Resistant suit Spot": 7,
    "Gold Keycard Spot": 8,
    "Dash Booster V Spot": 9,
    "Rough Map Spot": 10,
    "Triple Shot Spot": 11,
    "Plasma Shield Spot": 12,
    "Supercharge Module Spot": 13,
    "Dash Booster X Spot": 14,
    "Bike Spot": 15,
  
    "Health Pack Beetle Spot": 21,
    "Health Pack SandTop Spot": 22,
    "Health Pack SandBottom Spot": 23,
    "Health Pack FireLow Spot": 24,
    "Health Pack FireHigh Spot": 25,
    "Health Pack Temple Spot": 26,
    "Health Pack Ship Spot": 27,
    "Health Pack Water Spot": 28,

    "Diskette Water Spot": 31,
    "Diskette Depthsmaze Spot": 32,
    "Diskette Caves Spot": 33,
    "Diskette Jungle Spot": 34,
    "Diskette TempleLeft Spot": 35,
    "Diskette TempleTall Spot": 36,
    "Diskette FireLava Spot": 37,
    "Diskette FireTop Spot": 38,
    "Diskette Security Spot": 39,
    "Diskette SandBot Spot": 40,
    "Diskette SandMid Spot": 41,
    "Diskette Ship Spot": 42,
}
#Doing Region Locations as dictionary instead of old method
REGION_LOCATIONS: dict[str, list[str]] = {
    "Cave_Complex": [
        "Jump Booster Spot", "Dash Booster V Spot", "Rough Map Spot",
        "Health Pack Beetle Spot", "Diskette Caves Spot",
    ],
    "The Depths": [
        "Diskette Depthsmaze Spot",
    ],
    "The Volcanic Sector": [
        "Hookshot Spot", "Heat-Resistant suit Spot", "Supercharge Module Spot",
        "Dash Booster X Spot", "Health Pack FireLow Spot", "Health Pack FireHigh Spot",
        "Diskette FireLava Spot", "Diskette FireTop Spot",
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
    ],
    "The Derelict Ship": [
        "Gold Keycard Spot", "Bike Spot", "Health Pack Ship Spot", "Diskette Ship Spot",
    ],
    "The Control Hub": [
        "Teleport Access Spot", "Diskette Security Spot",
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
