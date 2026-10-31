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
    ABILITY_FLAG, CHECK_CHAR_BY_ID, COUPLED_LOCATIONS, DISKETTE_INDEX, DISKETTES, GRANT_FLAG,
    HEALTH_ITEMS, HEALTH_PACKS, ID_TO_LOCATION, ITEM_ID_TO_NAME, KEYS, LOCATION_FLAG,
    LOCATION_NAME_TO_ID, MONITOR_FLAG, MWYAH_DEFEATED_FLAG, VIRUS_DEFEATED_FLAG,
)
from ..options import Goal

POLL_INTERVAL = 0.2
DEATHLINK_GRACE = 5.0                   # a received death waits this long for a gameplay frame
ACCESS_LEVEL_2 = (5, 3, "1")
BIKE_CHARS = {(6, 1): {"B", "P"}}       # The Bike: B owned, P owned and riding
GOAL_FLAGS = {
    Goal.option_base_game: VIRUS_DEFEATED_FLAG,
    Goal.option_postgame: MWYAH_DEFEATED_FLAG,
}

# location -> (patch entry whose grant shows the pickup message, vanilla Dialogue.lar section)
PICKUP_DIALOGUE = {
    "Rough Map Spot":           ("tavarat0", "mapget"),
    "Hookshot Spot":            ("tavarat1", "hookget"),
    "Propeller Spot":           ("tavarat2", "swimget"),
    "Charge Shot Spot":         ("tavarat3", "shotget"),
    "Heat-Resistant suit Spot": ("tavarat4", "suitget"),
    "Plasma Shield Spot":       ("tavarat5", "shieldget"),
    "Triple Shot Spot":         ("tavarat6", "tripleget"),
    "Supercharge Module Spot":  ("tavarat8", "superget"),
    "Gold Keycard Spot":        ("tavarat9", "keyget"),
    "Dash Booster H Spot":      ("bombs0", "bombget"),
    "Dash Booster V Spot":      ("bombs1", "vertget"),
    "Dash Booster X Spot":      ("lisa2", "endlessget"),
    "Teleport Access Spot":     ("lisa24", "teleget"),
    "Jump Booster Spot":        ("superjump_all", "jumpget"),
}

# Shared grants, one key per pedestal via key tables: patch entry -> vanilla section.
# Table slot i belongs to the location whose flag is (entry slot, base + i). An empty
# section leaves the grant's own message.
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


# Monitors show the section named like the monitor: location -> (section, vanilla page 1,
# end there). Only page 1 is rewritten; it ends the dialogue unless the rest must still play.
MONITOR_DIALOGUE = {
    "Power Monitor":      ("Power", "\xa402main generator+activated!\xc5", True),
    "Gate Alpha Monitor": ("gateA", "\xa402main entrance security+gate alpha locked.\xc5", True),
    "Gate Beta Monitor":  ("gateB", "\xa402main entrance security+gate beta locked.\xc5", True),
    "Gate Gamma Monitor": ("gateC", "\xa402main entrance security+gate gamma locked.\xc5", True),
    "Gate Delta Monitor": ("gateD", "\xa402main entrance security+gate delta locked.\xc5", True),
    "Pillar 1 Monitor":   ("1", "\xa402*pillar 1 has now been unlocked*\xd6", True),
    "Pillar 2 Monitor":   ("2", "\xa402*pillar 2 has now been unlocked*\xd6", True),
    "Pillar 3 Monitor":   ("3", "\xa402*pillar 3 has now been unlocked*\xd6", True),
    "Pillar 4 Monitor":   ("4", "\xa402*pillar 4 has now been unlocked*\xd6", True),
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
OFFWORLD_PAGES = {"1": "\xa404you found an&*ap item*!\xc5",
                  "2": "it was sent to+another world.\xd6"}
MONITOR_OFFWORLD = "\xa404ap item sent to&another world!\xd6"
KNOWN_KEYS = ({s for _, s in PICKUP_DIALOGUE.values()} | set(ITEM_DIALOGUE.values())
              | {OFFWORLD_SECTION})
PICKUP_REFRESH = 2.0                    # seconds between pickup message passes

@functools.cache
def read_map() -> dict[int, dict[int, int]]:
    """{slot to read: {index: location id}}. Redirected flags are read from their shadow."""
    out: dict[int, dict[int, int]] = {}
    for name, (slot, index) in LOCATION_FLAG.items():
        out.setdefault(mem.read_slot_for(slot, index), {})[index] = LOCATION_NAME_TO_ID[name]
    return out


def scan_checks(att) -> dict[int, str]:
    """{location id: flag char} for every check flag currently set."""
    found = {}
    for slot, indices in read_map().items():
        raw = att.read(slot)
        if raw is None:
            continue
        for index, loc_id in indices.items():
            if index < len(raw) and raw[index] != "0":
                found[loc_id] = raw[index]
    return found

def goal_reached(att, goal) -> bool:
    flag = GOAL_FLAGS.get(goal)
    if flag is None:
        return False
    slot, index = flag
    raw = att.read(mem.read_slot_for(slot, index))
    return raw is not None and index < len(raw) and raw[index] != "0" 

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
             if mem.shadow_live(slot, index)]
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
        if f"{name} Monitor" == ID_TO_LOCATION[loc_id]:     # the monitor's own item: its own text
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
        self.output(f"ledger: {len(ctx.ledger)}/{len(LOCATION_NAME_TO_ID)} location(s) checked")
        counts = ctx.inventory_counts()
        ab = sum(1 for n in ABILITY_FLAG if counts.get(n))
        hp = min(8, sum(counts.get(n, 0) for n in HEALTH_ITEMS))
        dk = sum(1 for n in DISKETTE_INDEX if counts.get(n))
        mo = sum(1 for n in MONITOR_FLAG if counts.get(n))
        self.output(f"inventory: {ab}/{len(ABILITY_FLAG)} abilities, {hp}/8 health packs "
                    f"(hpmax {hpmax_for(hp)}), {dk}/{len(DISKETTE_INDEX)} diskettes, "
                    f"{mo}/{len(MONITOR_FLAG)} monitors")

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
            self.output(f"{ID_TO_LOCATION[loc_id]:<28} [{vanilla or 'own'}] -> "
                        f"[{att.game.read_key(addr) or 'own'}]")
        for name, (section, _, _) in MONITOR_DIALOGUE.items():
            sections = dialogue_keys(att, section)
            page = att.game.read_ini_raw(sections[0], "1") if sections else None
            if page is not None:
                found.add(name)
                self.output(f"{name:<28} [{section}] -> {page.decode('latin-1')!r}")
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
            self.death_link = bool(slot_data.get("death_link"))
            Utils.async_start(self.update_death_link(self.death_link), name="death link tag")
            if self.death_link:
                logger.info("DeathLink is on")
            known = set(args.get("missing_locations", ())) | set(args.get("checked_locations", ()))
            stray = sorted(set(LOCATION_NAME_TO_ID.values()) - known)
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
        coupled = sorted(ID_TO_LOCATION[i] for i in new if ID_TO_LOCATION[i] in COUPLED_LOCATIONS)
        if coupled:
            logger.warning("baseline: %d story flag(s) already set in this save (%s), sending them "
                           "as checks. Start a new file if that was not intended.",
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
    for line in push_inventory(att, ctx.inventory_counts(), ctx.write_diskettes):
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
