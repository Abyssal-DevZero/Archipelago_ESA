"""ESA client: AP connection, game patching, check scanning, inventory projection."""

from __future__ import annotations

import asyncio
import functools
import struct
import sys
import time
from collections import Counter

import Utils
from CommonClient import (CommonContext, ClientCommandProcessor, get_base_parser,
                          gui_enabled, logger, server_loop)
from NetUtils import ClientStatus

from . import memory as mem
from .memory import DETACHED, READY, SLOTS, hpmax_for
from ..data import (
    ABILITY_FLAG, CHECK_CHAR, CHECK_CHAR_BY_ID, CHECK_EXACT_IDS, CODE_SPOT_LOCATIONS, DISKETTE_INDEX, DISKETTES,
    FREE_SIGN_FLAG, GRANT_FLAG, HEALTH_ITEMS, HEALTH_PACKS, ID_TO_LOCATION, ITEM_ID_TO_NAME, KEYS, LOCATION_FLAG,
    LOCATION_NAME_TO_ID, MAZE_ENDING_FLAG, MAZE_PILLAR, MIRROR_FLAGS, MONITOR_FLAG, MWYAH_DEFEATED_FLAG,
    PILLAR_FLAG, PILLAR_ITEM, READ_REAL_FLAG, SIGN_DONE, SIGN_FLAG, SIGN_LOCATIONS, VIRUS_DEFEATED_FLAG,
)
from ..options import Goal

POLL_INTERVAL = 0.2
DEATHLINK_GRACE = 5.0                   # a received death waits this long for a gameplay frame
ACCESS_LEVEL_2 = (5, 3, "1")
BIKE_CHARS = {(6, 1): {"B", "P"}}       # The Bike: B owned, P owned and riding
GOAL_FLAGS = {
    Goal.option_base_game: VIRUS_DEFEATED_FLAG,
    Goal.option_postgame: MWYAH_DEFEATED_FLAG,
    Goal.option_maze: MAZE_ENDING_FLAG,
}

# location -> (patch entry whose grant shows the pickup message, vanilla Dialogue.lar section)
PICKUP_DIALOGUE = {
    "Rough Map Spot (19-12)":           ("tavarat0", "mapget"),
    "Hookshot Spot (26-10)":            ("tavarat1", "hookget"),
    "Propeller Spot (01-20)":           ("tavarat2", "swimget"),
    "Charge Shot Spot (00-08)":         ("tavarat3", "shotget"),
    "Heat-Resistant suit Spot (25-08)": ("tavarat4", "suitget"),
    "Plasma Shield Spot (03-15)":       ("tavarat5", "shieldget"),
    "Triple Shot Spot (15-04)":         ("tavarat6", "tripleget"),
    "Supercharge Module Spot (28-15)":  ("tavarat8", "superget"),
    "Gold Keycard Spot (29-19)":        ("tavarat9", "keyget"),
    "Dash Booster H Spot (05-03)":      ("bombs0", "bombget"),
    "Dash Booster V Spot (11-07)":      ("bombs1", "vertget"),
    "Dash Booster X Spot (22-12)":      ("lisa2", "endlessget"),
    "Teleport Access Spot (11-19)":     ("lisa24", "teleget"),
    "Jump Booster Spot (13-13)":        ("superjump_all", "jumpget"),
}

# Shared grants, one key per pedestal via key tables: patch entry -> vanilla section.
# Table slot i belongs to the location whose flag is (entry slot, base + i). An empty section leaves the grant's own message.
INDEXED_DIALOGUE = {
    "health_all": "tankget",
    "bonus_all": "diskget",
    "lisa_keys": "",
}
FLAG_LOCATION = {flag: LOCATION_NAME_TO_ID[name] for name, flag in LOCATION_FLAG.items()}


def table_slots(entry_id: str):
    """(KeyIndex, slot, location id) for every table slot of an indexed entry."""
    e = mem.ENTRY_BY_ID[entry_id]
    for k in e.key_index:
        for i in range(k.count):
            loc_id = FLAG_LOCATION.get((e.slot, k.base + i))
            if loc_id is not None:
                yield k, i, loc_id


# Monitors show the section named like the monitor: location -> (section, vanilla page 1, end there). Only page 1 is rewritten; it ends the dialogue unless the rest must still play.
MONITOR_DIALOGUE = {
    "Power Monitor (19-17)":      ("Power", "\xa402main generator+activated!\xc5", True),
    "Gate Alpha Monitor (11-19)": ("gateA", "\xa402main entrance security+gate alpha locked.\xc5", True),
    "Gate Beta Monitor (19-19)":  ("gateB", "\xa402main entrance security+gate beta locked.\xc5", True),
    "Gate Gamma Monitor (11-20)": ("gateC", "\xa402main entrance security+gate gamma locked.\xc5", True),
    "Gate Delta Monitor (19-20)": ("gateD", "\xa402main entrance security+gate delta locked.\xc5", True),
    "Pillar 1 Monitor (14-08)":   ("1", "\xa402*pillar 1 has now been unlocked*\xd6", True),
    "Pillar 2 Monitor (20-10)":   ("2", "\xa402*pillar 2 has now been unlocked*\xd6", True),
    "Pillar 3 Monitor (12-12)":   ("3", "\xa402*pillar 3 has now been unlocked*\xd6", True),
    "Pillar 4 Monitor (17-08)":   ("4", "\xa402*pillar 4 has now been unlocked*\xd6", True),
    "Password Monitor":   ("wrecked1", "\xa402success!\xc5", False),     # story and password follow
}


