"""
Handles the multiworld connection, patches the running game, reads location
checks out of fake/shadow slots and projects the received inventory back into
the game's real flags.
"""

from __future__ import annotations

import asyncio
import struct
import sys
import time

import Utils
from CommonClient import (CommonContext, ClientCommandProcessor, get_base_parser,
                          gui_enabled, logger, server_loop)
from NetUtils import ClientStatus

from . import memory as mem
from .memory import DETACHED, READY, SLOTS, hpmax_for

# Name and ID tables are shared with the world package
from ..data import (
    ABILITY_FLAG,
    CHECK_CHAR_BY_ID,
    GRANT_FLAG,
    MONITOR_FLAG,
    COUPLED_LOCATIONS,
    DISKETTE_INDEX,
    HEALTH_ITEMS,
    ID_TO_LOCATION,
    ITEM_ID_TO_NAME,
    LOCATION_FLAG,
    LOCATION_NAME_TO_ID,
)

POLL_INTERVAL = 0.2

_READ_MAP_CACHE: dict[tuple, dict] = {}

def _coverage_key():
    """Hashable snapshot of which (slot, index) pairs are redirected."""
    out = []
    for slot in sorted(mem.SHADOW_OF):
        cov = mem.shadow_coverage(slot)
        out.append((slot, "all" if cov is mem.ALL_INDICES else tuple(sorted(cov))))
    return tuple(out)
  
def read_map() -> dict[int, dict[int, int]]:
    """{slot to read -> {index -> location id}}.

    Patched slots are read through their shadow
    """
    key = _coverage_key()
    cached = _READ_MAP_CACHE.get(key)
    if cached is not None:
        return cached
    out: dict[int, dict[int, int]] = {}
    for name, (real_slot, index) in LOCATION_FLAG.items():
        out.setdefault(mem.read_slot_for(real_slot, index), {})[index] = \
            LOCATION_NAME_TO_ID[name]
    _READ_MAP_CACHE[key] = out
    return out

# Location ledger - in memory only

class Ledger:
    def __init__(self):
        self.seed = None
        self.slot = None
        self.checks: dict[int, str] = {}     # location id -> character

    def reset(self, seed, slot):
        self.seed, self.slot = seed, slot
        self.checks = {}

    def add(self, loc_id, char="1"):
        """Union only: a flag returning to 0 in memory (death, reload) must
        never un-check a location."""
        if loc_id in self.checks:
            return False
        self.checks[loc_id] = char
        return True


# Game <-> AP

def scan_checks(att) -> dict[int, str]:
    """{location id: character} for every check flag currently set."""
    found = {}
    for read_slot, indices in read_map().items():
        raw = att.read(read_slot)
        if raw is None:
            continue
        for index, loc_id in indices.items():
            if index < len(raw) and raw[index] != "0":
                found[loc_id] = raw[index]
    return found


def push_ledger(att, ledger: dict[int, str]) -> int:
    """Checked locations back into the shadows, one character at a time.

    The game writes these same shadow strings from its grant events, so a
    whole-string rewrite could eat a check it recorded mid-poll.
    """
    written = 0
    for read_slot, indices in read_map().items():
        if read_slot not in mem.REAL_OF:
            continue
        cur = att.read(read_slot)
        if cur is None:
            continue
        for index, loc_id in indices.items():
            if loc_id in ledger and index < len(cur) and cur[index] == "0":
                if att.write_char(read_slot, index, ledger[loc_id] or "1"):
                    written += 1
    return written


