from __future__ import annotations
 
from typing import TYPE_CHECKING
 
from rule_builder.rules import Has, HasAll
 
if TYPE_CHECKING:
    from .world import ESAWorld

from .options import Goal
 
# player usually can't leave Cave_Complex without any of those Items, so this way it should force the randomizer to spawn either on in the cave_complex
CAN_TRAVERSE = Has("Jump Booster") | Has("Dash Booster V")

#Probably a neater way than just listing every entrance again
TRAVERSAL_ENTRANCES = [
    "Cave Complex to Depths",
    "Cave Complex to Sandrock Sector",
    "Cave Complex to Underwater Sector",
    "Cave Complex to Jungle Sector",
    "Cave Complex to A.I. Mainframe",
    "Cave Complex to Derelict Ship",
    "Depths to Cave_Complex",
    "The Depths to Volcanic Sector",
    "Depths to Control Hub",
    "Depths to Sandrock Sector",
    "Volcanic Sector to Depths",
    "Volcanic Sector to AI Mainframe",
    "Volcanic Sector to Temple",
    "Underwater Sector to Cave_Complex",
    "Underwater Sector to Sandrock Sector",
    "Sandrock Sector to Cave_Complex",
    "Sandrock Sector to Depths",
    "Sandrock Sector to Control Hub",
    "Sandrock Sector to Underwater Sector",
    "Jungle Sector to Cave_Complex",
    "Jungle Sector to AI Mainframe",
    "Jungle Sector to Temple",
    "Temple to AI Mainframe",
    "Temple to Volcanic Sector",
    "Temple to Jungle Sector",
    "Derelict Ship to Cave_Complex",
    "Control Hub to Depths",
    "Control Hub to Sandrock Sector",
    "AI Mainframe to Cave_Complex",
    "AI Mainframe to Volcanic Sector",
    "AI Mainframe to Jungle Sector",
    "AI Mainframe to Temple",
]
#Location Rules for all Item spots in the game (Not including event spots yet)
LOCATION_RULES = {}
 
LOCATION_RULES["Hookshot Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Teleport Access Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Propeller Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Charge Shot Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Dash Booster H Spot"] = (
        Has("Dash Booster V")
        | HasAll("Hookshot", "Jump Booster")
        | HasAll("Charge Shot", "Gold Keycard", "Dash Booster H", "Jump Booster")
    )
LOCATION_RULES["Heat-Resistant suit Spot"] = (
        HasAll("Hookshot", "Dash Booster V")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Jump Booster")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Dash Booster V")
        | HasAll("Charge Shot", "Triple Shot", "Dash Booster V")
        | HasAll("Gold Keycard", "Dash Booster H", "Jump Booster")
        | HasAll("Gold Keycard", "Dash Booster H", "Dash Booster V")
        | HasAll("Dash Booster H", "Hookshot", "Jump Booster")
        | HasAll("Dash Booster H", "Jump Booster", "Dash Booster V")
        | HasAll("Dash Booster H", "Triple Shot", "Dash Booster V")
        | HasAll("Jump Booster", "Triple Shot", "Dash Booster V")
    )
LOCATION_RULES["Gold Keycard Spot"] = (
        HasAll("Hookshot", "Dash Booster V")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Jump Booster")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Dash Booster V")
        | HasAll("Charge Shot", "Triple Shot", "Dash Booster V")
        | HasAll("Gold Keycard", "Dash Booster H", "Jump Booster")
        | HasAll("Gold Keycard", "Dash Booster H", "Dash Booster V")
        | HasAll("Dash Booster H", "Hookshot", "Jump Booster")
        | HasAll("Dash Booster H", "Jump Booster", "Dash Booster V")
        | HasAll("Dash Booster H", "Triple Shot", "Dash Booster V")
        | HasAll("Jump Booster", "Triple Shot", "Dash Booster V")
    )
LOCATION_RULES["Dash Booster V Spot"] = (
        Has("Gold Keycard")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Triple Shot Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Plasma Shield Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Supercharge Module Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
        | HasAll("Charge Shot", "Dash Booster H")
        | HasAll("Charge Shot", "Hookshot")
    )
LOCATION_RULES["Dash Booster X Spot"] = (
        HasAll("Dash Booster H", "Dash Booster V", "Dash Booster X")
        | HasAll("Gold Keycard", "Hookshot", "Triple Shot", "Dash Booster V")
        | HasAll("Hookshot", "Jump Booster", "Triple Shot", "Dash Booster V")
        | HasAll("The Bike", "Gold Keycard", "Jump Booster", "Triple Shot", "Dash Booster V")
        | HasAll("Gold Keycard", "Dash Booster H", "Jump Booster", "Triple Shot", "Dash Booster V")
    )
