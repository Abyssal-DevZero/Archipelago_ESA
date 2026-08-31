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

def get_location_names_with_ids(location_names: list[str]) -> dict[str, int | None]:
    return {location_name: LOCATION_NAME_TO_ID[location_name] for location_name in location_names}


def create_all_locations(world: ESAWorld) -> None:
    create_regular_locations(world)
    create_events(world)


def create_regular_locations(world: ESAWorld) -> None:
    cave_complex = world.get_region("Cave_Complex")
    depths = world.get_region("The Depths")
    volcanic_sector = world.get_region("The Volcanic Sector")
    underwater_sector = world.get_region("The Underwater Sector")
    sandrock_sector = world.get_region("The Sandrock Sector")
    jungle_sector = world.get_region("The Jungle Sector")
    temple= world.get_region("The Temple")
    derelict_ship = world.get_region("The Derelict Ship")
    control_hub = world.get_region("The Control Hub")
    ai_mainframe = world.get_region("The A.I. Mainframe")

    cave_complex_locations = get_locations_names_with_ids(
      ["Health Pack Beetle", "Jump Booster Spot","Dash Booster V Spot", "Diskette Caves", "Rough Map Spot"]
    )
    cave_complex.add_locations(cave_complex_locations, ESALocation)
  
    depths_locations = get_locations_names_with_ids(
      ["Diskette Depthsmaze"]
    )
    depths.add_locations(depths_locations, ESALocation)

    volcanic_sector_locations = get_locations_names_with_ids(
      ["Heat-Resistant suit Spot", "Diskette FireTop", "Hookshot", "Health Pack FireLow", "Health Pack FireHigh", "Dash Booster X Spot", "Diskette FireLava", "Supercharge Module Spot"]
    )
    volcanic_sector.add_locations (volcanic_sector_locations, ESALocation)

    underwater_sector_locations = get_locations_names_with_ids(
      ["Plasma Shield Spot", "Charge Shot Spot", "Propeller Spot", "Diskette Water", "Health Pack Water"]
    )
    underwater_sector.add_locations(underwater_sector_locations, ESALocation)

    sandrock_sector_locations = get_locations_names_with_ids(
      ["Health Pack SandTop", "Health Pack SandBottom", "Diskette SandBot", "Diskette SandMid"]
    )
    sandrock_sector.add_locations(sandrock_sector_locations, ESALocation)

    jungle_sector_locations = get_locations_names_with_ids(
      ["Triple Shot Spot", "Dash Booster H Spot", "Diskette Jungle"]
    )
    jungle_sector.add_locations(jungle_sector_locations, ESALocation)

    temple_locations = get_locations_names_with_ids(
      ["Diskette TempleLeft", "Diskette TempleTall", "Health Pack Temple"]
    )
    temple.add_locations(temple_locations, ESALocation)

    derelict_ship_locations = get_locations_names_with_ids(
      ["Diskette Ship", "Bike Spot", "Gold Keycard Spot", "Health Pack Ship"]
    )
    derelict_ship.add_locations(derelict_ship_locations, ESALocation)


#Event for Endbosses AI Mainframe and Mywah when Postgame is included
def create_events(world: ESAWorld) -> None:
    ai_mainframe = world.get_region("The A.I. Mainframe")
    ai_mainframe.add_event(
        "A.I. Mainframe Boss Defeated", "A.I. Mainframe Boss Defeated",
        location_type=ESALocation, item_type=items.ESAItem,
    )

    if world.options.postgame:
        forlorn_planet = world.get_region("The Forlorn Planet")
        forlorn_planet.add_event(
            "Mwyah Defeated", "Mwyah Defeated",
            location_type=ESALocation, item_type=items.ESAItem,
        )