def push_inventory(att, counts: dict[str, int], write_diskettes: bool,
                   project_story: bool = True) -> list:
    """Project the AP inventory onto the game's real flags.

    Idempotent, one character at a time, and only on indices this client owns:
      received      '0'        -> grant char
      not received  grant char -> '0'   (revokes a vanilla grant that leaked)
      anything else            -> left alone

    An index whose redirect is not live is skipped entirely: the game still records that location in the real flag, so writing the item there would send the check too.
    """
    wants = []                                # (slot, index, char, have)
    for name, (slot, index, char) in GRANT_FLAG.items():
        if name not in ABILITY_FLAG and not project_story:
            continue
        if not mem.shadow_live(slot, index):
            continue
        wants.append((slot, index, char, counts.get(name, 0) > 0))
    if write_diskettes:
        for name, index in DISKETTE_INDEX.items():
            wants.append((4, index, "1", counts.get(name, 0) > 0))

    changed = []
    for slot in sorted({w[0] for w in wants}):
        name = SLOTS[slot][0]
        cur = att.read(slot)
        if cur is None:
            continue
        for s, index, char, have in wants:
            if s != slot or index >= len(cur):
                continue
            c = cur[index]
            if have and c == "0":
                new = char
            elif not have and c == char:
                new = "0"
            else:
                continue
            if att.write_char(slot, index, new):
                changed.append(f"{name}[{index}] {c} -> {new}")

    packs = min(8, sum(counts.get(n, 0) for n in HEALTH_ITEMS))

    # The real health string is how many upgrades you own and is live calculated
    if mem.shadow_live(0):
        want = "1" * packs + "0" * (8 - packs)
        cur = att.read(0)
        if cur is not None and cur != want and att.write(0, want):
            changed.append(f"health {cur} -> {want}")

    want_max = hpmax_for(packs)
    counter = att.game.read_counter(mem.OBJ_HP_COUNTER)
    if counter is not None:
        value, maximum = counter
        if maximum != want_max:
            if att.game.write_counter_max(mem.OBJ_HP_COUNTER, want_max):
                changed.append(f"max HP {maximum} -> {want_max}")
        # Clamp downwards only
        if value > want_max:
            if att.game.write_counter_value(mem.OBJ_HP_COUNTER, want_max):
                changed.append(f"current HP clamped {value:g} -> {want_max}")

    if att.hpmax_writable is not False:
        want_hp = float(want_max)
        idx = mem.HPMAX_VALUE_INDEX
        cur_hp = att.game.read_value(att.vbase, idx)
        if cur_hp is not None and cur_hp != want_hp:
            if att.game.write_value(att.vbase, idx, want_hp):
                back = att.game.read_value(att.vbase, idx)
                if back == want_hp:
                    att.hpmax_writable = True
                else:
                    att.hpmax_writable = False
                    changed.append(
                        f"Global Value {idx} will not hold a write (wrote "
                        f"{want_hp:g}, read back {back:g}) — leaving it alone. "
                        f"The counter write above is the one that matters.")
    return changed

# APClient

