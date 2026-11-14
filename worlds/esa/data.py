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
    "Password": 50,
}

# Code spot items: receiving one enters its spot for the maze (no item for Sign 8, the game enters it)
SIGN_INDEX = {
    "Sign 1": 51,
    "Sign 2": 52,
    "Sign 3": 53,
    "Sign 4": 54,
    "Sign 5": 55,
    "Sign 6": 56,
    "Sign 7": 57,
    "Sign 9": 59,
    "Sign 10": 60,
    "Sign 11": 61,
    "Sign 12": 62,
    "Sign 13": 63,
    "Sign 14": 64,
}

# MWYA Pillar item: receiving it opens the labyrinth (superjump[2] = 'T'). The pillar itself is then only a check.
PILLAR_ITEM = "MWYA Pillar"
PILLAR_INDEX = {PILLAR_ITEM: 65}

FILLER_ITEM_NAME = "Data Fragment"
ALL_ITEM_INDEX = {**ITEMDATA_INDEX, **KEY_INDEX, **CROWN_INDEX, **MONITOR_INDEX, **SIGN_INDEX, **PILLAR_INDEX}

ITEM_NAME_TO_ID = {name: BASE_ID + index for name, index in ALL_ITEM_INDEX.items()}
ITEM_NAME_TO_ID[FILLER_ITEM_NAME] = FILLER_BASE + 0

ITEM_ID_TO_NAME = {item_id: name for name, item_id in ITEM_NAME_TO_ID.items()}

ABILITIES = [name for name, i in ITEMDATA_INDEX.items() if i <= 14]
HEALTH_PACKS = [name for name, i in ITEMDATA_INDEX.items() if 15 <= i <= 22]
DISKETTES = [name for name, i in ITEMDATA_INDEX.items() if 23 <= i <= 34]
KEYS = list(KEY_INDEX)
MONITORS = list(MONITOR_INDEX)
SIGN_ITEMS = list(SIGN_INDEX)

#==signs==
# Postgame code spots for the maze ending. Game writed SIGN_DONE when "esa" typed at the correct spots
SIGN_DONE = "5"
FREE_SIGN_FLAG = {
    "Sign Location 8":                    (8, 24),
}
# MWYA pillar @22-16: typing "mwya" writes PILLAR_DONE into superjump[2], the labyrinth opens on that flag.
MAZE_PILLAR = "MWYA Pillar (22-16)"
PILLAR_DONE = "T"

