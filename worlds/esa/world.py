from collections.abc import Mapping
from typing import Any
from worlds.AutoWorld import World

from . import items, locations, regions, rules, web_world
from . import options as esa_options

#Start world class
class ESAWorld(World):
    """
    Environmental Station Alpha (short ESA, not the space agency) is a metroidvania playing on a forgotten space station. 
    As the astronaut is diving deeper and deeper into the station they discover the cause of desertion and it's many hidden secrets.
    """
    game = "Environmental Station Alpha"
    web = web_world.ESAWebWorld()

    options_dataclass = esa_options.ESAOptions
    options: esa_options.ESAOptions

    location_name_to_id = locations.LOCATION_NAME_TO_ID
    item_name_to_id = items.ITEM_NAME_TO_ID

    origin_region_name = "Cave_Complex"
    item_name_groups = items.ITEM_NAME_GROUPS
    
    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)
        locations.create_all_locations(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def create_items(self) -> None:
        items.create_all_items(self)

    def create_item(self, name: str) -> items.ESAItem:
        return items.create_item_with_correct_classification(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_random_filler_item_name(self)
        
    def fill_slot_data(self) -> Mapping[str, Any]:
        data = self.options.as_dict(
            "randomize_diskettes",
            "damage_boost_logic",
            "start_with_jump_booster",
            "goal",
        )
        data["seed_name"] = self.multiworld.seed_name
        return data