class ESACommandProcessor(ClientCommandProcessor):
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
            self.output(f"pid {att.proc.pid}, module {att.proc.base:X}, "
                        f"string table {table}")
            self.output(f"patched: {att.patched}   "
                        f"shadows initialised: {att.shadow_ready}")
        self.output(f"ledger: {len(ctx.ledger.checks)}/"
                    f"{len(LOCATION_NAME_TO_ID)} location(s) checked")
        counts = ctx.inventory_counts()
        ab = sum(1 for n in ABILITY_FLAG if counts.get(n))
        hp = min(8, sum(counts.get(n, 0) for n in HEALTH_ITEMS))
        dk = sum(1 for n in DISKETTE_INDEX if counts.get(n))
        mo = sum(1 for n in MONITOR_FLAG if counts.get(n))
        self.output(f"inventory: {ab}/{len(ABILITY_FLAG)} abilities, "
                    f"{hp}/8 health packs (hpmax {hpmax_for(hp)}), "
                    f"{dk}/{len(DISKETTE_INDEX)} diskettes, "
                    f"{mo}/{len(MONITOR_FLAG)} monitors")

    def _cmd_patch(self):
        """Force a patch attempt now."""
        ctx: ESAContext = self.ctx
        ctx.att.patched = False
        ctx.att.shadow_ready = False
        self.output("will re-apply on the next poll once a frame is live")

    def _cmd_unpatch(self):
        """Restore the game's original bytes.  Stops the client from working."""
        ctx: ESAContext = self.ctx
        ctx.att.unpatch()
        self.output("reverted.  Restart the game if anything looks wrong.")

    def _cmd_shadow(self):
        """Re-initialise the shadow slots and re-push the ledger."""
        ctx: ESAContext = self.ctx
        ctx.att.shadow_ready = False
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
            return
        if switch.lower() == "off":
            self.output(att.hold(entry_id))
        elif switch.lower() == "on":
            self.output(att.release(entry_id))
        else:
            self.output("usage: /entry <id> off|on")

    def _cmd_kill(self):
        """Set current HP to 0 to escape a softlock. You respawn at your last save."""
        ctx: ESAContext = self.ctx
        game = ctx.att.game              # local ref: the watcher thread may detach mid-command
        if ctx.state != READY or game is None:
            self.output(f"can't kill you from here — no live gameplay frame ({ctx.state})")
            return
        before = game.read_counter(mem.OBJ_HP_COUNTER)
        if before is None:
            self.output("can't find the HP counter in this frame")
            return
        # The counter object, not Global Value 3: that one is on
        # VALUE_DO_NOT_WRITE, and the counter is what the clamp already uses.
        if not game.write_counter_value(mem.OBJ_HP_COUNTER, 0):
            self.output("HP write failed")
            return
        after = game.read_counter(mem.OBJ_HP_COUNTER)
        if after is None or after[0] != 0:
            self.output(f"wrote 0 but read back {after[0] if after else '?'} — the game overrode it")
            return
        logger.info("kill: HP %g -> 0. Checks are kept; items re-sync after respawn.",
                    before[0])

    def _cmd_unstuck(self):
        """Kills you and sets your respawn back to the first Health Station"""
        ctx: ESAContext = self.ctx
        game = ctx.att.game
        if ctx.state != READY or game is None:
            self.output(f"no live gameplay frame ({ctx.state})")
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
                for kk, vv in old.items():               # all four or none
                    game.write_save_key(keys, kk, vv)
                self.output(f"write to {k} failed, old spawn restored")
                return
        self._cmd_kill()

    def _cmd_goal(self):
        """Mark the seed finished.  Manual — the final boss flag is unmapped."""
        ctx: ESAContext = self.ctx
        if ctx.finished_game:
            self.output("already sent")
            return
        ctx.want_goal = True          
        self.output("goal queued")    


class ESAContext(CommonContext):
    game = "Environmental Station Alpha"
    command_processor = ESACommandProcessor
    items_handling = 0b111

    def __init__(self, server_address, password):
        super().__init__(server_address, password)
        self.att = mem.Attachment(log=logger)
        self.ledger = Ledger()
        self.state = DETACHED
        self.write_diskettes = True
        self.project_story = True       # /story off to stop writing monitors/keys
        self.items_synced = False
        self.seed_name = None
        self.last_shadow_generation = -1
        self.baselined = False
        self.want_goal = False
        self.connected_at = 0.0
        self.snapshot: dict = {}
        self.snapshot_width = 24

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        if cmd == "RoomInfo":
            self.seed_name = args.get("seed_name")
        elif cmd == "Connected":
            # read from args rather than self: order-independent
            slot = args.get("slot", self.slot)
            self.ledger.reset(self.seed_name or "unknown", slot)
            # anything the server considers checked belongs in the ledger
            for loc_id in args.get("checked_locations", ()):
                self.ledger.add(loc_id, CHECK_CHAR_BY_ID.get(loc_id, "1"))
            self.baselined = False
            # CommonClient clears items_received on disconnect
            self.items_synced = False
            self.connected_at = time.monotonic()
            logger.info("connected as slot %s, seed %s", slot, self.seed_name)
            # drift check: diverged tables would silently swallow checks
            known = set(args.get("missing_locations", ())) | \
                set(args.get("checked_locations", ()))
            stray = sorted(set(LOCATION_NAME_TO_ID.values()) - known)
            if stray:
                logger.warning("the server does not know location id(s) %s — this client's tables are out of step with the apworld", stray)
        elif cmd == "ReceivedItems":
            self.items_synced = True
        elif cmd == "RoomUpdate":
            for loc_id in args.get("checked_locations", []):
                self.ledger.add(loc_id, CHECK_CHAR_BY_ID.get(loc_id, "1"))

    def inventory_counts(self) -> dict[str, int]:
        """Item name -> quantity received.
        Location and player are ignored: starting inventory has no location attributed and item links come from another player
        """
        counts: dict[str, int] = {}
        for net_item in self.items_received:
            name = ITEM_ID_TO_NAME.get(net_item.item)
            if name is None:
                continue
            counts[name] = counts.get(name, 0) + 1
        return counts

    async def send_goal(self):
        self.finished_game = True
        await self.send_msgs([{"cmd": "StatusUpdate",
                               "status": ClientStatus.CLIENT_GOAL}])

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago ESA Client"
        return ui