PICKUP_LOCATIONS = (set(PICKUP_DIALOGUE) | set(MONITOR_DIALOGUE)
                    | {ID_TO_LOCATION[loc_id] for e in INDEXED_DIALOGUE for _, _, loc_id in table_slots(e)})

# item -> section holding its vanilla pickup message
ITEM_DIALOGUE = {
    "Jump Booster": "jumpget", "Hookshot": "hookget", "Teleport Access": "teleget",
    "Propeller": "swimget", "Charge Shot": "shotget", "Dash Booster H": "bombget",
    "Heat-Resistant Suit": "suitget", "Gold Keycard": "keyget", "Dash Booster V": "vertget",
    "Rough Map": "mapget", "Triple Shot": "tripleget", "Plasma Shield": "shieldget",
    "Supercharge Module": "superget", "Dash Booster X": "endlessget",
    **{name: "tankget" for name in HEALTH_PACKS},
    **{name: "diskget" for name in DISKETTES},
    **{name: "mysteryget" for name in KEYS},
    # monitor items: the section the monitor shows once activated (never rewritten)
    "Power": "PowerB", "Password": "wreckaccess",
    **{f"Gate {g}": "gateo" for g in ("Alpha", "Beta", "Gamma", "Delta")},
    **{f"Pillar {n}": f"{n}b" for n in range(1, 5)},
}

# Items for other worlds use a section the game never shows. False keeps the vanilla message.
OFFWORLD = True
OFFWORLD_SECTION = "bluetiles"
OFFWORLD_PAGES = {"1": "\xa404You found an&*AP item*!\xc5",
                  "2": "It was sent to+another world.\xd6"}
MONITOR_OFFWORLD = "\xa404Found an *AP item*&and sent it to another world!\xd6"
KNOWN_KEYS = ({s for _, s in PICKUP_DIALOGUE.values()} | set(ITEM_DIALOGUE.values())
              | {OFFWORLD_SECTION})
PICKUP_REFRESH = 2.0                    # seconds between pickup message passes

VALUES_SCAN = 256                       # Global Values /values reads (past the table end it reads junk)
PILLAR_ENTRY = "mwya_pillar"            # patch entry that sends the MWYA Pillar's own input to the shadow superjump


def pillar_redirected() -> bool:
    """The pillar patch is live: "mwya" writes the shadow superjump, the labyrinth waits for the MWYA Pillar item."""
    e = mem.ENTRY_BY_ID.get(PILLAR_ENTRY)
    return bool(e and e.ready)


def check_slot(name: str) -> int:
    """Slot a location's check is read from: its shadow where a patch redirects it, else the real slot.

    READ_REAL_FLAG (the pillar) sits in superjump_all's computed coverage, but only its own patch moves it.
    """
    slot, index = LOCATION_FLAG[name]
    if name in READ_REAL_FLAG and not pillar_redirected():
        return slot
    return mem.read_slot_for(slot, index)


def item_projected(name: str, slot: int, index: int) -> bool:
    """The client owns this item's real flag: the game's own writer for it uses the shadow instead.

    Writing a flag the game still writes itself would undo the player's own progress, or send its check.
    """
    if name in PILLAR_FLAG:
        return pillar_redirected()
    return mem.shadow_live(slot, index)

@functools.cache
def read_map() -> dict[int, dict[int, int]]:
    """{slot to read: {index: location id}}. Redirected flags are read from their shadow."""
    out: dict[int, dict[int, int]] = {}
    for name, (slot, index) in LOCATION_FLAG.items():
        out.setdefault(check_slot(name), {})[index] = LOCATION_NAME_TO_ID[name]
    return out


@functools.cache
def coupled_locations() -> frozenset[str]:
    """Locations no patch entry redirects: the game's own flag is the check, so an old save sends them on connect."""
    return frozenset(name for name, (slot, _) in LOCATION_FLAG.items() if check_slot(name) == slot)


def flag_checked(loc_id: int, ch: str) -> bool:
    """Code spots count on their exact character only (the spot may pass through others while "esa"
    is typed), everything else on anything but '0'."""
    if loc_id in CHECK_EXACT_IDS:
        return ch == CHECK_CHAR_BY_ID[loc_id]
    return ch != "0"


def entered_signs(att) -> Counter:
    """Sign items and the MWYA Pillar item for every redirected spot entered in the shadow or already set in the real flag.

    For seeds without these items: each spot is then its own item, exactly like vanilla, so the redirect never
    costs the maze anything. Reading the real flag too keeps a spot entered after the shadows are rewritten.
    """
    out = Counter()
    for name, (slot, index, char) in {**SIGN_FLAG, **PILLAR_FLAG}.items():
        if not item_projected(name, slot, index):
            continue                                # no redirect: the game writes the real flag itself
        for s in (mem.SHADOW_OF[slot], slot):
            raw = att.read(s)
            if raw is not None and index < len(raw) and raw[index] == char:
                out[name] = 1
    return out
  
def signs_redirected() -> bool:
    """The code spot patch is live: the spots read and write the shadow mark."""
    return any(mem.shadow_live(slot, index) for slot, index, _ in SIGN_FLAG.values())

