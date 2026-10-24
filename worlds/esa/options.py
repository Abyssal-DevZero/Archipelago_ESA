from __future__ import annotations

from dataclasses import dataclass

from Options import Choice, DeathLink, DefaultOnToggle, PerGameCommonOptions, Toggle


class Goal(Choice):
    """
    What counts as finishing the seed.
    
    base_game: defeat the virus and get the first ending
    postgame: defeat Mwyah
    """

    display_name = "Goal"
    option_base_game = 1
    option_postgame = 0
    default = 0

class StartWithJumpBooster(DefaultOnToggle):
    """
    Begin with the Jump Booster instead of having to find it. For faster seeds. Dunno if that should be an option, but it's in here for now.
    """

    display_name = "Start With Jump Booster"


@dataclass
class ESAOptions(PerGameCommonOptions):
    goal: Goal
    start_with_jump_booster: StartWithJumpBooster
    death_link: DeathLink
