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
    ABILITY_FLAG, CHECK_CHAR_BY_ID, COUPLED_LOCATIONS, DISKETTE_INDEX, GRANT_FLAG,
    HEALTH_ITEMS, ID_TO_LOCATION, ITEM_ID_TO_NAME, LOCATION_FLAG, LOCATION_NAME_TO_ID,
    MONITOR_FLAG,
)

POLL_INTERVAL = 0.2
ACCESS_LEVEL_2 = (5, 3, "1")
BIKE_CHARS = {(6, 1): {"B", "P"}}       # The Bike: B owned, P owned and riding


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


def push_inventory(att, counts: dict[str, int], write_diskettes: bool,
                   project_story: bool = True) -> list:
    """Project the AP inventory onto the real flags, one char at a time.

    received '0' -> grant char; not received grant char -> '0'; anything else stays.
    Indices without a live redirect are skipped, writing them would send the check too.
    """
    wants = [(slot, index, char, counts.get(name, 0) > 0)
             for name, (slot, index, char) in GRANT_FLAG.items()
             if (project_story or name in ABILITY_FLAG) and mem.shadow_live(slot, index)]
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
        if not ctx.project_story:
            self.output("story projection OFF (/story on)")
        if att.proc:
            table = f"{att.sbase:X}" if att.sbase else "not allocated"
            self.output(f"pid {att.proc.pid}, module {att.proc.base:X}, string table {table}")
            self.output(f"patched: {att.patched}   shadows initialised: {att.shadow_ready}")
        self.output(f"ledger: {len(ctx.ledger)}/{len(LOCATION_NAME_TO_ID)} location(s) checked")
        counts = ctx.inventory_counts()
        ab = sum(1 for n in ABILITY_FLAG if counts.get(n))
        hp = min(8, sum(counts.get(n, 0) for n in HEALTH_ITEMS))
        dk = sum(1 for n in DISKETTE_INDEX if counts.get(n))
        mo = sum(1 for n in MONITOR_FLAG if counts.get(n))
        self.output(f"inventory: {ab}/{len(ABILITY_FLAG)} abilities, {hp}/8 health packs "
                    f"(hpmax {hpmax_for(hp)}), {dk}/{len(DISKETTE_INDEX)} diskettes, "
                    f"{mo}/{len(MONITOR_FLAG)} monitors")

    def _cmd_story(self, switch: str = ""):
        """`/story on|off`: write monitor and key items into the game."""
        if switch.lower() in ("on", "off"):
            self.ctx.project_story = switch.lower() == "on"
        self.output(f"story projection {'on' if self.ctx.project_story else 'OFF'}")

    def _cmd_patch(self):
        """Force a patch attempt now."""
        self.ctx.att.patched = self.ctx.att.shadow_ready = False
        self.output("will re-apply on the next poll once a frame is live")

    def _cmd_unpatch(self):
        """Restore the game's original bytes. Stops the client from working."""
        self.ctx.att.unpatch()
        self.output("reverted. Restart the game if anything looks wrong.")

    def _cmd_shadow(self):
        """Re-initialise the shadow slots and re-push the ledger."""
        self.ctx.att.shadow_ready = False
        self.output("shadow slots will be rewritten on the next poll")

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

    def _cmd_goal(self):
        """Mark the seed finished. Manual: the final boss flag is unmapped."""
        if self.ctx.finished_game:
            self.output("already sent")
            return
        self.ctx.want_goal = True
        self.output("goal queued")


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
        self.project_story = True
        self.items_synced = False
        self.seed_name = None
        self.last_shadow_generation = -1
        self.baselined = False
        self.want_goal = False
        self.connected_at = 0.0

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
            self.ledger = {}
            self._mark_checked(args.get("checked_locations", ()))
            self.baselined = False
            self.items_synced = False               # CommonClient clears items_received on disconnect
            self.connected_at = time.monotonic()
            logger.info("connected as slot %s, seed %s", slot, self.seed_name)
            known = set(args.get("missing_locations", ())) | set(args.get("checked_locations", ()))
            stray = sorted(set(LOCATION_NAME_TO_ID.values()) - known)
            if stray:
                logger.warning("the server does not know location id(s) %s: this client's tables "
                               "are out of step with the apworld", stray)
        elif cmd == "ReceivedItems":
            self.items_synced = True
        elif cmd == "RoomUpdate":
            self._mark_checked(args.get("checked_locations", ()))

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
            continue

        line = grant_access_level(ctx.att)
        if line:
            logger.debug("grant: Access Level 2, %s", line)

        if not ctx.server or ctx.slot is None:
            announced_ready = False
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


async def poll(ctx: ESAContext):
    att, ledger = ctx.att, ctx.ledger

    # fresh shadows are all zeros: restore the ledger before reading, or old checks reappear
    if att.shadow_generation != ctx.last_shadow_generation:
        ctx.last_shadow_generation = att.shadow_generation
        n = push_ledger(att, ledger)
        if n:
            logger.debug("restored %d check(s) into the game", n)

    found = scan_checks(att)
    new = sorted(i for i in found if i not in ledger)

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

    if new:
        ledger.update((i, found[i]) for i in new)
        logger.debug("check: %s", ", ".join(ID_TO_LOCATION.get(i, str(i)) for i in new))

    await ctx.check_locations(ledger.keys())

    if ctx.want_goal and not ctx.finished_game:
        ctx.want_goal = False
        await ctx.send_goal()
        logger.info("goal sent to the server")

    push_ledger(att, ledger)
    for line in push_inventory(att, ctx.inventory_counts(), ctx.write_diskettes, ctx.project_story):
        logger.debug("grant: %s", line)


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