def push_mirror_flags(att) -> list[str]:
    """Flags no item owns (Sign 8): whichever copy the game wrote, set both.

    Redirected code reads and writes the shadow, everything else the real slot. Sign 8's spot look reads the
    shadow, the maze the real mark.
    """
    changed = []
    for name, (slot, index, char) in MIRROR_FLAGS.items():
        if not mem.shadow_live(slot):
            continue                                # nothing redirected in this slot: one copy only
        shadow = mem.SHADOW_OF[slot]
        real_s, shadow_s = att.read(slot), att.read(shadow)
        if real_s is None or shadow_s is None or index >= min(len(real_s), len(shadow_s)):
            continue
        if char not in (real_s[index], shadow_s[index]):
            continue
        for s, cur in ((slot, real_s), (shadow, shadow_s)):
            if cur[index] != char and att.write_char(s, index, char):
                changed.append(f"{name}: {SLOTS[s][0]}[{index}] -> {char}")
    return changed
  
def scan_checks(att) -> dict[int, str]:
    """{location id: flag char} for every check flag currently set."""
    found = {}
    for slot, indices in read_map().items():
        raw = att.read(slot)
        if raw is None:
            continue
        for index, loc_id in indices.items():
            if index < len(raw) and flag_checked(loc_id, raw[index]):
                found[loc_id] = raw[index]
    return found

def goal_reached(att, goal) -> bool:
    flag = GOAL_FLAGS.get(goal)
    if flag is None:
        return False
    slot, index, *char = flag
    raw = att.read(mem.read_slot_for(slot, index))
    if raw is None or index >= len(raw):
        return False
    return raw[index] == char[0] if char else raw[index] != "0"

def push_ledger(att, ledger: dict[int, str]) -> int:
    """Write checked locations back into the shadows, one char at a time.

    The game writes the same strings, so a whole-string write could eat a fresh check.
    """
    written = 0
    for slot, indices in read_map().items():
        if slot not in mem.REAL_OF:
            continue
        cur = att.read(slot)
        if cur is None:
            continue
        for index, loc_id in indices.items():
            if loc_id in ledger and index < len(cur) and cur[index] == "0":
                written += bool(att.write_char(slot, index, ledger[loc_id] or "1"))
    return written

def push_inventory(att, counts: dict[str, int], write_diskettes: bool) -> list:
    """Project the AP inventory onto the real flags, one char at a time.

    received '0' -> grant char; not received grant char -> '0'; anything else stays.
    Indices without a live redirect are skipped, writing them would send the check too.
    """
    wants = [(slot, index, char, counts.get(name, 0) > 0)
             for name, (slot, index, char) in GRANT_FLAG.items()
             if item_projected(name, slot, index)]
    if write_diskettes:
        wants += [(4, index, "1", counts.get(name, 0) > 0) for name, index in DISKETTE_INDEX.items()]

    changed = []
    for slot in sorted({w[0] for w in wants}):
        cur = att.read(slot)
        if cur is None:
            continue
        for s, index, char, have in wants:
            if s != slot or index >= len(cur):
                continue
            c = cur[index]
            if c in BIKE_CHARS.get((s, index), ()):     # never force the player on/off the bike
                continue
            if have and c == "0":
                new = char
            elif not have and c == char:
                new = "0"
            else:
                continue
            if att.write_char(slot, index, new):
                changed.append(f"{SLOTS[slot][0]}[{index}] {c} -> {new}")

    packs = min(8, sum(counts.get(n, 0) for n in HEALTH_ITEMS))
    if mem.shadow_live(0):                              # real health string = upgrades owned
        want = "1" * packs + "0" * (8 - packs)
        cur = att.read(0)
        if cur is not None and cur != want and att.write(0, want):
            changed.append(f"health {cur} -> {want}")

    want_max = hpmax_for(packs)
    counter = att.game.read_counter(mem.OBJ_HP_COUNTER)
    if counter is not None:
        value, maximum = counter
        if maximum != want_max and att.game.write_counter_max(mem.OBJ_HP_COUNTER, want_max):
            changed.append(f"max HP {maximum} -> {want_max}")
        if value > want_max and att.game.write_counter_value(mem.OBJ_HP_COUNTER, want_max):
            changed.append(f"current HP clamped {value:g} -> {want_max}")   # downwards only

    if att.hpmax_writable is not False:
        idx, want_hp = mem.HPMAX_VALUE_INDEX, float(want_max)
        cur_hp = att.game.read_value(att.vbase, idx)
        if cur_hp is not None and cur_hp != want_hp and att.game.write_value(att.vbase, idx, want_hp):
            back = att.game.read_value(att.vbase, idx)
            att.hpmax_writable = back == want_hp
            if not att.hpmax_writable:
                shown = "nothing" if back is None else f"{back:g}"
                changed.append(f"Global Value {idx} will not hold a write (wrote {want_hp:g}, read "
                               f"back {shown}) — leaving it alone. The counter write above is the "
                               "one that matters.")
    return changed

def grant_access_level(att) -> str | None:
    """Access Level 2 on: only ever 0 -> 1."""
    slot, index, char = ACCESS_LEVEL_2
    cur = att.read(slot)
    if cur is None or index >= len(cur) or cur[index] != "0":
        return None
    return f"{SLOTS[slot][0]}[{index}] 0 -> {char}" if att.write_char(slot, index, char) else None
  