#==locations==
LOCATION_NAME_TO_ID = {
    "Jump Booster Spot (13-13)": 1,
    "Hookshot Spot (26-10)": 2,
    "Teleport Access Spot (11-19)": 3,
    "Propeller Spot (01-20)": 4,
    "Charge Shot Spot (00-08)": 5,
    "Dash Booster H Spot (05-03)": 6,
    "Heat-Resistant suit Spot (25-08)": 7,
    "Gold Keycard Spot (29-19)": 8,
    "Dash Booster V Spot (11-07)": 9,
    "Rough Map Spot (19-12)": 10,
    "Triple Shot Spot (15-04)": 11,
    "Plasma Shield Spot (03-15)": 12,
    "Supercharge Module Spot (28-15)": 13,
    "Dash Booster X Spot (22-12)": 14,
    "Bike Spot": 15,

    "Health Pack Beetle Spot (15-12)": 21,
    "Health Pack SandTop Spot (11-13)": 22,
    "Health Pack SandBottom Spot (06-16)": 23,
    "Health Pack FireLow Spot (26-14)": 24,
    "Health Pack FireHigh Spot (26-12)": 25,
    "Health Pack Temple Spot (23-04)": 26,
    "Health Pack Ship Spot (31-24)": 27,
    "Health Pack Water Spot (02-13)": 28,

    "Diskette Water Spot (04-13)": 31,
    "Diskette Depthsmaze Spot (17-16)": 32,
    "Diskette Caves Spot (18-10)": 33,
    "Diskette Jungle Spot (17-00)": 34,
    "Diskette TempleLeft Spot (23-07)": 35,
    "Diskette TempleTall Spot (29-03)": 36,
    "Diskette FireLava Spot (25-15)": 37,
    "Diskette FireTop Spot (23-09)": 38,
    "Diskette Security Spot (19-18)": 39,
    "Diskette SandBot Spot (07-18)": 40,
    "Diskette SandMid Spot (10-14)": 41,
    "Diskette Ship Spot (25-19)": 42,

    # Four keys
    "Key Mwyah Spot": 51,
    "Key Fire Spot (19-13)": 52,
    "Key Caves Spot (15-09)": 53,
    "Key Temple Spot (22-02)": 54,

    # text monitor
    "Power Monitor (19-17)": 61,
    "Gate Alpha Monitor (11-19)": 62,
    "Gate Beta Monitor (19-19)": 63,
    "Gate Gamma Monitor (11-20)": 64,
    "Gate Delta Monitor (19-20)": 65,
    "Pillar 1 Monitor (14-08)": 66,
    "Pillar 2 Monitor (20-10)": 67,
    "Pillar 3 Monitor (12-12)": 68,
    "Pillar 4 Monitor (17-08)": 69,
    "Password Monitor": 70,

    # postgame code spots (88 stays free for Sign Location 8)
    "Sign Location 1 (03-08)": 81,
    "Sign Location 2 (21-14)": 82,
    "Sign Location 3 (Planet Surface)": 83,
    "Sign Location 4 (07-11)": 84,
    "Sign Location 5 (11-06)": 85,
    "Sign Location 6 (12-18)": 86,
    "Sign Location 7 (15-22)": 87,
    "Sign Location 9 (Death-Laser Room)": 89,
    "Sign Location 10 (24-20)": 90,
    "Sign Location 11 (26-17)": 91,
    "Sign Location 12 (18-01)": 92,
    "Sign Location 13 (28-08)": 93,
    "Sign Location 14 (25-00)": 94,
    "MWYA Pillar (22-16)": 95,
}

ID_TO_LOCATION = {loc_id: name for name, loc_id in LOCATION_NAME_TO_ID.items()}

