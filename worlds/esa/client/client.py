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
    DISKETTE_INDEX,
    HEALTH_ITEMS,
    ID_TO_LOCATION,
    ITEM_ID_TO_NAME,
    LOCATION_FLAG,
    LOCATION_NAME_TO_ID,
)

POLL_INTERVAL = 0.2

_READ_MAP_CACHE: dict[tuple, dict] = {}


def read_map() -> dict[int, dict[int, int]]:
    """{slot to read -> {index -> location id}}.

    Patched slots are read through their shadow
    """
    key = tuple(sorted(s for s in mem.SHADOW_OF if mem.shadow_live(s)))
    cached = _READ_MAP_CACHE.get(key)
    if cached is not None:
        return cached
    out: dict[int, dict[int, int]] = {}
    for name, (real_slot, index) in LOCATION_FLAG.items():
        out.setdefault(mem.read_slot_for(real_slot), {})[index] = \
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
    written = 0
    for read_slot, indices in read_map().items():
        cur = att.read(read_slot)
        if cur is None:
            continue
        chars = list(cur)
        dirty = False
        for index, loc_id in indices.items():
            if loc_id not in ledger or index >= len(chars):
                continue
            if chars[index] == "0":
                chars[index] = ledger[loc_id] or "1"
                dirty = True
        if dirty and att.write(read_slot, "".join(chars)):
            written += 1
    return written


def push_inventory(att, counts: dict[str, int], write_diskettes: bool) -> list:
    """Project the AP inventory onto the game's real flags.

    Idempotent and authoritative in both directions: a flag AP did not grant
    is cleared. Only indices this client owns are touched
    """
    owned: dict[tuple, str] = {}
    for name, (slot, index, char) in ABILITY_FLAG.items():
        owned[(slot, index)] = char if counts.get(name, 0) else "0"
    if write_diskettes:
        for name, index in DISKETTE_INDEX.items():
            owned[(4, index)] = "1" if counts.get(name, 0) else "0"

    changed = []
    for slot in sorted({s for s, _ in owned}):
        name, length = SLOTS[slot]
        cur = att.read(slot)
        if cur is None:
            continue
        chars = list(cur)
        for (s, index), char in owned.items():
            if s == slot and index < len(chars):
                chars[index] = char
        want = "".join(chars)
        if want != cur and att.write(slot, want):
            changed.append(f"{name} {cur} -> {want}")

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
        self.output(f"state: {ctx.state}")
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
        self.output(f"inventory: {ab}/15 abilities, {hp}/8 health packs "
                    f"(hpmax {hpmax_for(hp)}), {dk}/12 diskettes")

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
                logger.warning("the server does not know location id(s) %s — "
                               "this client's tables are out of step with the "
                               "apworld", stray)
        elif cmd == "ReceivedItems":
            self.items_synced = True
        elif cmd == "RoomUpdate":
            for loc_id in args.get("checked_locations", []):
                self.ledger.add(loc_id, CHECK_CHAR_BY_ID.get(loc_id, "1"))

    def inventory_counts(self) -> dict[str, int]:
        """Item name -> quantity received.
        Location and player are ignored: starting inventory has no location
        attributed and item links come from another player
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
            logger.info("Ready — connected as %s and hooked into the game. "
                        "Start a NEW game; do not load an existing save.",
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
            logger.debug("restored %d slot(s) worth of checks into the game", n)

    found = scan_checks(att)

    if not ctx.baselined:
        ctx.baselined = True
        health_seen = [i for i in found
                       if LOCATION_FLAG[ID_TO_LOCATION[i]][0] == 0
                       and i not in ledger]
        if len(health_seen) > 2:
            logger.warning(
                "baseline: %d Health Pack flag(s) are already set in this "
                "save. They are being sent as checks. If this is an old "
                "non-randomised save, start a new file instead.",
                len(health_seen))

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
    changed = push_inventory(att, ctx.inventory_counts(), ctx.write_diskettes)
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
