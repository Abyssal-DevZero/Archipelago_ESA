from __future__ import annotations
from typing import TYPE_CHECKING
from BaseClasses import Item, ItemClassification
if TYPE_CHECKING:
    from .world import ESAWorld

#Import from data.py
from .data import (
    ABILITIES,
    DISKETTES,
    FILLER_ITEM_NAME,
    HEALTH_PACKS,
    ITEM_NAME_TO_ID,
)

#Abilities that open up checks
LOGICAL_ABILITIES = {
    "Jump Booster",        # double jump
    "Hookshot",            
    "Dash Booster V",      # vertical dash
    "Dash Booster H",      # horizontal dash
    "Dash Booster X",      # infinite dash
    "The Bike",            # "Troll" item from the dev, insta kills enemies
    "Charge Shot",         
    "Gold Keycard",        
    "Heat-Resistant Suit", 
    "Propeller",           # Water movement
    "Triple Shot",         
    "Teleport Access",     
}

DEFAULT_ITEM_CLASSIFICATIONS: dict[str, ItemClassification] = {}

for _name in ABILITIES:
    if _name in LOGICAL_ABILITIES:
        DEFAULT_ITEM_CLASSIFICATIONS[_name] = ItemClassification.progression
    else:
        DEFAULT_ITEM_CLASSIFICATIONS[_name] = ItemClassification.useful

for _name in HEALTH_PACKS:
    DEFAULT_ITEM_CLASSIFICATIONS[_name] = ItemClassification.useful
 #Making Diskettes not progression items, since they are not necessarely needed for progression, only for convenience Dash Booster X
for _name in DISKETTES:
    DEFAULT_ITEM_CLASSIFICATIONS[_name] = ItemClassification.useful

#No real junk items in ESA, let's call it Data Fragment, does nothing
DEFAULT_ITEM_CLASSIFICATIONS["Data Fragment"] = ItemClassification.filler 

class ESAItem(Item):
    game = "Environmental Station Alpha"
 
def get_random_filler_item_name(world: ESAWorld) -> str:
    return "Data Fragment"

def create_item_with_correct_classification(world: ESAWorld, name: str) -> ESAItem:
    classification = DEFAULT_ITEM_CLASSIFICATIONS[name]
 
    if name in HEALTH_PACKS and world.options.damage_boost_logic:
        classification = ItemClassification.progression
 
    return ESAItem(name, classification, ITEM_NAME_TO_ID[name], world.player)

def create_event_item(world: ESAWorld, name: str) -> ESAItem:
    return ESAItem(name, ItemClassification.progression, None, world.player)


 def create_all_items(world: ESAWorld) -> None:
    itempool: list[Item] = []

    if world.options.start_with_jump_booster:
        world.push_precollected(world.create_item("Jump Booster"))

    # 15 abilities + 8 Health Packs
    for name in ABILITIES:
        if name == "Jump Booster" and world.options.start_with_jump_booster:
            continue
        itempool.append(world.create_item(name))

    for name in HEALTH_PACKS:
        itempool.append(world.create_item(name))

    # 12 Diskettes are optional
    if world.options.randomize_diskettes:
        for name in DISKETTES:
            itempool.append(world.create_item(name))

    number_of_items = len(itempool)
    number_of_unfilled_locations = len(world.multiworld.get_unfilled_locations(world.player))
    needed_number_of_filler_items = number_of_unfilled_locations - number_of_items
  
    if needed_number_of_filler_items < 0:
        raise Exception(
            f"ESA created {number_of_items} items for only {number_of_unfilled_locations} "
        )

    itempool += [world.create_filler() for _ in range(needed_number_of_filler_items)]
    world.multiworld.itempool += itempool
 
EVENT_ITEMS = {
    35: "Key Mwyah",
    36: "Key Fire",
    37: "Key Caves",
    38: "Key Temple",
    39: "CROWN",
    40: "Power",
    41: "Gate Alpha",
    42: "Gate Beta",
    43: "Gate Gamma",
    44: "Gate Delta",
    45: "Pillar 1",
    46: "Pillar 2",
    47: "Pillar 3",
    48: "Pillar 4",
}
ITEM_NAME_GROUPS = {
    "Abilities": set(ABILITIES),
    "Health Packs": set(HEALTH_PACKS),
    "Diskettes": set(DISKETTES),
}