async def game_watcher(ctx: ESAContext):
    """Attach, patch, poll"""
    warned_offline = False
    announced_ready = False
    while not ctx.exit_event.is_set():
        await asyncio.sleep(POLL_INTERVAL)
        try:
            # trampoline allocation walks the address space; keep it off the
            ctx.state = await asyncio.to_thread(ctx.att.step)
        except Exception as exc:                    # never kill the watcher
            logger.exception("watcher: %r", exc)
            ctx.att.detach("error")
            continue

        if ctx.state != READY:
            announced_ready = False     # re-announce after a re-attach
            continue

        if not ctx.server or ctx.slot is None:
            announced_ready = False
            if not warned_offline:
                logger.info("game is patched and waiting — connect to the "
                            "multiworld to start syncing")
                warned_offline = True
            continue
        warned_offline = False

        # a slot with nothing to receive never gets a ReceivedItems packet, so fall through after a short grace period
        if not ctx.items_synced and time.monotonic() - ctx.connected_at < 2.0:
            continue

        if not announced_ready:
            logger.info("Game attached and connected as %s ",
                        ctx.auth or ctx.slot)
            announced_ready = True

        try:
            await poll(ctx)
        except Exception as exc:
            logger.exception("poll: %r", exc)


async def poll(ctx: ESAContext):
    att = ctx.att
    ledger = ctx.ledger.checks

    # a fresh shadow is all zeroes, so push the ledger in before reading back out, or every already-checked pedestal reappears
    if att.shadow_generation != ctx.last_shadow_generation:
        ctx.last_shadow_generation = att.shadow_generation
        n = push_ledger(att, ledger)
        if n:
            logger.debug("restored %d check(s) into the game", n)

    found = scan_checks(att)

    if not ctx.baselined:
        ctx.baselined = True
        health_seen = [i for i in found
                       if LOCATION_FLAG[ID_TO_LOCATION[i]][0] == 0
                       and i not in ledger]
        if len(health_seen) > 2:
            logger.warning(
                "baseline: %d Health Pack flag(s) are already set in this save. They are being sent as checks. If this is an old non-randomised save, start a new file instead.",
                len(health_seen))
        coupled_seen = [ID_TO_LOCATION[i] for i in found
                        if ID_TO_LOCATION.get(i) in COUPLED_LOCATIONS
                        and i not in ledger]
        if coupled_seen:
            logger.warning(
                "baseline: %d story flag(s) are already set in this save (%s). They are being sent as checks. Start a new file if that was not intended.",
                len(coupled_seen), ", ".join(sorted(coupled_seen)))

    new = []
    for loc_id, char in found.items():
        if ctx.ledger.add(loc_id, char):
            new.append(loc_id)

    if new:
        names = ", ".join(ID_TO_LOCATION.get(i, str(i)) for i in sorted(new))
        logger.debug("check: %s", names)

    await ctx.check_locations(ledger.keys())

    if ctx.want_goal and not ctx.finished_game:
        ctx.want_goal = False
        await ctx.send_goal()
        logger.info("goal sent to the server")

    # Server truth back into the game, then the inventory
    push_ledger(att, ledger)
    changed = push_inventory(att, ctx.inventory_counts(), ctx.write_diskettes,
                             ctx.project_story)
    for line in changed:
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
        logger.error("Environmental Station Alpha's Archipelago client is Windows only. It reads the game's memory directly. Under Proton or Wine, run the Launcher inside the same prefix as the game.")
        return
    if struct.calcsize("P") * 8 != 64:
        logger.error("Needs 64-bit Python - the game is x64.")
        return

    parser = get_base_parser(description="Environmental Station Alpha client")
    parsed = parser.parse_args(args)
    asyncio.run(main(parsed))