#==flags==
LOCATION_FLAG = {
    # abilities
    "Jump Booster Spot (13-13)":        (6, 0),
    "Bike Spot":                (6, 1),
    "Rough Map Spot (19-12)":           (2, 0),
    "Hookshot Spot (26-10)":            (2, 1),
    "Propeller Spot (01-20)":           (2, 2),
    "Charge Shot Spot (00-08)":         (2, 3),
    "Heat-Resistant suit Spot (25-08)": (2, 4),
    "Plasma Shield Spot (03-15)":       (2, 5),
    "Triple Shot Spot (15-04)":         (2, 6),
    "Supercharge Module Spot (28-15)":  (2, 8),
    "Gold Keycard Spot (29-19)":        (2, 9),
    "Dash Booster H Spot (05-03)":      (1, 0),
    "Dash Booster V Spot (11-07)":      (1, 1),
    "Dash Booster X Spot (22-12)":      (5, 2),
    "Teleport Access Spot (11-19)":     (5, 24),
    # health packs
    "Health Pack Beetle Spot (15-12)":     (0, 0),
    "Health Pack SandTop Spot (11-13)":    (0, 1),
    "Health Pack FireLow Spot (26-14)":    (0, 2),
    "Health Pack Temple Spot (23-04)":     (0, 3),
    "Health Pack SandBottom Spot (06-16)": (0, 4),
    "Health Pack Ship Spot (31-24)":       (0, 5),
    "Health Pack Water Spot (02-13)":      (0, 6),
    "Health Pack FireHigh Spot (26-12)":   (0, 7),
    # diskettes
    "Diskette Water Spot (04-13)":      (4, 0),
    "Diskette Depthsmaze Spot (17-16)": (4, 1),
    "Diskette Caves Spot (18-10)":      (4, 2),
    "Diskette Jungle Spot (17-00)":     (4, 3),
    "Diskette TempleLeft Spot (23-07)": (4, 4),
    "Diskette FireLava Spot (25-15)":   (4, 5),
    "Diskette TempleTall Spot (29-03)": (4, 6),
    "Diskette Security Spot (19-18)":   (4, 7),
    "Diskette SandMid Spot (10-14)":    (4, 8),
    "Diskette SandBot Spot (07-18)":    (4, 9),
    "Diskette FireTop Spot (23-09)":    (4, 10),
    "Diskette Ship Spot (25-19)":       (4, 11),
    # Keys
    "Key Mwyah Spot":  (5, 38),
    "Key Fire Spot (19-13)":   (5, 39),
    "Key Caves Spot (15-09)":  (5, 40),
    "Key Temple Spot (22-02)": (5, 41),
    # text monitors
    "Power Monitor (19-17)":      (5, 8),
    "Gate Alpha Monitor (11-19)": (5, 18),
    "Gate Beta Monitor (19-19)":  (5, 19),
    "Gate Gamma Monitor (11-20)": (5, 20),
    "Gate Delta Monitor (19-20)": (5, 21),
    "Pillar 1 Monitor (14-08)":   (5, 32),
    "Pillar 2 Monitor (20-10)":   (5, 33),
    "Pillar 3 Monitor (12-12)":   (5, 34),
    "Pillar 4 Monitor (17-08)":   (5, 35),
    # password monitor (mark)
    "Password Monitor":   (8, 2),
    # code spots (mark), one entry each in order, no gap for Sign 8 (mark[24], FREE_SIGN_FLAG)
    "Sign Location 1 (03-08)":            (8, 11),
    "Sign Location 2 (21-14)":            (8, 12),
    "Sign Location 3 (Planet Surface)":   (8, 13),
    "Sign Location 4 (07-11)":            (8, 14),
    "Sign Location 5 (11-06)":            (8, 15),
    "Sign Location 6 (12-18)":            (8, 16),
    "Sign Location 7 (15-22)":            (8, 17),
    "Sign Location 9 (Death-Laser Room)": (8, 18),
    "Sign Location 10 (24-20)":           (8, 19),
    "Sign Location 11 (26-17)":           (8, 20),
    "Sign Location 12 (18-01)":           (8, 21),
    "Sign Location 13 (28-08)":           (8, 22),
    "Sign Location 14 (25-00)":           (8, 23),
    # MWYA pillar (superjump), read from the real slot (READ_REAL_FLAG)
    "MWYA Pillar (22-16)":                (6, 2),
}

# Locations whose check is still read from the real flag, so a save that already has it set sends it on connect
COUPLED_LOCATIONS = set()

# Because it would be too simple to switch between 0 and 1
CHECK_CHAR = {
    "Bike Spot": "B",
    "Sign Location 1 (03-08)":            SIGN_DONE,
    "Sign Location 2 (21-14)":            SIGN_DONE,
    "Sign Location 3 (Planet Surface)":   SIGN_DONE,
    "Sign Location 4 (07-11)":            SIGN_DONE,
    "Sign Location 5 (11-06)":            SIGN_DONE,
    "Sign Location 6 (12-18)":            SIGN_DONE,
    "Sign Location 7 (15-22)":            SIGN_DONE,
    "Sign Location 9 (Death-Laser Room)": SIGN_DONE,
    "Sign Location 10 (24-20)":           SIGN_DONE,
    "Sign Location 11 (26-17)":           SIGN_DONE,
    "Sign Location 12 (18-01)":           SIGN_DONE,
    "Sign Location 13 (28-08)":           SIGN_DONE,
    "Sign Location 14 (25-00)":           SIGN_DONE,
    "MWYA Pillar (22-16)":                PILLAR_DONE,
}
CHECK_CHAR_BY_ID = {LOCATION_NAME_TO_ID[n]: c for n, c in CHECK_CHAR.items()}

