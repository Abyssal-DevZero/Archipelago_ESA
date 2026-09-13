from worlds.AutoWorld import WebWorld
from BaseClasses import Tutorial


class ESAWebWorld(WebWorld):
    theme = "ice"
    tutorials = [
        Tutorial(
            "Multiworld Setup Guide",
            "A guide to setting up Environmental Station Alpha.",
            "English",
            "setup_en.md",
            "setup/en",
            ["Lucius"],
        )
    ]