def grant_free_signs(att) -> list[str]:
    """Code spots that come for free (Sign 8, mark[24]): entered from the start, in the real mark the maze reads
    and in the shadow the spot looks at. Re-asserted every poll, so fresh shadows and reloaded saves get it too."""
    changed = []
    for name, (slot, index) in FREE_SIGN_FLAG.items():
        for s in (slot, mem.SHADOW_OF[slot]) if mem.shadow_live(slot) else (slot,):
            cur = att.read(s)
            if cur is not None and index < len(cur) and cur[index] != SIGN_DONE and att.write_char(s, index, SIGN_DONE):
                changed.append(f"{name}: {SLOTS[s][0]}[{index}] {cur[index]} -> {SIGN_DONE}")
    return changed  
  
def find_pickup_targets(att) -> list[tuple[int, int, str]]:
    """[(location id, key address, vanilla section)] for every pedestal whose key can be found.
    Any known section is accepted, not just the vanilla one: after a client restart the keys still hold what the previous session wrote.
    """
    found: dict[int, list[tuple[int, str]]] = {}
    for loc, (entry_id, vanilla) in PICKUP_DIALOGUE.items():
        e = mem.ENTRY_BY_ID.get(entry_id)
        addr = att.game.pickup_key_static(e.grant_fn) if e and e.grant_fn else None
        have = att.game.read_key(addr) if addr else None
        if have not in KNOWN_KEYS:
            logger.warning("pickup message: no dialogue key found for %s (%s), it keeps the "
                           "vanilla message", loc, have or "pattern not found")
            continue
        found.setdefault(addr, []).append((LOCATION_NAME_TO_ID[loc], vanilla))
    out = []
    for addr, locs in found.items():
        if len(locs) > 1:
            logger.warning("pickup message: %s share one dialogue key, they keep the vanilla "
                           "message", ", ".join(ID_TO_LOCATION[i] for i, _ in locs))
            continue
        loc_id, vanilla = locs[0]
        out.append((loc_id, addr, vanilla))
    for entry_id, vanilla in INDEXED_DIALOGUE.items():
        tables = {}
        for k, i, loc_id in table_slots(entry_id):
            if k not in tables:
                tables[k] = att.game.key_table(k)
                if tables[k] is None:
                    logger.warning("pickup message: no key table at +%X (%s), those pedestals keep "
                                   "the vanilla message", k.rva, mem.ENTRY_BY_ID[entry_id].label)
            if tables[k] is not None:
                out.append((loc_id, tables[k] + i * mem.KEY_SLOT, vanilla))
    return out

def dialogue_keys(att, section: str) -> list:
    """Key maps of a Dialogue.lar section in every cached copy, remembered per attach."""
    cached = att.dialogue_sections.get(section)
    if cached:
        return cached
    found = [keys for _, file_map in att.game.ini_file_maps("dialogue.lar")
             if (keys := att.game.ini_keys_map(file_map, section)) is not None]
    if found:
        att.dialogue_sections[section] = found
    return found

def offworld_ready(att) -> bool:
    """Write the off-world message into its section. True once every page holds it."""
    sections = dialogue_keys(att, OFFWORLD_SECTION)
    ok = bool(sections)
    for keys in sections:
        for key, text in OFFWORLD_PAGES.items():
            want = text.encode("latin-1")
            if att.game.read_ini_raw(keys, key) != want and not att.game.write_ini_raw(keys, key, want):
                ok = False
    return ok

def wanted_section(ctx, loc_id: int, vanilla: str, offworld: bool) -> str:
    """Section the pedestal at loc_id should show."""
    it = ctx.locations_info.get(loc_id)
    if it is None:
        return vanilla
    if it.player != ctx.slot:
        return OFFWORLD_SECTION if offworld else vanilla
    name = ITEM_ID_TO_NAME.get(it.item)
    if name in KEYS and not vanilla:            # a key on a key pedestal: its own message
        return vanilla
    return ITEM_DIALOGUE.get(name, vanilla)

def monitor_page(ctx, loc_id: int, vanilla: bytes, end: bool) -> bytes:
    """Page 1 the monitor at loc_id should show; `end` decides whether the dialogue stops there."""
    it = ctx.locations_info.get(loc_id)
    if it is None:
        return vanilla
    if it.player != ctx.slot:
        if not OFFWORLD:
            return vanilla
        page = MONITOR_OFFWORLD.encode("latin-1")
    else:
        name = ITEM_ID_TO_NAME.get(it.item)
        own = GRANT_FLAG.get(name, ())[:2] == LOCATION_FLAG[ID_TO_LOCATION[loc_id]]
        if own:                                             # the monitor's own item: its own text
            return vanilla
        section = ITEM_DIALOGUE.get(name)
        sections = dialogue_keys(ctx.att, section) if section else []
        page = ctx.att.game.read_ini_raw(sections[0], "1") if sections else None
        if not page or len(page) > mem.INLINE_MAX:
            return vanilla
    if page[-1:] in (b"\xc5", b"\xd6"):
        page = page[:-1] + (b"\xd6" if end else b"\xc5")
    return page