LOCATION_RULES["Bike Spot"] = (
        HasAll("Hookshot", "Dash Booster V")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Jump Booster")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Dash Booster V")
        | HasAll("Charge Shot", "Triple Shot", "Dash Booster V")
        | HasAll("Dash Booster H", "Hookshot", "Jump Booster")
        | HasAll("Charge Shot", "Gold Keycard", "Dash Booster H", "Jump Booster")
        | HasAll("Charge Shot", "Gold Keycard", "Dash Booster H", "Dash Booster V")
        | HasAll("Charge Shot", "Dash Booster H", "Jump Booster", "Dash Booster V")
    )
LOCATION_RULES["Health Pack SandTop Spot"] = (
        Has("Dash Booster V")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Health Pack FireLow Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Health Pack Temple Spot"] = (
        HasAll("Charge Shot", "Jump Booster")
        | HasAll("Charge Shot", "Dash Booster V")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Health Pack FireHigh Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
        | HasAll("Charge Shot", "Dash Booster H")
        | HasAll("Charge Shot", "Hookshot")
    )
LOCATION_RULES["Health Pack SandBottom Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Health Pack Ship Spot"] = (
        Has("Dash Booster H")
        | HasAll("Charge Shot", "Dash Booster V")
        | HasAll("Hookshot", "Dash Booster V")
        | HasAll("Jump Booster", "Dash Booster V")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Hookshot", "Jump Booster")
    )
LOCATION_RULES["Health Pack Water Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Diskette Water Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Diskette Depthsmaze Spot"] = (
        Has("Charge Shot")
        | Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Diskette Jungle Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Diskette TempleLeft Spot"] = (
        Has("Dash Booster V")
        | HasAll("Hookshot", "Jump Booster")
        | HasAll("Gold Keycard", "Jump Booster", "Propeller")
        | HasAll("Charge Shot", "Dash Booster H", "Heat-Resistant Suit", "Jump Booster", "Propeller")
    )
LOCATION_RULES["Diskette FireLava Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
        | HasAll("Charge Shot", "Dash Booster H")
        | HasAll("Charge Shot", "Hookshot")
    )
LOCATION_RULES["Diskette TempleTall Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
        | HasAll("Charge Shot", "Dash Booster H", "Heat-Resistant Suit", "Jump Booster")
    )
LOCATION_RULES["Diskette Security Spot"] = Has("Dash Booster V")
LOCATION_RULES["Diskette SandMid Spot"] = (
        Has("Dash Booster V")
        | HasAll("Gold Keycard", "Jump Booster")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Diskette SandBot Spot"] = (
        Has("Dash Booster V")
        | HasAll("Charge Shot", "Hookshot")
        | HasAll("Hookshot", "Jump Booster")
    )
LOCATION_RULES["Diskette FireTop Spot"] = (
        Has("Jump Booster")
        | Has("Dash Booster V")
    )
LOCATION_RULES["Diskette Ship Spot"] = (
        HasAll("Hookshot", "Dash Booster V")
        | HasAll("Gold Keycard", "Dash Booster H", "Jump Booster")
        | HasAll("Gold Keycard", "Dash Booster H", "Dash Booster V")
        | HasAll("Dash Booster H", "Hookshot", "Jump Booster")
        | HasAll("Charge Shot", "Heat-Resistant Suit", "Hookshot", "Jump Booster")
        | HasAll("The Bike", "Gold Keycard", "Jump Booster", "Triple Shot", "Dash Booster V")
        | HasAll("The Bike", "Charge Shot", "Gold Keycard", "Heat-Resistant Suit", "Jump Booster", "Dash Booster V")
    )

 
def set_all_rules(world: ESAWorld) -> None:
    set_all_entrance_rules(world)
    set_all_location_rules(world)
    set_completion_condition(world)
 
 
def set_all_entrance_rules(world: ESAWorld) -> None:
    for entrance_name in TRAVERSAL_ENTRANCES:
        world.set_rule(world.get_entrance(entrance_name), CAN_TRAVERSE)

    # The Derelict Ship needs the Gold Keycard to avoid softlocks
    world.set_rule(
        world.get_entrance("Cave Complex to Derelict Ship"),
        CAN_TRAVERSE & Has("Gold Keycard"),
    )
 
 
def set_all_location_rules(world: ESAWorld) -> None:
    for location_name, rule in LOCATION_RULES.items():
        world.set_rule(world.get_location(location_name), rule)
 
 
def set_completion_condition(world: ESAWorld) -> None:
    world.set_rule(
        world.get_location("A.I. Mainframe Boss Defeated")
    )

    if world.options.goal == Goal.option_postgame:
        world.set_rule(
            world.get_location("Mwyah Defeated"),
            Has("A.I. Mainframe Boss Defeated"),
        )
        world.set_completion_rule(Has("Mwyah Defeated"))
    else:
        world.set_completion_rule(Has("A.I. Mainframe Boss Defeated"))
