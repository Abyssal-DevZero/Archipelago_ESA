#Shared tables used by the apworld and the client

from __future__ import annotations

#==items==

BASE_ID = 0x0E5A00
FILLER_BASE = BASE_ID + 100

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

KEY_INDEX = {
    "Key Mwyah": 35,
    "Key Fire": 36,
    "Key Caves": 37,
    "Key Temple": 38,
}

CROWN_INDEX = {"CROWN": 39}

MONITOR_INDEX = {
    "Power": 40,
    "Gate Alpha": 41,
    "Gate Beta": 42,
    "Gate Gamma": 43,
    "Gate Delta": 44,
    "Pillar 1": 45,
    "Pillar 2": 46,
    "Pillar 3": 47,
    "Pillar 4": 48,
}

FILLER_ITEM_NAME = "Data Fragment"
ALL_ITEM_INDEX = {**ITEMDATA_INDEX, **KEY_INDEX, **CROWN_INDEX, **MONITOR_INDEX}

ITEM_NAME_TO_ID = {name: BASE_ID + index for name, index in ALL_ITEM_INDEX.items()}
ITEM_NAME_TO_ID[FILLER_ITEM_NAME] = FILLER_BASE + 0

ITEM_ID_TO_NAME = {item_id: name for name, item_id in ITEM_NAME_TO_ID.items()}

ABILITIES = [name for name, i in ITEMDATA_INDEX.items() if i <= 14]
HEALTH_PACKS = [name for name, i in ITEMDATA_INDEX.items() if 15 <= i <= 22]
DISKETTES = [name for name, i in ITEMDATA_INDEX.items() if 23 <= i <= 34]
KEYS = list(KEY_INDEX)
MONITORS = list(MONITOR_INDEX)

#==locations==
LOCATION_NAME_TO_ID = {
    "Jump Booster Spot": 1,
    "Hookshot Spot": 2,
    "Teleport Access Spot": 3,
    "Propeller Spot": 4,
    "Charge Shot Spot": 5,
    "Dash Booster H Spot": 6,
    "Heat-Resistant suit Spot": 7,
    "Gold Keycard Spot": 8,
    "Dash Booster V Spot": 9,
    "Rough Map Spot": 10,
    "Triple Shot Spot": 11,
    "Plasma Shield Spot": 12,
    "Supercharge Module Spot": 13,
    "Dash Booster X Spot": 14,
    "Bike Spot": 15,

    "Health Pack Beetle Spot": 21,
    "Health Pack SandTop Spot": 22,
    "Health Pack SandBottom Spot": 23,
    "Health Pack FireLow Spot": 24,
    "Health Pack FireHigh Spot": 25,
    "Health Pack Temple Spot": 26,
    "Health Pack Ship Spot": 27,
    "Health Pack Water Spot": 28,

    "Diskette Water Spot": 31,
    "Diskette Depthsmaze Spot": 32,
    "Diskette Caves Spot": 33,
    "Diskette Jungle Spot": 34,
    "Diskette TempleLeft Spot": 35,
    "Diskette TempleTall Spot": 36,
    "Diskette FireLava Spot": 37,
    "Diskette FireTop Spot": 38,
    "Diskette Security Spot": 39,
    "Diskette SandBot Spot": 40,
    "Diskette SandMid Spot": 41,
    "Diskette Ship Spot": 42,

    # boss keys
    "Key Mwyah Spot": 51,
    "Key Fire Spot": 52,
    "Key Caves Spot": 53,
    "Key Temple Spot": 54,

    # text monitor
    "Power Monitor": 61,
    "Gate Alpha Monitor": 62,
    "Gate Beta Monitor": 63,
    "Gate Gamma Monitor": 64,
    "Gate Delta Monitor": 65,
    "Pillar 1 Monitor": 66,
    "Pillar 2 Monitor": 67,
    "Pillar 3 Monitor": 68,
    "Pillar 4 Monitor": 69,
}

ID_TO_LOCATION = {loc_id: name for name, loc_id in LOCATION_NAME_TO_ID.items()}