def push_monitor_texts(ctx) -> list[str]:
    """Rewrite page 1 of every monitor's own section with the item that is really there."""
    changed = []
    for name, (section, vanilla, end) in MONITOR_DIALOGUE.items():
        want = monitor_page(ctx, LOCATION_NAME_TO_ID[name], vanilla.encode("latin-1"), end)
        for keys in dialogue_keys(ctx.att, section):
            if ctx.att.game.read_ini_raw(keys, "1") != want and ctx.att.game.write_ini_raw(keys, "1", want):
                changed.append(f"{name} -> {want.decode('latin-1')!r}")
    return changed

def push_pickup_texts(ctx) -> list[str]:
    """Point every pedestal and monitor at the message of the item that is really there."""
    att = ctx.att
    if att.pickup_targets is None:
        att.pickup_targets = find_pickup_targets(att)
    needs_offworld = OFFWORLD and any(
        (it := ctx.locations_info.get(loc_id)) is not None and it.player != ctx.slot
        for loc_id, _, _ in att.pickup_targets)
    offworld = needs_offworld and offworld_ready(att)
    changed = []
    for loc_id, addr, vanilla in att.pickup_targets:
        want = wanted_section(ctx, loc_id, vanilla, offworld)
        if att.game.read_key(addr) != want and att.game.write_key(addr, want):
            changed.append(f"{ID_TO_LOCATION[loc_id]} -> [{want}]")
    return changed + push_monitor_texts(ctx)
  
# every code spot (checks and the free one) in flag order
# name -> (slot, index, done char)
SIGN_FLAGS = {
    **dict(sorted({**{name: (*LOCATION_FLAG[name], SIGN_DONE) for name in SIGN_LOCATIONS},
                   **{name: (*flag, SIGN_DONE) for name, flag in FREE_SIGN_FLAG.items()}}.items(),
                  key=lambda kv: kv[1])),
    MAZE_PILLAR: (*LOCATION_FLAG[MAZE_PILLAR], CHECK_CHAR[MAZE_PILLAR]),
}

def sign_rows(att, ledger) -> list[tuple[str, int, int, str, bool, str, str]] | None:
    """[(name, slot, index, char, entered, AP state, shadow char)] from the real flags the maze reads, or None.

    The shadow char is what the spot itself shows once its patch is live ("" before that): the code spot patch
    for the signs, the pillar patch for the MWYA Pillar.
    """
    live = {name: pillar_redirected() if name == MAZE_PILLAR else signs_redirected() for name in SIGN_FLAGS}
    strings = {slot: att.read(slot) for slot, _, _ in SIGN_FLAGS.values()}
    shadow_slots = {SIGN_FLAGS[name][0] for name, on in live.items() if on}
    shadows = {slot: att.read(mem.SHADOW_OF[slot]) for slot in shadow_slots}
    if None in strings.values() or None in shadows.values():
        return None
    rows = []
    for name, (slot, index, done) in SIGN_FLAGS.items():
        raw = strings[slot]
        ch = raw[index] if index < len(raw) else "?"
        sh = shadows[slot][index] if live[name] and index < len(shadows[slot]) else ""
        if name in FREE_SIGN_FLAG:
            state = "no check (free)"
        else:
            state = "checked" if LOCATION_NAME_TO_ID[name] in ledger else "-"
        rows.append((name, slot, index, ch, ch == done, state, sh))
    return rows  

def kill_player(game) -> tuple[bool, str]:
    """HP counter to 0. (ok, message). The counter object, not Global Value 3 (see VALUE_DO_NOT_WRITE)."""
    before = game.read_counter(mem.OBJ_HP_COUNTER)
    if before is None:
        return False, "can't find the HP counter in this frame"
    if not game.write_counter_value(mem.OBJ_HP_COUNTER, 0):
        return False, "HP write failed"
    after = game.read_counter(mem.OBJ_HP_COUNTER)
    if after is None or after[0] != 0:
        return False, f"wrote 0 but read back {after[0] if after else '?'}, the game overrode it"
    return True, f"HP {before[0]:g} -> 0"