# every code spot that is a check, in table order
SIGN_LOCATIONS = tuple(name for name, char in CHECK_CHAR.items() if char == SIGN_DONE)

# Count only when the flag holds exactly their CHECK_CHAR. every other location counts on anything but '0'.
CHECK_EXACT = frozenset(SIGN_LOCATIONS) | {MAZE_PILLAR}
CHECK_EXACT_IDS = frozenset(LOCATION_NAME_TO_ID[n] for n in CHECK_EXACT)

# locations that only exist with include_signs (or the maze goal)
CODE_SPOT_LOCATIONS = (*SIGN_LOCATIONS, MAZE_PILLAR)

# Checks read from the real slot while their own patch is not live, even where a computed patch entry covers
READ_REAL_FLAG = frozenset({MAZE_PILLAR})

# Flags no item owns: whichever copy the game writes (real or shadow), the client sets both.
# name -> (real slot, index, char)
MIRROR_FLAGS = {
    "Sign Location 8": (8, 24, SIGN_DONE),
}

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

# Monitor items (Things getting activated by interacting with various monitors)
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
    "Password":   (8, 2, "1"),
}

# Sign items: the real mark index the maze reads (the spot's own check goes to the shadow once redirected)
SIGN_FLAG = {
    "Sign 1":  (8, 11, SIGN_DONE),
    "Sign 2":  (8, 12, SIGN_DONE),
    "Sign 3":  (8, 13, SIGN_DONE),
    "Sign 4":  (8, 14, SIGN_DONE),
    "Sign 5":  (8, 15, SIGN_DONE),
    "Sign 6":  (8, 16, SIGN_DONE),
    "Sign 7":  (8, 17, SIGN_DONE),
    "Sign 9":  (8, 18, SIGN_DONE),
    "Sign 10": (8, 19, SIGN_DONE),
    "Sign 11": (8, 20, SIGN_DONE),
    "Sign 12": (8, 21, SIGN_DONE),
    "Sign 13": (8, 22, SIGN_DONE),
    "Sign 14": (8, 23, SIGN_DONE),
}
# Four Keys
KEY_FLAG = {
    "Key Mwyah":  (5, 0x26, "1"),
    "Key Fire":   (5, 0x27, "1"),
    "Key Caves":  (5, 0x28, "1"),
    "Key Temple": (5, 0x29, "1"),
}

# MWYA Pillar item: the superjump[2] the labyrinth reads (the pillar's own check goes to the shadow once redirected)
PILLAR_FLAG = {PILLAR_ITEM: (6, 2, PILLAR_DONE)}

# everything push_inventory projects onto a real slot, character included
GRANT_FLAG = {**ABILITY_FLAG, **MONITOR_FLAG, **KEY_FLAG, **SIGN_FLAG, **PILLAR_FLAG}

DISKETTE_INDEX = {
    "Diskette Water": 0, "Diskette Depthsmaze": 1, "Diskette Caves": 2,
    "Diskette Jungle": 3, "Diskette Templeleft": 4, "Diskette Firelava": 5,
    "Diskette Templetall": 6, "Diskette Security": 7, "Diskette Sandmid": 8,
    "Diskette Sandbot": 9, "Diskette Firetop": 10, "Diskette Ship": 11,
}

HEALTH_ITEMS = set(HEALTH_PACKS)
# Endings
VIRUS_DEFEATED_FLAG = (5, 25)
MWYAH_DEFEATED_FLAG = (5, 37)
MAZE_ENDING_FLAG = (8, 27, "B")     # mark[27]: '0' -> 'B' when the maze ending is reached (mark[2] '1' -> '2' too)
# Maze state, for reference: mark[25] is 'b' while the ghost chases the player and 'y' once it is dead,
