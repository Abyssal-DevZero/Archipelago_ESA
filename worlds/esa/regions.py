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
    cave_complex.connect(depths, "Cave Complex to Depths")
    cave_complex.connect(sandrock_sector, "Cave Complex to Sandrock Sector")
    cave_complex.connect(underwater_sector, "Cave Complex to Underwater Sector")
    cave_complex.connect(jungle_sector, "Cave Complex to Jungle Sector")
    cave_complex.connect(ai_mainframe, "Cave Complex to A.I. Mainframe")
    cave_complex.connect(derelict_ship, "Cave Complex to Derelict Ship")

    #Depths
    depths.connect (cave_complex, "Depths to Cave_Complex")
    depths.connect (volcanic_sector, "The Depths to Volcanic Sector")
    depths.connect (control_hub, "Depths to Control Hub")
    depths.connect (sandrock_sector, "Depths to Sandrock Sector")

    #Volcanic Sector
    volcanic_sector.connect (depths, "Volcanic Sector to Depths")
    volcanic_sector.connect (ai_mainframe, "Volcanic Sector to AI Mainframe")
    volcanic_sector.connect (temple, "Volcanic Sector to Temple")

    #Underwater Sector
    underwater_sector.connect (cave_complex, "Underwater Sector to Cave_Complex")
    underwater_sector.connect (sandrock_sector, "Underwater Sector to Sandrock Sector")

    #Sandrock Sector
    sandrock_sector.connect (cave_complex, "Sandrock Sector to Cave_Complex")
    sandrock_sector.connect (depths, "Sandrock Sector to Depths")
    sandrock_sector.connect (control_hub, "Sandrock Sector to Control Hub")
    sandrock_sector.connect (underwater_sector, "Sandrock Sector to Underwater Sector")

    #Jungle Sector
    jungle_sector.connect (cave_complex, "Jungle Sector to Cave_Complex")
    jungle_sector.connect (ai_mainframe, "Jungle Sector to AI Mainframe")
    jungle_sector.connect (temple, "Jungle Sector to Temple")

    #Temple
    temple.connect (ai_mainframe, "Temple to AI Mainframe")
    temple.connect (volcanic_sector, "Temple to Volcanic Sector")
    temple.connect (jungle_sector, "Temple to Jungle Sector")

    #Derelict Ship
    derelict_ship.connect (cave_complex, "Derelict Ship to Cave_Complex")

    #Control Hub
    control_hub.connect (depths, "Control Hub to Depths")
    control_hub.connect (sandrock_sector, "Control Hub to Sandrock Sector")

    #A.I. Mainframe
    ai_mainframe.connect (cave_complex, "AI Mainframe to Cave_Complex")
    ai_mainframe.connect (volcanic_sector, "AI Mainframe to Volcanic Sector")
    ai_mainframe.connect (jungle_sector, "AI Mainframe to Jungle Sector")
    ai_mainframe.connect (temple, "AI Mainframe to Temple")

   #TO-DO: Conditions for connections
    #overworld.connect(top_left_room, "Overworld to Top Left Room", lambda state: state.has("Key", world.player))

    # TO-DO options ffor connections
    #if world.options.hammer:
        #top_middle_room = world.get_region("Top Middle Room")
        #overworld.connect(top_middle_room, "Overworld to Top Middle Room")