class ESACommandProcessor(ClientCommandProcessor):
    def _live_game(self):
        """The Game if a gameplay frame is live; otherwise says why and returns None."""
        game = self.ctx.att.game            # local ref: the watcher may detach mid-command
        if self.ctx.state != READY or game is None:
            self.output(f"no live gameplay frame ({self.ctx.state})")
            return None
        return game

    def _cmd_esa(self):
        """Show attach, patch and inventory state."""
        ctx: ESAContext = self.ctx
        att = ctx.att
        why = f" ({att.last_why})" if ctx.state != READY and att.last_why else ""
        self.output(f"state: {ctx.state}{why}")
        if att.held_off:
            self.output(f"held off: {', '.join(sorted(att.held_off))}")
        if att.proc:
            table = f"{att.sbase:X}" if att.sbase else "not allocated"
            self.output(f"pid {att.proc.pid}, module {att.proc.base:X}, string table {table}")
            self.output(f"patched: {att.patched}   shadows initialised: {att.shadow_ready}")
        goal = Goal.name_lookup.get(ctx.goal, "unknown") if ctx.goal is not None else "not connected"
        self.output(f"goal: {goal}{'  (sent)' if ctx.finished_game else ''}")
        self.output(f"death link: {'on' if ctx.death_link else 'off'}")
        self.output(f"ledger: {len(ctx.ledger)}/{len(LOCATION_NAME_TO_ID)} location(s) checked, "
                    f"{sum(LOCATION_NAME_TO_ID[n] in ctx.ledger for n in SIGN_LOCATIONS)}/"
                    f"{len(SIGN_LOCATIONS)} code spots")
        counts = ctx.inventory_counts()
        ab = sum(1 for n in ABILITY_FLAG if counts.get(n))
        hp = min(8, sum(counts.get(n, 0) for n in HEALTH_ITEMS))
        dk = sum(1 for n in DISKETTE_INDEX if counts.get(n))
        mo = sum(1 for n in MONITOR_FLAG if counts.get(n))
        sg = sum(1 for n in SIGN_FLAG if counts.get(n))
        pillar = "yes" if counts.get(PILLAR_ITEM) else "no"
        if not pillar_redirected():
            pillar += " (pillar patch pending, the pillar runs vanilla)"
        signs = (f", {sg}/{len(SIGN_FLAG)} signs, MWYA Pillar {pillar}" if ctx.signs_randomized
                 else ", signs not in this seed")
        self.output(f"inventory: {ab}/{len(ABILITY_FLAG)} abilities, {hp}/8 health packs "
                    f"(hpmax {hpmax_for(hp)}), {dk}/{len(DISKETTE_INDEX)} diskettes, "
                    f"{mo}/{len(MONITOR_FLAG)} monitors{signs}")

    def _cmd_slots(self):
        """Real vs shadow contents of every mirrored slot."""
        att = self.ctx.att
        if not att.game or not att.sbase:
            self.output("not attached")
            return
        for real, sh in sorted(mem.SHADOW_OF.items()):
            self.output(f"{SLOTS[real][0]:>9}  real   {att.read(real)}")
            self.output(f"{'':>9}  shadow {att.read(sh)}")
  
    def _cmd_entry(self, entry_id: str = "", switch: str = ""):
        """List patch entries, or `/entry <id> off|on` to pull one out live."""
        att = self.ctx.att
        if not entry_id:
            for e in mem.ENTRIES:
                st = att.patcher.entry_state(e) if att.patcher else "-"
                held = "  HELD OFF" if e.id in att.held_off else ""
                self.output(f"{e.id:<14} {st:<8} {e.label}{held}")
        elif switch.lower() == "off":
            self.output(att.hold(entry_id))
        elif switch.lower() == "on":
            self.output(att.release(entry_id))
        else:
            self.output("usage: /entry <id> off|on")
          
    def _cmd_goal(self):
        """Send the goal to the server by hand."""
        if not self.ctx.server or self.ctx.slot is None:
            self.output("not connected")
            return
        if self.ctx.finished_game:
            self.output("goal already sent")
            return
        Utils.async_start(self.ctx.send_goal(), name="send goal")
        self.output("goal sent")
  
    def _cmd_kill(self):
        """Set current HP to 0 to escape a softlock. You respawn at your last save."""
        game = self._live_game()
        if game is None:
            return
        before = game.read_counter(mem.OBJ_HP_COUNTER)
        if before is None:
            self.output("can't find the HP counter in this frame")
            return
        # the counter object, not Global Value 3 (see VALUE_DO_NOT_WRITE)
        if not game.write_counter_value(mem.OBJ_HP_COUNTER, 0):
            self.output("HP write failed")
            return
        after = game.read_counter(mem.OBJ_HP_COUNTER)
        if after is None or after[0] != 0:
            self.output(f"wrote 0 but read back {after[0] if after else '?'}, the game overrode it")
            return
        logger.info("kill: HP %g -> 0. Checks are kept; items re-sync after respawn.", before[0])
      
    def _cmd_pickups(self):
        """Which message each pedestal will show."""
        att = self.ctx.att
        if self._live_game() is None:
            return
        if att.pickup_targets is None:
            self.output("not scanned yet, connect first")
            return
        found = set()
        for loc_id, addr, vanilla in sorted(att.pickup_targets):
            found.add(ID_TO_LOCATION[loc_id])
            self.output(f"{ID_TO_LOCATION[loc_id]:<36} [{vanilla or 'own'}] -> "
                        f"[{att.game.read_key(addr) or 'own'}]")
        for name, (section, _, _) in MONITOR_DIALOGUE.items():
            sections = dialogue_keys(att, section)
            page = att.game.read_ini_raw(sections[0], "1") if sections else None
            if page is not None:
                found.add(name)
                self.output(f"{name:<36} [{section}] -> {page.decode('latin-1')!r}")
        missing = PICKUP_LOCATIONS - found
        if missing:
            self.output("not found: " + ", ".join(sorted(missing)))
          
    def _cmd_obj(self, offset: str = ""):
        """`/obj <hex>`: live instances of the object at runtime + offset."""
        game = self._live_game()
        if game is None:
            return
        try:
            off = int(offset, 16)
        except ValueError:
            self.output("usage: /obj 6B10")
            return
        insts = game.object_instances(off)
        self.output(f"+{off:X}: {len(insts)} instance(s) {' '.join(f'{p:X}' for p in insts)}")
  
    def _cmd_unstuck(self):
        """Kill you and reset your respawn to the first Health Station."""
        game = self._live_game()
        if game is None:
            return
        slot = game.active_slot()
        if slot is None:
            self.output("can't tell which save slot is loaded, not touching anything")
            return
        keys = game.save_keys_map(slot)
        if keys is None:
            self.output(f"save{slot} not found in the INI cache")
            return
        old = {k: game.read_save_key(keys, k) for k in mem.SHIP_SPAWN}
        if None in old.values():
            self.output(f"spawn keys missing in save{slot}: {old}")
            return
        for k, v in mem.SHIP_SPAWN.items():
            if not game.write_save_key(keys, k, v):
                for kk, vv in old.items():              # all four or none
                    game.write_save_key(keys, kk, vv)
                self.output(f"write to {k} failed, old spawn restored")
                return
        self._cmd_kill()

