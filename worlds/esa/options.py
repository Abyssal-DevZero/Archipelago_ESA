from __future__ import annotations

from dataclasses import dataclass

from Options import Choice, DeathLink, DefaultOnToggle, PerGameCommonOptions, Toggle


class Goal(Choice):
    """
    What counts as finishing the seed.
    
    base_game: defeat the virus and get the first ending
    postgame: defeat Mwyah
    maze: Defeat the ghost and solve the maze.
    """

    display_name = "Goal"
    option_base_game = 0
    option_postgame = 1
    option_maze = 2
    default = 0

class StartWithJumpBooster(Toggle):
    """
    Begin with the Jump Booster instead of having to find it. For faster seeds. Dunno if that should be an option, but it's in here for now.
    """

    display_name = "Start With Jump Booster"
    
class IncludeSigns(Toggle):
    """
    Add the 13 secret eye signs into the randomizer pool for more checks. They are forced, if the maze ending is choosen. 
    Only recommended on other endings, to even out spots to check with other games, since they effectively add 13 non-relevant items to your pool.
    """

    display_name = "Include Sign Locations"

@dataclass
class ESAOptions(PerGameCommonOptions):
    goal: Goal
    start_with_jump_booster: StartWithJumpBooster
    include_signs: IncludeSigns
    death_link: DeathLink
