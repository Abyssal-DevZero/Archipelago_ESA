from __future__ import annotations
 
from typing import TYPE_CHECKING
 
from rule_builder.rules import Has, HasAll
 
if TYPE_CHECKING:
    from .world import ESAWorld
 
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
 
 
def set_all_rules(world: ESAWorld) -> None:
    set_all_entrance_rules(world)
    set_all_location_rules(world)
    set_completion_condition(world)
 
 
def set_all_entrance_rules(world: ESAWorld) -> None:
    for entrance_name in TRAVERSAL_ENTRANCES:
        world.set_rule(world.get_entrance(entrance_name), CAN_TRAVERSE)
 
 
def set_all_location_rules(world: ESAWorld) -> None:
    world.set_rule(world.get_location("Bike Spot"), Has("Gold Keycard"))
    world.set_rule(
        world.get_location("Dash Booster X Spot"),
        HasAll("Dash Booster H", "Dash Booster V"),
    )
 
 
def set_completion_condition(world: ESAWorld) -> None:
    # Placeholder for now, not the final victory condition
    world.set_completion_rule(
        HasAll("Jump Booster", "Hookshot", "Charge Shot", "Heat-Resistant Suit", "Gold Keycard")
    )