class ESAContext(CommonContext):
    game = "Environmental Station Alpha"
    command_processor = ESACommandProcessor
    items_handling = 0b111

    def __init__(self, server_address, password):
        super().__init__(server_address, password)
        self.att = mem.Attachment(log=logger)
        self.ledger: dict[int, str] = {}    # location id -> flag char; union only, never un-checks
        self.state = DETACHED
        self.write_diskettes = True
        self.goal: int | None = None        # Goal option value from slot_data
        self.signs_randomized = False       # include_signs from slot_data: code spots are checks, Sign items in the pool
        self.items_synced = False
        self.seed_name = None
        self.last_shadow_generation = -1
        self.baselined = False
        self.want_goal = False
        self.connected_at = 0.0
        self.death_link = False
        self.hp_alive: bool | None = None   # HP > 0 at the last poll; None = no reading this frame yet
        self.pending_death: float | None = None     # monotonic time a DeathLink arrived, not yet applied
        self.last_pickup_push = 0.0
        self.values_snapshot: dict[int, float] | None = None     # /values

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def _mark_checked(self, loc_ids):
        for loc_id in loc_ids:
            self.ledger.setdefault(loc_id, CHECK_CHAR_BY_ID.get(loc_id, "1"))

    def on_package(self, cmd: str, args: dict):
        if cmd == "RoomInfo":
            self.seed_name = args.get("seed_name")
        elif cmd == "Connected":
            slot = args.get("slot", self.slot)
            slot_data = args.get("slot_data") or {}
            self.ledger = {}
            self._mark_checked(args.get("checked_locations", ()))
            self.baselined = False
            self.items_synced = False               # CommonClient clears items_received on disconnect
            self.connected_at = time.monotonic()
            self.goal = slot_data.get("goal")
            logger.info("connected as slot %s, seed %s", slot, self.seed_name)
            if self.goal is None:
                logger.warning("slot_data carries no goal (seed from an older apworld?), "
                               "use /goal when you finish")
            elif self.goal not in GOAL_FLAGS:
                logger.info("goal %s has no game flag the client can watch yet, use /goal when you finish",
                            Goal.name_lookup.get(self.goal, self.goal))
            self.signs_randomized = bool(slot_data.get("include_signs"))
            if self.signs_randomized and not pillar_redirected():
                logger.info("MWYA Pillar: this client has no pillar patch yet, so typing \"mwya\" opens the "
                            "labyrinth like vanilla and the MWYA Pillar item does nothing")
            self.death_link = bool(slot_data.get("death_link"))
            Utils.async_start(self.update_death_link(self.death_link), name="death link tag")
            if self.death_link:
                logger.info("DeathLink is on")
            known = set(args.get("missing_locations", ())) | set(args.get("checked_locations", ()))
            expected = set(LOCATION_NAME_TO_ID.values())
            if not self.signs_randomized:
                expected -= {LOCATION_NAME_TO_ID[n] for n in CODE_SPOT_LOCATIONS}
            stray = sorted(expected - known)
            if stray:
                logger.warning("the server does not know location id(s) %s: this client's tables "
                               "are out of step with the apworld", stray)
            self.locations_info = {}
            scout = sorted(i for n in PICKUP_LOCATIONS if (i := LOCATION_NAME_TO_ID[n]) in known)
            if scout:
                Utils.async_start(self.send_msgs([{"cmd": "LocationScouts", "locations": scout, "create_as_hint": 0}]), name="pickup scout")
        elif cmd == "LocationInfo":
            self.last_pickup_push = 0.0             # write on the next poll
        elif cmd == "ReceivedItems":
            self.items_synced = True
        elif cmd == "RoomUpdate":
            self._mark_checked(args.get("checked_locations", ()))

    def on_deathlink(self, data: dict):
        super().on_deathlink(data)                  # logs it and records the time
        if self.death_link:
            self.pending_death = time.monotonic()   # the watcher applies it on the next live poll

    def inventory_counts(self) -> dict[str, int]:
        """Item name -> count received. Sender and location don't matter (start inventory, item links)."""
        return Counter(name for it in self.items_received
                       if (name := ITEM_ID_TO_NAME.get(it.item)) is not None)

    async def send_goal(self):
        self.finished_game = True
        await self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago ESA Client"
        return ui


