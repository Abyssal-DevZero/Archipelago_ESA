from __future__ import annotations
 
from typing import TYPE_CHECKING
 
from BaseClasses import Item, ItemClassification
 
if TYPE_CHECKING:
    from .world import ESAWorld
 

BASE_ID = 0x0E5A00

#TO-DO: Monitors, Keys, Crown
ITEMDATA_INDEX = {
    "Jump Booster": 0,
    "Hookshot": 1,
    "Teleport Access": 2,
    "Propeller": 3,
    "Charge Shot": 4,
    "Dash Booster H": 5,
    "Heat-Resistant Suit": 6,
    "Gold Keycard": 7,
    "Dash Booster V": 8,
    "Rough Map": 9,
    "Triple Shot": 10,
    "Plasma Shield": 11,
    "Supercharge Module": 12,
    "Dash Booster X": 13,
    "The Bike": 14,
    "Health Pack Beetle": 15,
    "Health Pack Sandtop": 16,
    "Health Pack Firelow": 17,
    "Health Pack Temple": 18,
    "Health Pack Firehigh": 19,
    "Health Pack Sandbot": 20,
    "Health Pack Ship": 21,
    "Health Pack Water": 22,
    "Diskette Water": 23,
    "Diskette Depthsmaze": 24,
    "Diskette Caves": 25,
    "Diskette Jungle": 26,
    "Diskette Templeleft": 27,
    "Diskette Firelava": 28,
    "Diskette Templetall": 29,
    "Diskette Security": 30,
    "Diskette Sandmid": 31,
    "Diskette Sandbot": 32,
    "Diskette Firetop": 33,
    "Diskette Ship": 34,
}
 
#High enough filler ID
FILLER_BASE = BASE_ID + 100
 
ITEM_NAME_TO_ID = {name: BASE_ID + index for name, index in ITEMDATA_INDEX.items()}
ITEM_NAME_TO_ID["Data Fragment"] = FILLER_BASE + 0
 
# Convenience groupings
ABILITIES = [name for name, i in ITEMDATA_INDEX.items() if i <= 14]
HEALTH_PACKS = [name for name, i in ITEMDATA_INDEX.items() if 15 <= i <= 22]
DISKETTES = [name for name, i in ITEMDATA_INDEX.items() if 23 <= i <= 34]

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
 
#No junk in ESA, let's call it Data Fragment, does nothing
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
            f"locations. items.py and regions.py disagree about an option."
        )
 
    itempool += [world.create_filler() for _ in range(needed_number_of_filler_items)]
 .
    world.multiworld.itempool += itempool
 
    if world.options.start_with_jump_booster:
        world.push_precollected(world.create_item("Jump Booster"))
 
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
}