#==flags==
LOCATION_FLAG = {
    # abilities
    "Jump Booster Spot":        (6, 0),
    "Bike Spot":                (6, 1),
    "Rough Map Spot":           (2, 0),
    "Hookshot Spot":            (2, 1),
    "Propeller Spot":           (2, 2),
    "Charge Shot Spot":         (2, 3),
    "Heat-Resistant suit Spot": (2, 4),
    "Plasma Shield Spot":       (2, 5),
    "Triple Shot Spot":         (2, 6),
    "Supercharge Module Spot":  (2, 8),
    "Gold Keycard Spot":        (2, 9),
    "Dash Booster H Spot":      (1, 0),
    "Dash Booster V Spot":      (1, 1),
    "Dash Booster X Spot":      (5, 2),
    "Teleport Access Spot":     (5, 24),
    # health packs
    "Health Pack Beetle Spot":     (0, 0),
    "Health Pack SandTop Spot":    (0, 1),
    "Health Pack FireLow Spot":    (0, 2),
    "Health Pack Temple Spot":     (0, 3),
    "Health Pack FireHigh Spot":   (0, 4),
    "Health Pack SandBottom Spot": (0, 5),
    "Health Pack Ship Spot":       (0, 6),
    "Health Pack Water Spot":      (0, 7),
    # diskettes
    "Diskette Water Spot":      (4, 0),
    "Diskette Depthsmaze Spot": (4, 1),
    "Diskette Caves Spot":      (4, 2),
    "Diskette Jungle Spot":     (4, 3),
    "Diskette TempleLeft Spot": (4, 4),
    "Diskette FireLava Spot":   (4, 5),
    "Diskette TempleTall Spot": (4, 6),
    "Diskette Security Spot":   (4, 7),
    "Diskette SandMid Spot":    (4, 8),
    "Diskette SandBot Spot":    (4, 9),
    "Diskette FireTop Spot":    (4, 10),
    "Diskette Ship Spot":       (4, 11),
    # boss keys (lisa).  Redirected - read out of shadow slot 17.
    "Key Mwyah Spot":  (5, 38),
    "Key Fire Spot":   (5, 39),
    "Key Caves Spot":  (5, 40),
    "Key Temple Spot": (5, 41),
    # text monitors (lisa).  Redirected - read out of shadow slot 17.
    "Power Monitor":      (5, 8),
    "Gate Alpha Monitor": (5, 18),
    "Gate Beta Monitor":  (5, 19),
    "Gate Gamma Monitor": (5, 20),
    "Gate Delta Monitor": (5, 21),
    "Pillar 1 Monitor":   (5, 32),
    "Pillar 2 Monitor":   (5, 33),
    "Pillar 3 Monitor":   (5, 34),
    "Pillar 4 Monitor":   (5, 35),
}

COUPLED_LOCATIONS = set()

# Because it would be too simple to switch between 0 and 1
CHECK_CHAR = {"Bike Spot": "B"}
CHECK_CHAR_BY_ID = {LOCATION_NAME_TO_ID[n]: c for n, c in CHECK_CHAR.items()}

# item name -> (real slot, index, character the vanilla grant writes)
ABILITY_FLAG = {
    "Rough Map":           (2, 0, "1"),
    "Hookshot":            (2, 1, "1"),
    "Propeller":           (2, 2, "1"),
    "Charge Shot":         (2, 3, "1"),
    "Heat-Resistant Suit": (2, 4, "1"),
    "Plasma Shield":       (2, 5, "1"),
    "Triple Shot":         (2, 6, "1"),
    "Supercharge Module":  (2, 8, "1"),
    "Gold Keycard":        (2, 9, "1"),
    "Jump Booster":        (6, 0, "1"),
    "The Bike":            (6, 1, "B"),
    "Dash Booster H":      (1, 0, "1"),
    "Dash Booster V":      (1, 1, "1"),
    "Dash Booster X":      (5, 2, "1"),
    "Teleport Access":     (5, 24, "1"),
}

# Monitor items.  All nine writes are redirected into the shadow (see the grant_only entries in memory.py), so the game can no longer set these itself and the client owns them outright.
MONITOR_FLAG = {
    "Power":      (5, 0x08, "1"),
    "Gate Alpha": (5, 0x12, "1"),
    "Gate Beta":  (5, 0x13, "1"),
    "Gate Gamma": (5, 0x14, "1"),
    "Gate Delta": (5, 0x15, "1"),
    "Pillar 1":   (5, 0x20, "1"),
    "Pillar 2":   (5, 0x21, "1"),
    "Pillar 3":   (5, 0x22, "1"),
    "Pillar 4":   (5, 0x23, "1"),
}

# Hidden Keys
KEY_FLAG = {
    "Key Mwyah":  (5, 0x26, "1"),
    "Key Fire":   (5, 0x27, "1"),
    "Key Caves":  (5, 0x28, "1"),
    "Key Temple": (5, 0x29, "1"),
}

# everything push_inventory projects onto a real slot, character included
GRANT_FLAG = {**ABILITY_FLAG, **MONITOR_FLAG, **KEY_FLAG}

DISKETTE_INDEX = {
    "Diskette Water": 0, "Diskette Depthsmaze": 1, "Diskette Caves": 2,
    "Diskette Jungle": 3, "Diskette Templeleft": 4, "Diskette Firelava": 5,
    "Diskette Templetall": 6, "Diskette Security": 7, "Diskette Sandmid": 8,
    "Diskette Sandbot": 9, "Diskette Firetop": 10, "Diskette Ship": 11,
}

HEALTH_ITEMS = set(HEALTH_PACKS)