async def game_watcher(ctx: ESAContext):
    """Attach, patch, poll."""
    warned_offline = announced_ready = False
    while not ctx.exit_event.is_set():
        await asyncio.sleep(POLL_INTERVAL)
        try:
            ctx.state = await asyncio.to_thread(ctx.att.step)     # stub allocation walks memory
        except Exception as exc:
            logger.exception("watcher: %r", exc)
            ctx.att.detach("error")
            continue

        if ctx.state != READY:
            announced_ready = False
            ctx.hp_alive = None
            continue

        line = grant_access_level(ctx.att)
        if line:
            logger.debug("grant: Access Level 2, %s", line)

        if not ctx.server or ctx.slot is None:
            announced_ready = False
            ctx.hp_alive = None
            if not warned_offline:
                logger.info("game is patched and waiting, connect to the multiworld to start syncing")
                warned_offline = True
            continue
        warned_offline = False

        # a slot with nothing to receive never gets ReceivedItems: wait briefly, then go
        if not ctx.items_synced and time.monotonic() - ctx.connected_at < 2.0:
            continue

        if not announced_ready:
            logger.info("Game attached and connected as %s", ctx.auth or ctx.slot)
            announced_ready = True

        try:
            await poll(ctx)
        except Exception as exc:
            logger.exception("poll: %r", exc)

async def death_link_tick(ctx: ESAContext):
    """Apply a received death, or send ours. A death is HP going from above 0 to 0 or below."""
    game = ctx.att.game
    counter = game.read_counter(mem.OBJ_HP_COUNTER)
    if counter is None:
        ctx.hp_alive = None
        return
    alive = counter[0] > 0

    if ctx.pending_death is not None:
        age = time.monotonic() - ctx.pending_death
        ctx.pending_death = None
        if not ctx.death_link:
            pass
        elif age > DEATHLINK_GRACE:
            logger.info("DeathLink: dropped, it arrived %.0fs ago while you weren't in gameplay", age)
        elif alive:
            ok, msg = kill_player(game)
            if ok:
                ctx.hp_alive = False                # our own kill: don't bounce it back
                logger.debug("DeathLink: %s", msg)
                return
            logger.warning("DeathLink: couldn't kill you (%s)", msg)

    if ctx.death_link and ctx.hp_alive and not alive:
        name = ctx.player_names.get(ctx.slot, "Someone")
        await ctx.send_death(f"{name} ran out of HP on Environmental Station Alpha.")
    ctx.hp_alive = alive

async def poll(ctx: ESAContext):
    att, ledger = ctx.att, ctx.ledger
    await death_link_tick(ctx)
    # fresh shadows are all zeros: restore the ledger before reading, or old checks reappear
    if att.shadow_generation != ctx.last_shadow_generation:
        ctx.last_shadow_generation = att.shadow_generation
        n = push_ledger(att, ledger)
        if n:
            logger.debug("restored %d check(s) into the game", n)

    found = scan_checks(att)
    new = sorted(i for i in found if i not in ledger)
    auto_goal = goal_reached(att, ctx.goal)

    if not ctx.baselined:
        ctx.baselined = True
        health = [i for i in new if LOCATION_FLAG[ID_TO_LOCATION[i]][0] == 0]
        if len(health) > 2:
            logger.warning("baseline: %d Health Pack flag(s) already set in this save, sending them "
                           "as checks. If this is an old non-randomised save, start a new file.",
                           len(health))
        coupled = sorted(ID_TO_LOCATION[i] for i in new if ID_TO_LOCATION[i] in coupled_locations())
        if coupled:
            logger.warning("baseline: %d flag(s) the game keeps itself are already set in this save (%s), "
                           "sending them as checks. Start a new file if that was not intended.",
                           len(coupled), ", ".join(coupled))
        if auto_goal and not ctx.finished_game:
            logger.warning("baseline: the goal is already reached in this save, sending it. Start a new file if that was not intended.")

    if new:
        ledger.update((i, found[i]) for i in new)
        logger.debug("check: %s", ", ".join(ID_TO_LOCATION.get(i, str(i)) for i in new))

    await ctx.check_locations(ledger.keys())

    if auto_goal and not ctx.finished_game:
        await ctx.send_goal()

    push_ledger(att, ledger)
    if ctx.signs_randomized or signs_redirected():   # the redirect stops the game entering Sign 8 itself
        for line in grant_free_signs(att):
            logger.debug("free sign: %s", line)
    for line in push_mirror_flags(att):
        logger.debug("mirror: %s", line)
    counts = ctx.inventory_counts()
    if not ctx.signs_randomized:
        counts.update(entered_signs(att))           # no Sign items in this seed: entered spots count as vanilla
    for line in push_inventory(att, counts, ctx.write_diskettes):
        logger.debug("grant: %s", line)
    now = time.monotonic()
    if now - ctx.last_pickup_push >= PICKUP_REFRESH:
        ctx.last_pickup_push = now
        for line in push_pickup_texts(ctx):
            logger.debug("pickup message: %s", line)

async def main(args):
    ctx = ESAContext(args.connect, args.password)
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()
    ctx.watcher_task = asyncio.create_task(game_watcher(ctx), name="ESAWatcher")
    await ctx.exit_event.wait()
    await ctx.shutdown()


def launch(*args):
    Utils.init_logging("ESAClient", exception_logger="Client")
    if sys.platform != "win32":
        logger.error("The ESA client is Windows only: it reads the game's memory directly. Under Proton or Wine, run the Launcher inside the same prefix as the game.")
        return
    if struct.calcsize("P") * 8 != 64:
        logger.error("Needs 64-bit Python: the game is x64.")
        return
    asyncio.run(main(get_base_parser(description="Environmental Station Alpha client").parse_args(args)))
