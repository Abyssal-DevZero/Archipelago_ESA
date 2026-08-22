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

def create_events(world: APQuestWorld) -> None:
    # Sometimes, the player may perform in-game actions that allow them to progress which are not related to Items.
    # In our case, the player must press a button in the top left room to open the final boss door.
    # AP has something for this purpose: "Event locations" and "Event items".
    # An event location is no different than a regular location, except it has the address "None".
    # It is treated during generation like any other location, but then it is discarded.
    # This location cannot be "sent" and its item cannot be "received", but the item can be used in logic rules.
    # Since we are creating more locations and adding them to regions, we need to grab those regions again first.
    top_left_room = world.get_region("Top Left Room")
    final_boss_room = world.get_region("Final Boss Room")

    # One way to create an event is simply to use one of the normal methods of creating a location.
    button_in_top_left_room = APQuestLocation(world.player, "Top Left Room Button", None, top_left_room)
    top_left_room.locations.append(button_in_top_left_room)

    # We then need to put an event item onto the location.
    # An event item is an item whose code is "None" (same as the event location's address),
    # and whose classification is "progression". Item creation will be discussed more in items.py.
    # Note: Usually, items are created in world.create_items(), which for us happens in items.py.
    # However, when the location of an item is known ahead of time (as is the case with an event location/item pair),
    # it is common practice to create the item when creating the location.
    # Since locations also have to be finalized after world.create_regions(), which runs before world.create_items(),
    # we'll create both the event location and the event item in our locations.py code.
    button_item = items.APQuestItem("Top Left Room Button Pressed", ItemClassification.progression, None, world.player)
    button_in_top_left_room.place_locked_item(button_item)

    # A way simpler way to do create an event location/item pair is by using the region.create_event helper.
    # Luckily, we have another event we want to create: The Victory event.
    # We will use this event to track whether the player can win the game.
    # The Victory event is a completely optional abstraction - This will be discussed more in set_rules().
    final_boss_room.add_event(
        "Final Boss Defeated", "Victory", location_type=APQuestLocation, item_type=items.APQuestItem
    )

    # If you create all your regions and locations line-by-line like this,
    # the length of your create_regions might get out of hand.
    # Many worlds use more data-driven approaches using dataclasses or NamedTuples.
    # However, it is worth understanding how the actual creation of regions and locations works,
    # That way, we're not just mindlessly copy-pasting! :)
