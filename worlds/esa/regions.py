from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Entrance, Region

if TYPE_CHECKING:
    from .world import ESAWorld

# TODO: Post-Game regions
#       Double Check region connections

def create_and_connect_regions(world: ESAWorld) -> None:
    create_all_regions(world)
    connect_regions(world)

# Regions and connections derived from https://environmental-station-alpha.fandom.com/wiki/Station_Map
# Post-Game regions currently commented as they are no part of the AP rando yet
def create_all_regions(world: ESAWorld) -> None:
    cave_complex = Region("Cave_Complex", world.player, world.multiworld)
    depths = Region("The Depths", world.player, world.multiworld)
    volcanic_sector = Region("The Volcanic Sector", world.player, world.multiworld)
    underwater_sector = Region("The Underwater Sector", world.player, world.multiworld)
    sandrock_sector = Region("The Sandrock Sector", world.player, world.multiworld)
    jungle_sector = Region("The Jungle Sector", world.player, world.multiworld)
    temple = Region("The Temple", world.player, world.multiworld)
    derelict_ship = Region("The Derelict Ship", world.player, world.multiworld)
    control_hub = Region("The Control Hub", world.player, world.multiworld)
    ai_mainframe = Region("The A.I. Mainframe", world.player, world.multiworld)

    regions = [cave_complex, depths, volcanic_sector, underwater_sector, sandrock_sector, jungle_sector, temple, derelict_ship, control_hub, ai_mainframe]

    # Keeping this for later in the file, when the option for post-game content is viable
    #if world.options.postgame:
          #forlorn_planet = Region("The Forlorn Planet", world.player, world.multiworld)
          #research_outpost = Region("The Research Outpost", world.player, world.multiworld)
      #  regions.append(forlorn_planet, research_outpost)

    world.multiworld.regions += regions


def connect_regions(world: ESAWorld) -> None:
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

    # Also derived from https://environmental-station-alpha.fandom.com/wiki/Station_Map and the respective Areas
    # Cave Complex
    cave_to_depths = Entrance(world.player, "Cave Complex to Depths", parent=overworld)
    cave_complex.exits.append(ocave_to_depths)
    cave_to_sandrock = Entrance(world.player, "Cave Complex to Sandrock Sector", parent=overworld)
    cave_complex.exits.append(ocave_to_depths)
    cave_to_underwater = Entrance(world.player, "Cave Complex to Underwater Sector", parent=overworld)
    cave_complex.exits.append(ocave_to_depths)
    cave_to_jungle = Entrance(world.player, "Cave Complex to Jungle Sector", parent=overworld)
    cave_complex.exits.append(ocave_to_depths)
    cave_to_mainframe = Entrance(world.player, "Cave Complex to A.I. Mainframe", parent=overworld)
    cave_complex.exits.append(ocave_to_depths)
    cave_to_derelict = Entrance(world.player, "Cave Complex to Derelict Ship", parent=overworld)
    cave_complex.exits.append(ocave_to_depths)
  
    cave_complex.connect(depths, "Cave Complex to Depths")
    cave_complex.connect(sandrock_sector, "Cave Complex to Sandrock Sector")
    cave_complex.connect(underwater_secotr, "Cave Complex to Underwater Sector")
    cave_complex.connect(jungle_sector, "Cave Complex to Jungle Sector")
    cave_complex.connect(ai_mainframe, "Cave Complex to A.I. Mainframe")
    cave_complex.connect(derelict_ship, "Cave Complex to Derelict Ship")

    # An even easier way is to use the region.connect helper.
    overworld.connect(right_room, "Overworld to Right Room")
    right_room.connect(final_boss_room, "Right Room to Final Boss Room")

    # The region.connect helper even allows adding a rule immediately.
    # We'll talk more about rule creation in the set_all_rules() function in rules.py.
    overworld.connect(top_left_room, "Overworld to Top Left Room", lambda state: state.has("Key", world.player))

    # Some Entrances may only exist if the player enables certain options.
    # In our case, the Hammer locks the top middle chest in its own room if the hammer option is enabled.
    # In this case, we previously created an extra "Top Middle Room" region that we now need to connect to Overworld.
    if world.options.hammer:
        top_middle_room = world.get_region("Top Middle Room")
        overworld.connect(top_middle_room, "Overworld to Top Middle Room")
