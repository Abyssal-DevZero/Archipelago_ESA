#!/usr/bin/env python3
"""ESA Archipelago - game-side layer.
Process attach, global table access, and the SHADOW patch set.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import time
import logging
from dataclasses import dataclass, field

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import ctypes.wintypes as wt
else:                                    
    class wt:                            
        DWORD = ctypes.c_uint32
        WORD = ctypes.c_uint16
        BOOL = ctypes.c_int32
        HANDLE = ctypes.c_void_p
        HMODULE = ctypes.c_void_p
        WCHAR = ctypes.c_wchar

# Game constants

PROCESS_NAME = "Environmental Station Alpha.exe"
IMAGE_BASE = 0x140000000

RVA_GLOBAL_STRINGS = 0x771130
RVA_GLOBAL_VALUES = 0x771128
RVA_RUNTIME = 0x771120

EVENTGROUP_PICKUP = 0x105B6        # runtime + this -> pickup event enable byte
OBJ_PLAYER = 0x1668                # runtime + this -> player instance

OBJ_DATA = 0x20                    # object -> data block
ALT_VALUES = 0x280                 # data + this + n*8 -> Alterable Value n

# Counter objects store state as direct fields, not Alterable Values.

COUNTER_VALUE = 0xC0               # double, current
COUNTER_MAX = 0xCC                 # int32, maximum
OBJ_HP_COUNTER = 0x3AB0

# named runtime slots
OBJECT_SLOTS = {
    "player": OBJ_PLAYER,
    "hpmeter": OBJ_HP_COUNTER,     # health bar counter
    "popup": 0x16B0,               # pickup message box
    "healthped": 0x2118,           # Health Pack pedestal
}

STRING_STRIDE = 0x40
STRING_COUNT = 256
VALUE_COUNT = 256

# real slot -> (name, length)
REAL_SLOTS = {
    0: ("health", 8),
    1: ("bombs", 3),
    2: ("tavarat", 13),
    3: ("bossit", 12),
    4: ("bonus", 12),
    5: ("lisa", 43),
    6: ("superjump", 3),
    7: ("switch", 2),
    8: ("mark", 28),
}

# real slot -> shadow slot (named after save file arrays)
SHADOW_OF = {
    6: 13,   # superjump  -> +0x340
    2: 14,   # tavarat    -> +0x380
    4: 15,   # bonus      -> +0x3C0
    1: 16,   # bombs      -> +0x400
    5: 17,   # lisa       -> +0x440
    0: 18,   # health     -> +0x480
}
REAL_OF = {v: k for k, v in SHADOW_OF.items()}

SLOTS = {}
for _s, (_n, _l) in REAL_SLOTS.items():
    SLOTS[_s] = (_n, _l)
for _real, _sh in SHADOW_OF.items():
    _n, _l = REAL_SLOTS[_real]
    SLOTS[_sh] = ("shadow_" + _n, _l)

# Writing shadows at the title screen or straight after a table realloc leaves the ability HUD blank. Require a gameplay frame live this long first.
INIT_DEBOUNCE_SECONDS = 4.0

# Global Value 6 (+0x30) is the saved max HP
HPMAX_VALUE_INDEX = 6

# Indices the client must never write
VALUE_DO_NOT_WRITE = {
    3: "current HP",
    0x1A: "pickup sound volume",
}
HPMAX_BASE = 10


def hpmax_for(upgrades: int) -> int:
    """Max HP after N Health Pack items.  First two give +4, the rest +2."""
    return HPMAX_BASE + 4 * min(upgrades, 2) + 2 * max(0, upgrades - 2)


def slot_disp(slot: int) -> int:
    return slot * STRING_STRIDE


def add_rdx(disp: int) -> bytes:
    """add rdx, imm32 — the 7-byte form."""
    return b"\x48\x81\xC2" + struct.pack("<I", disp)


def mov_edx(k: int) -> bytes:
    return b"\xBA" + struct.pack("<I", k)


JMP_LEN = 5
NOP = b"\x90"

# what a 4-byte trampoline site must contain before we touch it, per real slot
SITE_EXPECT = {
    1: bytes.fromhex("4883C240"),      # ADD RDX,0x40
    2: bytes.fromhex("4883EA80"),      # SUB RDX,-0x80
}


def jmp_rel32(from_addr: int, to_addr: int) -> bytes:
    rel = to_addr - (from_addr + JMP_LEN)
    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise ValueError(f"jump out of rel32 range: {rel:+d}")
    return b"\xE9" + struct.pack("<i", rel)


def build_stub(stub_addr: int, shadow_disp: int, tail: bytes,
               return_addr: int) -> bytes:
    """CAVE shape: the site was `add rdx, imm8`, so the add comes first."""
    body = add_rdx(shadow_disp) + tail
    return body + jmp_rel32(stub_addr + len(body), return_addr)

RIP_MOV_RDX = b"\x48\x8B\x15"      # mov rdx, qword ptr [rip + d32]


def relocate(original: bytes, site_addr: int, stub_addr: int,
             declared_pi: bool = False) -> bytes:
    """Rewrite displaced bytes to behave identically at stub_addr."""
    if original[:3] == RIP_MOV_RDX and len(original) >= 7:
        d = struct.unpack_from("<i", original, 3)[0]
        target = site_addr + 7 + d              # RIP is the NEXT instruction
        new_d = target - (stub_addr + 7)
        if not -0x80000000 <= new_d <= 0x7FFFFFFF:
            raise ValueError("relocated RIP displacement out of range")
        return RIP_MOV_RDX + struct.pack("<i", new_d) + original[7:]
    if declared_pi:
        return original
    raise ValueError(
        f"displaced bytes {original.hex(' ').upper()} are not a recognised RIP-relative load. Confirm in Ghidra that they are positionindependent and set base_pi=True on the entry.")


def build_stub_append(stub_addr: int, tail: bytes, original: bytes,
                      site_addr: int, return_addr: int,
                      declared_pi: bool = False) -> bytes:
    """<relocated displaced bytes> ; <tail> ; jmp back.
    Equivalent to inserting `tail` at site_addr + len(original).
    """
    body = relocate(original, site_addr, stub_addr, declared_pi) + tail
    return body + jmp_rel32(stub_addr + len(body), return_addr)


def build_stub_base(stub_addr: int, shadow_disp: int, original: bytes,
                    site_addr: int, return_addr: int,
                    declared_pi: bool = False) -> bytes:
    """BASE shape: rdx already holds the table base, so add the offset."""
    return build_stub_append(stub_addr, add_rdx(shadow_disp), original,
                             site_addr, return_addr, declared_pi)


def build_stub_slot(stub_addr: int, shadow_slot: int, original: bytes,
                    site_addr: int, return_addr: int,
                    declared_pi: bool = False) -> bytes:
    """SLOT shape: for a slot index set by a 2-byte XOR, too short to
    overwrite with MOV EDX,imm32 in place."""
    return build_stub_append(stub_addr, mov_edx(shadow_slot), original,
                             site_addr, return_addr, declared_pi)


TAIL_LEN = {"base": 7, "slot": 5}


def stub_size(covered: int, kind: str = "cave") -> int:
    if kind in TAIL_LEN:
        return covered + TAIL_LEN[kind] + JMP_LEN   # relocation keeps length
    return 7 + (covered - 4) + JMP_LEN


# "first": the gate deciding both pedestal destruction and icon lighting reads
# the shadow. "last" would leave that gate on the real flag, so an item
# received from AP would destroy its own pedestal. Do not change.
SUPPRESSION_MODE = "first"


def select_sites(sites):
    if len(sites) <= 1 or SUPPRESSION_MODE == "all":
        return list(sites)
    key = (lambda s: s if isinstance(s, int) else s[0])
    ordered = sorted(sites, key=key)
    return [ordered[0]] if SUPPRESSION_MODE == "first" else [ordered[-1]]

# Patch table

@dataclass
class Entry:
    id: str
    label: str
    slot: int
    index: object
    suppress_fn: int = None
    pedestal: int = None
    suppress_rvas: list = field(default_factory=list)   # 7-byte, in place
    cave_sites: list = field(default_factory=list)      # 4-byte, trampoline
    base_sites: list = field(default_factory=list)      # no add at all -> BASE stub
    # (rva, length) runs to NOP out: deletes an instruction rather than
    # redirecting it. In-place and reversible. Needs bytes in site_expect.
    nop_sites: list = field(default_factory=list)
    grant_fn: int = None
    grant_src_rva: int = None
    grant_src_cave: int = None
    grant_src_base: tuple = None       # (rva, bytes_displaced)
    grant_slot_rva: int = None         # MOV EDX,imm32, in place
    grant_slot_base: tuple = None      # XOR EDX,EDX -> SLOT stub
    # rva -> exact original bytes. Required for BASE, SLOT and NOP sites
    site_expect: dict = field(default_factory=dict)
    disp_sites: list = field(default_factory=list)
    base_pi: bool = False
    suppression_only: bool = False
    grant_only: bool = False
    # the four pillars share a single display event but have a writer each
    extra_grants: list = field(default_factory=list)
    enabled: bool = True
    note: str = ""

    def __post_init__(self):
        """Validate field shapes at import, not mid-patch."""
        def bad(what):
            raise ValueError("Entry(%r): %s" % (self.id, what))
        if self.index != "computed" and not isinstance(self.index, int):
            if not (isinstance(self.index, tuple) and self.index
                    and all(isinstance(i, int) for i in self.index)):
                bad("index must be an int, a non-empty tuple of ints, or "
                    "\"computed\", got %r" % (self.index,))
        for pair in self.extra_grants:
            if not (isinstance(pair, tuple) and len(pair) == 2
                    and all(isinstance(x, int) for x in pair)):
                bad("extra_grants entries must be "
                    "(grant_src_rva, grant_slot_rva), got %r" % (pair,))
        for site in self.disp_sites:
            if not (isinstance(site, tuple) and len(site) == 3
                    and isinstance(site[0], int)
                    and isinstance(site[1], (bytes, bytearray))
                    and isinstance(site[2], (bytes, bytearray))):
                bad("disp_sites entries must be "
                    "(rva, original_bytes, patched_bytes), got %r" % (site,))
            rva, orig, patched = site
            if len(orig) != len(patched):
                bad("disp_sites at +%X changes the instruction length "
                    "(%d -> %d); an in-place rewrite must not"
                    % (rva, len(orig), len(patched)))
            diff = [i for i, (a, b) in enumerate(zip(orig, patched)) if a != b]
            if not diff:
                bad("disp_sites at +%X patches to identical bytes" % rva)
            if diff[-1] - diff[0] > 3:
                bad("disp_sites at +%X differs across %d bytes; a displacement "
                    "rewrite touches one dword only"
                    % (rva, diff[-1] - diff[0] + 1))
        if self.grant_only and self.suppression_only:
            bad("grant_only and suppression_only are mutually exclusive")
        for f in ("suppress_fn", "pedestal", "grant_fn", "grant_slot_rva"):
            v = getattr(self, f)
            if v is not None and not isinstance(v, int):
                bad("%s must be a bare RVA, got %r. If this is an "
                    "(rva, length) pair you probably want %s."
                    % (f, v, "grant_slot_base" if f == "grant_slot_rva"
                       else "a *_base or *_cave field"))

        for f in ("grant_src_cave", "grant_src_base", "grant_slot_base"):
            v = getattr(self, f)
            if v is not None and not (isinstance(v, tuple) and len(v) == 2
                                      and all(isinstance(x, int) for x in v)):
                bad("%s must be (rva, bytes_displaced), got %r" % (f, v))

        for f in ("cave_sites", "base_sites", "nop_sites"):
            for site in getattr(self, f):
                if not (isinstance(site, tuple) and len(site) == 2
                        and all(isinstance(x, int) for x in site)):
                    bad("%s entries must be (rva, bytes_displaced), got %r"
                        % (f, site))

        for r in self.suppress_rvas:
            if not isinstance(r, int):
                bad("suppress_rvas holds bare RVAs (patched in place), got %r. "
                    "A site needing a stub belongs in cave_sites or base_sites."
                    % (r,))

        for rva, want in self.site_expect.items():
            if not isinstance(rva, int) or not isinstance(want, (bytes,
                                                                 bytearray)):
                bad("site_expect maps rva -> bytes, got %r -> %r" % (rva, want))

        # a stub cannot be smaller than the jump that reaches it
        for label, rva, covered, kind in self.detour_sites:
            if covered < JMP_LEN:
                bad("%s at +%X displaces only %d byte(s); a JMP needs %d"
                    % (label, rva, covered, JMP_LEN))
            want = self.site_expect.get(rva)
            if kind in ("base", "slot") and want is not None \
                    and len(want) != covered:
                bad("site_expect for +%X is %d byte(s) but the site displaces "
                    "%d — they must match" % (rva, len(want), covered))

    @property
    def shadow(self):
        return SHADOW_OF.get(self.slot)

    @property
    def detour_sites(self):
        """[(label, rva, bytes_displaced, kind)] — sites needing a stub."""
        out = [("suppression", r, c, "cave")
               for r, c in select_sites(self.cave_sites)]
        out += [("suppression", r, c, "base")
                for r, c in select_sites(self.base_sites)]
        if not self.suppression_only:
            if self.grant_src_cave:
                out.append(("grant parser source", *self.grant_src_cave, "cave"))
            if self.grant_src_base:
                out.append(("grant parser source", *self.grant_src_base, "base"))
            if self.grant_slot_base:
                out.append(("grant setter slot", *self.grant_slot_base, "slot"))
        return out

    def expect_at(self, rva, kind):
        """Bytes the site must currently hold, or None if unknowable."""
        if kind in ("base", "slot"):
            return self.site_expect.get(rva)
        return SITE_EXPECT.get(self.slot)

    @property
    def ready(self):
        if not self.enabled or self.shadow is None:
            return False
        if not (self.suppress_rvas or self.cave_sites or self.base_sites or self.nop_sites or self.grant_only or self.disp_sites):
            return False
        for rva, length in self.nop_sites:
            want = self.site_expect.get(rva)
            if not want or len(want) != length:
                return False
        # every BASE site needs its original bytes
        for _, rva, _, kind in self.detour_sites:
            if kind in ("base", "slot") and not self.site_expect.get(rva):
                return False
        if self.suppression_only:
            return True
        has_suppression = bool(self.cave_sites or self.base_sites or self.suppress_rvas)
        if (self.disp_sites and not has_suppression and not self.grant_only
                and self.grant_slot_rva is None
                and self.grant_slot_base is None):
            return True
        if not has_suppression and not self.grant_only:
            return True                     # nop-only entry, nothing to grant
        if self.grant_slot_rva is None and self.grant_slot_base is None:
            return False
        if not (self.grant_src_rva is not None or self.grant_src_cave is not None or self.grant_src_base is not None):
            return False
        return all(isinstance(a, int) and isinstance(b, int)
                   for a, b in self.extra_grants)

    def sites(self):
        """-> [(label, rva, original_bytes, patched_bytes)] — in-place only."""
        if self.shadow is None:
            return []
        real, sh = slot_disp(self.slot), slot_disp(self.shadow)
        out = []
        chosen = select_sites(self.suppress_rvas)
        for i, r in enumerate(chosen):
            tag = "suppression" if len(chosen) == 1 else f"suppression #{i + 1}"
            out.append((tag, r, add_rdx(real), add_rdx(sh)))
        if self.suppression_only:
            return out
        if self.grant_src_rva is not None:
            out.append(("grant parser source", self.grant_src_rva,
                        add_rdx(real), add_rdx(sh)))
        if self.grant_slot_rva is not None:
            out.append(("grant setter slot", self.grant_slot_rva,
                        mov_edx(self.slot), mov_edx(self.shadow)))
        for n, (r, orig, patched) in enumerate(self.disp_sites, start=1):
            out.append((f"displacement #{n}", r, orig, patched))
        for n, (src, slot_rva) in enumerate(self.extra_grants, start=2):
            out.append((f"grant parser source #{n}", src,
                        add_rdx(real), add_rdx(sh)))
            out.append((f"grant setter slot #{n}", slot_rva,
                        mov_edx(self.slot), mov_edx(self.shadow)))
        for rva, length in self.nop_sites:
            want = self.site_expect.get(rva)
            if want and len(want) == length:
                out.append(("nop", rva, want, NOP * length))
        return out


ENTRIES = [
    # patchable in place 
    Entry("superjump_all", "Jump Booster", 6, "computed",
          suppress_fn=0x2F4A60, pedestal=0x36C0,
          suppress_rvas=[0x2F4A99], grant_fn=0x2F1880,
          grant_src_rva=0x2F1951, grant_slot_rva=0x2F19D8,
          note="verified in-game"),
    Entry("superjump1b", "The Bike", 6, 1,
          suppress_fn=0x2F6320, suppress_rvas=[0x2F6343],
          grant_fn=0x2F4380, grant_src_rva=0x2F446E, grant_slot_rva=0x2F44B1),
    Entry("bonus_all", "All 12 Diskettes", 4, "computed",
          suppress_fn=0x2F5EB0, pedestal=0x55B0,
          suppress_rvas=[0x2F5EE9], grant_fn=0x2F3AA0,
          grant_src_rva=0x2F3B81, grant_slot_rva=0x2F3C08),
    Entry("lisa2", "Dash Booster X", 5, 2,
          suppress_fn=0x2F57F0, pedestal=0xB670,
          suppress_rvas=[0x2F581B, 0x2F5916], grant_fn=0x2F3260,
          grant_src_rva=0x2F3331, grant_slot_rva=0x2F3384),
    Entry("lisa24", "Teleport Access", 5, 24,
          suppress_fn=0x2F5510, pedestal=0xA5D8,
          suppress_rvas=[0x2F553B, 0x2F5636], grant_fn=0x2F2A20,
          grant_src_rva=0x2F2AF1, grant_slot_rva=0x2F2B44),

    # trampoline sites (4-byte encodings)
    Entry("tavarat0", "Rough Map", 2, 0, suppress_fn=0x2F4BB0, pedestal=0x3708,
          cave_sites=[(0x2F4BDB, 7), (0x2F4CCB, 7)], grant_fn=0x2F1B70,
          grant_src_cave=(0x2F1C41, 12), grant_slot_rva=0x2F1C8E),
    Entry("tavarat1", "Hookshot", 2, 1, suppress_fn=0x2F6000, pedestal=0x4830,
          cave_sites=[(0x2F602B, 10), (0x2F6126, 10)], grant_fn=0x2F40C0,
          grant_src_cave=(0x2F4191, 12), grant_slot_rva=0x2F41E1),
    Entry("tavarat2", "Propeller", 2, 2, suppress_fn=0x2F68E0, pedestal=0x54D8,
          cave_sites=[(0x2F690B, 10), (0x2F6A06, 10)], grant_fn=0x2F4660,
          grant_src_cave=(0x2F4731, 12), grant_slot_rva=0x2F4781),
    Entry("tavarat3", "Charge Shot", 2, 3, suppress_fn=0x2F5CF0, pedestal=0x55F8,
          cave_sites=[(0x2F5D1B, 10), (0x2F5E16, 10)], grant_fn=0x2F37E0,
          grant_src_cave=(0x2F38B1, 12), grant_slot_rva=0x2F3901),
    Entry("tavarat4", "Heat-Resistant suit", 2, 4, suppress_fn=0x2F4D70,
          pedestal=0x8070,
          cave_sites=[(0x2F4D9B, 10), (0x2F4E96, 10)], grant_fn=0x2F1E30,
          grant_src_cave=(0x2F1F01, 12), grant_slot_rva=0x2F1F51),
    Entry("tavarat5", "Plasma Shield", 2, 5, suppress_fn=0x2F4F30, pedestal=0x8538,
          cave_sites=[(0x2F4F5B, 10), (0x2F5056, 10)], grant_fn=0x2F20F0,
          grant_src_cave=(0x2F21D1, 12), grant_slot_rva=0x2F2221),
    Entry("tavarat5b", "Plasma Shield (2nd suppression)", 2, 5,
          suppress_fn=0x2F59C0, cave_sites=[(0x2F59E6, 10)], suppression_only=True),
    Entry("tavarat6", "Triple Shot", 2, 6, suppress_fn=0x2F50F0, pedestal=0x8A48,
          cave_sites=[(0x2F511B, 10), (0x2F5213, 10), (0x2F52AD, 10)],
          grant_fn=0x2F24A0,
          grant_src_cave=(0x2F2571, 12), grant_slot_rva=0x2F25C1),
    Entry("tavarat7", "?? unassigned", 2, 7, suppress_fn=0x2F56E0, pedestal=0xA9C8,
          cave_sites=[(0x2F5706, 10)], grant_fn=0x2F2FA0,
          grant_src_cave=(0x2F3071, 12), grant_slot_rva=0x2F30C1,
          note="deleted item — patched defensively, NOT an AP location"),
    Entry("tavarat8", "Supercharge Module", 2, 8, suppress_fn=0x2F6AA0,
          pedestal=0xB040,
          cave_sites=[(0x2F6ACB, 10), (0x2F6BC8, 10)], grant_fn=0x2F2CE0,
          grant_src_cave=(0x2F2DB1, 12), grant_slot_rva=0x2F2E01),
    Entry("tavarat9", "Gold Keycard", 2, 9, suppress_fn=0x2F6C70, pedestal=0xB988,
          cave_sites=[(0x2F6C9B, 10), (0x2F6D43, 10)], grant_fn=0x2F3520,
          grant_src_cave=(0x2F35F1, 12), grant_slot_rva=0x2F3641),
    Entry("bombs0", "Dash Booster H", 1, 0, suppress_fn=0x2FDA20, pedestal=0x6B10,
          cave_sites=[(0x2FDA4B, 7), (0x2FDB3B, 7)], grant_fn=0x2F3DE0,
          grant_src_cave=(0x2F3EB1, 12), grant_slot_rva=0x2F3F29),
    Entry("bombs1", "Dash Booster V", 1, 1, suppress_fn=0x2F5350, pedestal=0x93D8,
          cave_sites=[(0x2F537B, 10), (0x2F5476, 10)], grant_fn=0x2F2760,
          grant_src_cave=(0x2F2831, 12), grant_slot_rva=0x2F2881),
    Entry("health_all", "All 8 Health Packs", 0, "computed",
          suppress_fn=0x2F4920, pedestal=0x2118, grant_fn=0x2F1490,
          base_sites=[(0x2F493D, 7)],           # MOV RDX,[RCX+0x102E0]
          grant_src_base=(0x2F155F, 7),         # MOV RDX,[RDI+0x102E0]
          # slot index is a 2-byte XOR, too short to overwrite in place
          grant_slot_base=(0x2F15EE, 5),        # XOR EDX,EDX ; MOV RCX,RBX
          # deletes  value6 += pedestal.AlterableValue[1], which would raise max HP whatever item AP placed on the pedestal
          nop_sites=[(0x2F1737, 5)],            # MOVSD [RDX+0x30], XMM0

          site_expect={
              0x2F493D: bytes.fromhex("488B91E0020100"),
              0x2F155F: bytes.fromhex("488B97E0020100"),
              0x2F15EE: bytes.fromhex("33D2488BCB"),
              0x2F1737: bytes.fromhex("F20F114230"),
          },
          base_pi=True),
    # text monitors
    Entry("lisa8", "Power", 5, 8,
          grant_fn=0x378A10, grant_src_rva=0x378B35, grant_slot_rva=0x378B70,
          grant_only=True,),
    Entry("lisa18", "Gate Alpha", 5, 0x12,
          grant_fn=0x37E0E0, grant_src_rva=0x37E195, grant_slot_rva=0x37E1E8,
          grant_only=True,),
    Entry("lisa19", "Gate Beta", 5, 0x13,
          grant_fn=0x37E370, grant_src_rva=0x37E425, grant_slot_rva=0x37E478,
          grant_only=True),
    Entry("lisa20", "Gate Gamma", 5, 0x14,
          grant_fn=0x37E600, grant_src_rva=0x37E6B5, grant_slot_rva=0x37E708,
          grant_only=True),
    Entry("lisa21", "Gate Delta", 5, 0x15,
          grant_fn=0x37E890, grant_src_rva=0x37E945, grant_slot_rva=0x37E998,
          grant_only=True),
    Entry("lisa_pillars", "Pillars 1-4", 5, (0x20, 0x21, 0x22, 0x23),
          suppress_fn=0x384E30, pedestal=0xBD78,
          suppress_rvas=[0x384F17],
          grant_fn=0x39D5E0,
          grant_src_rva=0x39D682, grant_slot_rva=0x39D6C2,      # Pillar 1
          extra_grants=[
              (0x39D792, 0x39D7D2),                             # Pillar 2
              (0x39D8A2, 0x39D8E2),                             # Pillar 3
              (0x39D9B2, 0x39D9F2),                             # Pillar 4
          ],
    Entry("lisa_keys", "Boss Keys", 5, (0x26, 0x27, 0x28, 0x29),
          suppress_fn=0x301C00, pedestal=0xCFC8, grant_fn=0x301C00,
          disp_sites=[
              # 140301C00 - no keys held branch
              (0x301CFA, bytes.fromhex("4881C340010000"),
                         bytes.fromhex("4881C340040000")),
              (0x30209E, bytes.fromhex("4881C240010000"),
                         bytes.fromhex("4881C240040000")),
              (0x302138, bytes.fromhex("488D8E40010000"),
                         bytes.fromhex("488D8E40040000")),
              (0x302144, bytes.fromhex("0FB68640010000"),
                         bytes.fromhex("0FB68640040000")),
              (0x30214F, bytes.fromhex("488D8E41010000"),
                         bytes.fromhex("488D8E41040000")),
              (0x302158, bytes.fromhex("488B8E48010000"),
                         bytes.fromhex("488B8E48040000")),
              # 140302270 - sibling branch, identical shape
              (0x30236A, bytes.fromhex("4881C340010000"),
                         bytes.fromhex("4881C340040000")),
              (0x3026FE, bytes.fromhex("4881C240010000"),
                         bytes.fromhex("4881C240040000")),
              (0x302798, bytes.fromhex("488D8E40010000"),
                         bytes.fromhex("488D8E40040000")),
              (0x3027A4, bytes.fromhex("0FB68640010000"),
                         bytes.fromhex("0FB68640040000")),
              (0x3027AF, bytes.fromhex("488D8E41010000"),
                         bytes.fromhex("488D8E41040000")),
              (0x3027B8, bytes.fromhex("488B8E48010000"),
                         bytes.fromhex("488B8E48040000")),
          ],
]

ENTRY_BY_ID = {e.id: e for e in ENTRIES}
ENTRIES_BY_SLOT = {}
for _e in ENTRIES:
    ENTRIES_BY_SLOT.setdefault(_e.slot, []).append(_e)

# kept for callers that only care that some redirect exists on a slot
ENTRY_BY_SLOT = {s: es[0] for s, es in ENTRIES_BY_SLOT.items()}

ALL_INDICES = object()


def shadow_coverage(real_slot):
    """Which indices of `real_slot` are actually redirected into its shadow.

    -> ALL_INDICES  a computed-index entry owns the whole slot
    -> set()        nothing ready: read the real slot
    -> {i, j, ...}  only these indices are written to the shadow

    This is per *index*, not per slot..
    """
    if SHADOW_OF.get(real_slot) is None:
        return set()
    covered = set()
    for e in ENTRIES_BY_SLOT.get(real_slot, ()):
        if not (e.enabled and e.ready) or e.shadow is None:
            continue
        if e.index == "computed":
            return ALL_INDICES
        if isinstance(e.index, tuple):
            covered.update(e.index)
        else:
            covered.add(e.index)
    return covered


def shadow_live(real_slot, index=None):
    """Is the redirect installed for this slot?
    """
    cov = shadow_coverage(real_slot)
    if cov is ALL_INDICES:
        return True
    if index is None:
        return bool(cov)
    return index in cov


def read_slot_for(real_slot, index=None):
    """Which slot the client should read checks out of."""
    return SHADOW_OF[real_slot] if shadow_live(real_slot, index) else real_slot

# Win32 plumbing

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_ALL_ACCESS = 0x1F0FFF
PAGE_EXECUTE_READWRITE = 0x40
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_FREE = 0x10000
ALLOC_GRANULARITY = 0x10000
REL32_REACH = 0x7000_0000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD), ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wt.DWORD), ("hModule", wt.HMODULE),
        ("szModule", wt.WCHAR * 256), ("szExePath", wt.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wt.DWORD),
        ("__alignment1", wt.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("__alignment2", wt.DWORD),
    ]


if WINDOWS:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    # Without explicit signatures ctypes defaults to a 32-bit int return and silently truncates addresses above 4GB.  The game sits at 0x7FF7-ish.
    k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                   ctypes.POINTER(MEMORY_BASIC_INFORMATION64),
                                   ctypes.c_size_t]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   wt.DWORD, wt.DWORD]
    k32.VirtualAllocEx.restype = ctypes.c_void_p
else:
    k32 = None


class AttachError(Exception):
    pass


class Process:
    """Thin ReadProcessMemory / WriteProcessMemory wrapper."""

    def __init__(self, name=PROCESS_NAME):
        if not WINDOWS:
            raise AttachError("Windows only")
        self.pid = self._find_pid(name)
        if self.pid is None:
            raise AttachError(f"process not found: {name}")
        self.base = self._module_base(self.pid, name)
        if self.base is None:
            raise AttachError(f"module base not found: {name}")
        self.handle = k32.OpenProcess(PROCESS_ALL_ACCESS, False, self.pid)
        if not self.handle:
            raise AttachError(
                f"OpenProcess failed (err {ctypes.get_last_error()}) — "
                "run the client as administrator")

    @staticmethod
    def _find_pid(name):
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE:
            return None
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(e)
            if not k32.Process32FirstW(snap, ctypes.byref(e)):
                return None
            while True:
                if e.szExeFile.lower() == name.lower():
                    return e.th32ProcessID
                if not k32.Process32NextW(snap, ctypes.byref(e)):
                    return None
        finally:
            k32.CloseHandle(snap)

    @staticmethod
    def _module_base(pid, name):
        snap = k32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if snap == INVALID_HANDLE_VALUE:
            return None
        try:
            m = MODULEENTRY32W()
            m.dwSize = ctypes.sizeof(m)
            if not k32.Module32FirstW(snap, ctypes.byref(m)):
                return None
            while True:
                if m.szModule.lower() == name.lower():
                    return ctypes.cast(m.modBaseAddr, ctypes.c_void_p).value
                if not k32.Module32NextW(snap, ctypes.byref(m)):
                    return None
        finally:
            k32.CloseHandle(snap)

    def read(self, addr, size):
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr),
                                   ctypes.byref(buf), size, ctypes.byref(got))
        if not ok or got.value != size:
            return None
        return bytes(buf)

    def write(self, addr, data):
        size = len(data)
        old = wt.DWORD()
        if not k32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), size,
                                    PAGE_EXECUTE_READWRITE, ctypes.byref(old)):
            return False
        buf = (ctypes.c_ubyte * size).from_buffer_copy(data)
        put = ctypes.c_size_t()
        ok = k32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr),
                                    ctypes.byref(buf), size, ctypes.byref(put))
        k32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), size,
                             old, ctypes.byref(old))
        return bool(ok) and put.value == size

    def read_u64(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else None

    def alive(self):
        return self.read(self.base, 2) == b"MZ"

    def close(self):
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None

# Game view

PRINTABLE = set(range(0x20, 0x7F))


def plausible_ptr(p):
    """User-mode, 8-aligned, not obviously junk."""
    return bool(p) and 0x10000 <= p < 0x7FFF_FFFF_FFFF and not (p & 7)


class Game:
    def __init__(self, proc):
        self.p = proc

    def strings_base(self):
        return self.p.read_u64(self.p.base + RVA_GLOBAL_STRINGS)

    def values_base(self):
        return self.p.read_u64(self.p.base + RVA_GLOBAL_VALUES)

    def read_slot(self, base, slot, expect_len=None):
        """Slot characters, or None on a torn/invalid read."""
        elem = base + slot * STRING_STRIDE
        head = self.p.read(elem, 16)
        if head is None:
            return None
        prefix = head[0]
        if prefix & 1:                       # heap mode
            size = struct.unpack_from("<I", head, 4)[0]
            ptr = struct.unpack_from("<Q", head, 8)[0]
            if size == 0 or size > 4096 or ptr == 0:
                return None
            raw = self.p.read(ptr, size)
        else:                                # inline
            size = prefix >> 1
            if size > STRING_STRIDE - 1:
                return None
            raw = head[1:1 + size] if size <= 15 else self.p.read(elem + 1, size)
        if raw is None or len(raw) != size:
            return None
        if expect_len is not None and size != expect_len:
            return None
        if any(b not in PRINTABLE for b in raw):
            return None
        return raw.decode("ascii")

    def write_slot_inline(self, base, slot, text, force=False):
        """Overwrite a slot with an inline string.
        Refuses in heap mode: the heap pointer at +0x08 would be clobbered.
        """
        if len(text) > STRING_STRIDE - 2:
            return False
        elem = base + slot * STRING_STRIDE
        head = self.p.read(elem, 1)
        if head is None:
            return False
        if (head[0] & 1) and not force:
            return False
        payload = bytes([len(text) << 1]) + text.encode("ascii")
        return self.p.write(elem, payload)

    def read_value(self, base, index):
        b = self.p.read(base + index * 8, 8)
        return struct.unpack("<d", b)[0] if b else None

    def write_value(self, base, index, x):
        """Global Values are 8-byte doubles"""
        return self.p.write(base + index * 8, struct.pack("<d", float(x)))

    def runtime(self):
        return self.p.read_u64(self.p.base + RVA_RUNTIME)

    def runtime_ok(self, rt=None):
        rt = self.runtime() if rt is None else rt
        if not rt:
            return False
        cached = self.p.read_u64(rt + 0x102E0)
        return bool(cached) and cached == self.strings_base()

    # object Alterable Values
    def object_instances(self, slot, limit=64):
        """Live instances of an object type.
        
        `runtime + slot` holds only the default instance and is often null.
        The instance list is at `runtime + slot + 8`: head index at +8, then
        16-byte entries of {instance pointer, next index at +8}.
        """
        rt = self.runtime()
        if not rt or not self.runtime_ok(rt):
            return []
        out = []
        direct = self.p.read_u64(rt + slot)
        if plausible_ptr(direct):
            out.append(direct)
        lst = self.p.read_u64(rt + slot + 8)
        if not plausible_ptr(lst):
            return out
        head = self.p.read(lst + 8, 4)
        if head is None:
            return out
        idx = struct.unpack("<i", head)[0]
        seen = set()
        while idx and idx not in seen and len(out) < limit:
            seen.add(idx)
            entry = lst + idx * 0x10
            obj = self.p.read_u64(entry)
            nxt = self.p.read(entry + 8, 4)
            if nxt is None:
                break
            if plausible_ptr(obj) and obj not in out:
                out.append(obj)
            idx = struct.unpack("<i", nxt)[0]
        return out

    def object_ptr(self, slot):
        insts = self.object_instances(slot, limit=1)
        return insts[0] if insts else None

    def object_data(self, slot):
        obj = self.object_ptr(slot)
        return self.data_of(obj) if obj else None

    def data_of(self, obj):
        d = self.p.read_u64(obj + OBJ_DATA)
        return d if plausible_ptr(d) else None

    def alt_values_at(self, data, count=16):
        raw = self.p.read(data + ALT_VALUES, count * 8)
        if raw is None:
            return None
        return list(struct.unpack("<%dd" % count, raw))

    def walk_objects(self, count=24, span=0x10000):
        """Yield (slot, ordinal, instance, values) for every readable object."""
        rt = self.runtime()
        if not rt or not self.runtime_ok(rt):
            return
        for base in range(0, span, 0x1000):
            block = self.p.read(rt + base, 0x1000)
            if block is None:
                continue
            for off in range(0, 0x1000, 8):
                ptr = struct.unpack_from("<Q", block, off)[0]
                if not plausible_ptr(ptr):
                    continue
                slot = base + off
                for k, obj in enumerate(self.object_instances(slot, limit=4)):
                    data = self.data_of(obj)
                    if data is None:
                        continue
                    vals = self.alt_values_at(data, count)
                    if vals is not None:
                        yield slot, k, obj, vals

    def snapshot(self, count=24, span=0x10000):
        """{(slot, ordinal, index): value} for every object in the frame.
        Keyed by ordinal, not address, so comparisons survive reallocation.
        """
        out = {}
        for slot, k, _obj, vals in self.walk_objects(count, span):
            for i, v in enumerate(vals):
                out[(slot, k, i)] = v
        return out

    def scan_objects(self, target, count=24, span=0x10000, tol=1e-9):
        """Object slots holding `target` in an Alterable Value. -> [(slot, instance, index, value)]
        """
        hits = []
        for slot, _k, obj, vals in self.walk_objects(count, span):
            for i, v in enumerate(vals):
                if abs(v - target) <= tol:
                    hits.append((slot, obj, i, v))
        return hits

    def read_alt_values(self, slot, count=16):
        data = self.object_data(slot)
        return self.alt_values_at(data, count) if data else None

    def write_alt_value(self, slot, index, x):
        data = self.object_data(slot)
        if not data:
            return False
        return self.p.write(data + ALT_VALUES + index * 8,
                            struct.pack("<d", float(x)))

    # --- Counter objects ---------------------------------------------
    def read_counter(self, slot):
        """-> (current, maximum) for a Counter object, or None."""
        obj = self.object_ptr(slot)
        if not obj:
            return None
        cur = self.p.read(obj + COUNTER_VALUE, 8)
        mx = self.p.read(obj + COUNTER_MAX, 4)
        if cur is None or mx is None:
            return None
        return struct.unpack("<d", cur)[0], struct.unpack("<i", mx)[0]

    def write_counter_max(self, slot, n):
        obj = self.object_ptr(slot)
        if not obj:
            return False
        return self.p.write(obj + COUNTER_MAX, struct.pack("<i", int(n)))

    def write_counter_value(self, slot, x):
        obj = self.object_ptr(slot)
        if not obj:
            return False
        return self.p.write(obj + COUNTER_VALUE, struct.pack("<d", float(x)))

    def read_alt_string(self, slot):
        """The object's own Alterable String, same layout as a global slot."""
        data = self.object_data(slot)
        if not data:
            return None
        head = self.p.read(data, 16)
        if head is None:
            return None
        if head[0] & 1:
            size = struct.unpack_from("<I", head, 4)[0]
            ptr = struct.unpack_from("<Q", head, 8)[0]
            if not (0 < size <= 4096) or not ptr:
                return None
            raw = self.p.read(ptr, size)
        else:
            size = head[0] >> 1
            if size > 63:
                return None
            raw = head[1:1 + size] if size <= 15 else self.p.read(data + 1, size)
        if raw is None or any(b not in PRINTABLE for b in raw):
            return None
        return raw.decode("ascii")

    def read_u8(self, addr):
        b = self.p.read(addr, 1)
        return b[0] if b else None


def frame_state(game, sbase):
    """-> (ready, why). Is a gameplay frame running?

    Slot readability is not sufficient: init_globals fills the slots at
    startup, so they read fine at the main menu. The event-group byte and the
    player object are frame-scoped.
    """
    rt = game.runtime()
    if not rt:
        return False, "runtime object is null"
    if not game.runtime_ok(rt):
        return False, "runtime self-check failed"
    grp = game.read_u8(rt + EVENTGROUP_PICKUP)
    if grp is None:
        return False, "event group byte unreadable"
    if grp == 0:
        return False, "not in a gameplay frame (menu?)"
    player = game.p.read_u64(rt + OBJ_PLAYER)
    if not player:
        return False, "no player object in this frame"
    for slot, (name, length) in REAL_SLOTS.items():
        if game.read_slot(sbase, slot, length) is None:
            return False, f"{name} not readable at {length} chars"
    return True, f"player {player:X}, pickup events enabled"


def init_shadows(game, base, log):
    """Fill every shadow slot with zeros of the mirrored slot's length.

    Only once a gameplay frame is live; see frame_state().
    """
    done = []
    for real, sh in sorted(SHADOW_OF.items(), key=lambda kv: kv[1]):
        name, length = SLOTS[sh]
        if not game.write_slot_inline(base, sh, "0" * length):
            log.error(f"shadow: write refused for slot {sh} ({name}) — heap mode? "
                "will retry")
            return False
        if game.read_slot(base, sh, length) != "0" * length:
            log.debug(f"shadow: slot {sh} ({name}) did not read back — retrying")
            return False
        done.append(f"{sh}:{name}({length})")
    log.debug("shadow: initialised " + ", ".join(done))
    return True

# Patcher / Trampolines

class Patcher:
    def __init__(self, proc):
        self.p = proc

    def site_state(self, rva, orig, new):
        cur = self.p.read(self.p.base + rva, len(orig))
        if cur is None:
            return "unreadable"
        if cur == new:
            return "patched"
        if cur == orig:
            return "clean"
        return "foreign"

    def entry_state(self, e):
        if not e.enabled:
            return "off"
        if not e.ready:
            return "pending"
        sites = e.sites()
        if not sites:
            return "none"          # trampoline-only entry, nothing in place
        seen = {self.site_state(rva, o, n) for _, rva, o, n in sites}
        if seen == {"clean"}:
            return "clean"
        if seen == {"patched"}:
            return "patched"
        if "foreign" in seen or "unreadable" in seen:
            return "foreign"
        return "mixed"

    def apply(self, log, entries=None):
        entries = entries if entries is not None else ENTRIES
        applied = skipped = 0
        for e in entries:
            st = self.entry_state(e)
            if st == "patched":
                applied += 1
                continue
            if st == "none":
                continue                    # trampoline-only, nothing in place
            if st in ("pending", "off"):
                skipped += 1
                continue
            if st != "clean":
                log.error(f"patch: {e.id} ABORT — byte state is '{st}'. Wrong build, "
                    "or something else already wrote there.")
                skipped += 1
                continue
            ok = True
            for label, rva, orig, new in e.sites():
                if not self.p.write(self.p.base + rva, new):
                    log.error(f"patch: {e.id} WRITE FAILED at +{rva:X} ({label})")
                    ok = False
                    break
            if ok and self.entry_state(e) == "patched":
                applied += 1
            else:
                log.error(f"patch: {e.id} verification failed after write")
        log.debug(f"patch: {applied} in-place row(s) redirected, {skipped} skipped")
        return applied

    def revert(self, log, entries=None):
        entries = entries if entries is not None else ENTRIES
        n = 0
        for e in entries:
            if not e.ready or not e.sites():
                continue
            for label, rva, orig, _ in e.sites():
                if not self.p.write(self.p.base + rva, orig):
                    log.error(f"unpatch: WRITE FAILED at +{rva:X} ({e.id}/{label})")
                    return n
            n += 1
        log.info(f"unpatch: {n} row(s) restored")
        return n


class Trampolines:
    """One stub per site, in a single page within rel32 reach
    """

    def __init__(self, proc):
        self.p = proc
        self.stub_base = None
        self.saved = {}
        self.installed = set()

    @staticmethod
    def plan(entries=None):
        """[(entry, label, rva, covered, kind)] for every trampoline site."""
        out = []
        for e in (entries if entries is not None else ENTRIES):
            if not e.enabled or e.shadow is None or not e.ready:
                continue
            for label, rva, covered, kind in e.detour_sites:
                out.append((e, label, rva, covered, kind))
        return out

    def _alloc_near(self, size, log):
        base = self.p.base
        step = ALLOC_GRANULARITY
        mbi = MEMORY_BASIC_INFORMATION64()
        probes = 0
        for direction in (1, -1):
            addr = (base + direction * step) & ~(step - 1)
            while abs(addr - base) < REL32_REACH and probes < 60000:
                probes += 1
                if addr < 0x10000:
                    break
                ok = k32.VirtualQueryEx(self.p.handle, ctypes.c_void_p(addr),
                                        ctypes.byref(mbi), ctypes.sizeof(mbi))
                if not ok:
                    addr += direction * step
                    continue
                if mbi.State == MEM_FREE:
                    target = max((mbi.BaseAddress + step - 1) & ~(step - 1), addr)
                    room = mbi.BaseAddress + mbi.RegionSize - target
                    if room >= size and abs(target - base) < REL32_REACH:
                        p = k32.VirtualAllocEx(
                            self.p.handle, ctypes.c_void_p(target), size,
                            MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
                        if p:
                            log.debug(f"trampolines: stub page at {p:X} "
                                f"({p - base:+X} from the module)")
                            return p
                # advance, rounding AWAY from the module so we never revisit
                if direction > 0:
                    nxt = (mbi.BaseAddress + mbi.RegionSize + step - 1) & ~(step - 1)
                    addr = max(nxt, addr + step)
                else:
                    prv = (mbi.BaseAddress - 1) & ~(step - 1)
                    addr = min(prv, addr - step)
        log.error(f"trampolines: no free page within rel32 range ({probes} probes)")
        return None

    def site_state(self, rva, expect):
        cur = self.p.read(self.p.base + rva, JMP_LEN)
        if cur is None:
            return "unreadable"
        if cur[0] == 0xE9:
            return "installed"
        if expect and cur[:4] == expect[:4]:
            return "clean"
        return "foreign"

    def state(self, entries=None):
        seen = {self.site_state(rva, e.expect_at(rva, kind))
                for e, _, rva, _, kind in self.plan(entries)}
        if not seen:
            return "none"
        if seen == {"clean"}:
            return "clean"
        if seen == {"installed"}:
            return "installed"
        return "mixed" if "foreign" not in seen else "foreign"

    def install(self, log, entries=None):
        sites = self.plan(entries)
        if not sites:
            return True
        st = self.state(entries)
        if st == "installed":
            return True
        if st not in ("clean", "mixed"):
            log.error(f"trampolines: ABORT — site bytes are '{st}'. Wrong build, or "
                "something else already patched these addresses.")
            return False

        payloads = []
        for e, label, rva, covered, kind in sites:
            want = e.expect_at(rva, kind)
            cur = self.p.read(self.p.base + rva, covered)
            if cur is None:
                log.error(f"trampolines: ABORT — cannot read +{rva:X} ({e.id}/{label})")
                return False
            if not want:
                log.error(f"trampolines: ABORT — no confirmed bytes recorded for "
                    f"+{rva:X} ({e.id}/{label})")
                return False
            if cur[:len(want)] != want:
                if cur[0] == 0xE9:
                    continue
                log.error(f"trampolines: ABORT — +{rva:X} ({e.id}/{label}) is "
                    f"{cur[:len(want)].hex(' ').upper()}, expected "
                    f"{want.hex(' ').upper()}")
                return False
            payloads.append((e, label, rva, covered, kind, cur))
        if not payloads:
            return True

        need = sum(stub_size(c, k) for _, _, _, c, k, _ in payloads)
        page = max(0x1000, (need + 0xFFF) & ~0xFFF)
        if self.stub_base is None:
            self.stub_base = self._alloc_near(page, log)
            if self.stub_base is None:
                return False

        cursor = self.stub_base
        done = 0
        for e, label, rva, covered, kind, original in payloads:
            site_addr = self.p.base + rva
            shadow_disp = slot_disp(e.shadow)
            try:
                if kind == "base":
                    stub = build_stub_base(cursor, shadow_disp, original,
                                           site_addr, site_addr + covered,
                                           e.base_pi)
                elif kind == "slot":
                    stub = build_stub_slot(cursor, e.shadow, original,
                                           site_addr, site_addr + covered,
                                           e.base_pi)
                else:
                    stub = build_stub(cursor, shadow_disp, original[4:],
                                      site_addr + covered)
                patch = jmp_rel32(site_addr, cursor)
            except ValueError as exc:
                log.error(f"trampolines: ABORT — {e.id}/{label}: {exc}")
                return False
            patch += NOP * (covered - JMP_LEN)
            if not self.p.write(cursor, stub):
                log.error(f"trampolines: stub write failed for {e.id}/{label}")
                return False
            if self.p.read(cursor, len(stub)) != stub:
                log.error(f"trampolines: stub verification failed for {e.id}/{label}")
                return False
            if not self.p.write(site_addr, patch):
                log.error(f"trampolines: site write failed at +{rva:X}")
                return False
            self.saved[rva] = original
            self.installed.add(rva)
            cursor += len(stub)
            done += 1

        if self.state(entries) != "installed":
            log.error("trampolines: verification failed after install")
            return False
        by_entry = {}
        for e, _, _, _, kind in sites:
            by_entry.setdefault(e.id, set()).add(kind.upper())
        log.debug(f"trampolines: {done} site(s) installed and verified — "
            + ", ".join(f"{k}({'/'.join(sorted(v))})"
                        for k, v in sorted(by_entry.items())))
        return True

    def remove(self, log, entries=None):
        n = 0
        for e, label, rva, covered, kind in self.plan(entries):
            original = self.saved.get(rva)
            if original is None:
                if rva in self.installed:
                    log.warning(f"trampolines: no saved bytes for +{rva:X} — "
                        "restart the game to restore it")
                continue
            if not self.p.write(self.p.base + rva, original):
                log.error(f"trampolines: restore failed at +{rva:X}")
                return n
            self.installed.discard(rva)
            n += 1
        self.saved.clear()
        log.debug(f"trampolines: {n} site(s) restored")
        return n

# Attachment — attach, wait for a frame, patch, initialise shadows

DETACHED = "detached"
WAITING = "waiting"
READY = "ready"


class Attachment:
    """Drives the process to a patched, shadow-initialised state.
    step() is idempotent; call it every poll. Returns DETACHED / WAITING / READY. shadow_generation increments whenever the shadows are re-initialised, signalling the caller to re-push its location ledger.
    """

    def __init__(self, log, debounce=INIT_DEBOUNCE_SECONDS):
        self.log = log
        self.debounce = debounce
        self.proc = None
        self.game = None
        self.patcher = None
        self.tramp = None
        self.sbase = None
        self.vbase = None
        self.prev_base = None
        self.patched = False
        self.shadow_ready = False
        self.shadow_generation = 0
        self.hpmax_writable = None      # None untested / False refused / True ok
        self.ready_since = None
        self.last_why = None
        self._last_attach_try = 0.0

    # --- lifecycle ---
    def detach(self, why=""):
        if self.proc:
            self.proc.close()
        self.proc = self.game = self.patcher = self.tramp = None
        self.prev_base = self.sbase = self.vbase = None
        self.patched = self.shadow_ready = False
        self.hpmax_writable = None
        self.ready_since = None
        self.last_why = None
        if why:
            self.log.info(f"detached: {why}")

    def _try_attach(self):
        now = time.monotonic()
        if now - self._last_attach_try < 2.0:
            return False
        self._last_attach_try = now
        try:
            self.proc = Process(PROCESS_NAME)
        except AttachError as exc:
            if self.last_why != str(exc):
                self.log.debug(f"attach: {exc}")
                self.last_why = str(exc)
            self.proc = None
            return False
        self.game = Game(self.proc)
        self.patcher = Patcher(self.proc)
        self.tramp = Trampolines(self.proc)
        self.log.debug(f"attached: pid {self.proc.pid}, module {self.proc.base:X}")
        self.last_why = None
        return True

    # --- one poll ---
    def step(self):
        if self.proc is None and not self._try_attach():
            return DETACHED

        if not self.proc.alive():
            self.detach("game process is gone")
            return DETACHED

        sbase = self.game.strings_base()
        vbase = self.game.values_base()
        if not sbase or not vbase:
            self.ready_since = None
            return WAITING
        self.sbase, self.vbase = sbase, vbase

        if sbase != self.prev_base:
            if self.prev_base is not None:
                self.log.debug(f"string table reallocated ({self.prev_base:X} -> "
                         f"{sbase:X}) — shadows must be rewritten")
                self.shadow_ready = False
            self.prev_base = sbase
            self.ready_since = None

        ok, why = frame_state(self.game, sbase)
        if not ok:
            self.ready_since = None
            if why != self.last_why:
                self.log.debug(f"waiting: {why}")
                self.last_why = why
            return WAITING
        if self.ready_since is None:
            self.ready_since = time.monotonic()
        waited = time.monotonic() - self.ready_since
        if waited < self.debounce:
            return WAITING

        # Patching from the menu leaves the ability strip blank, so patch and shadow init both happen here, after the debounce.
        if not self.patched:
            if not self.tramp.install(self.log):
                self.ready_since = None          # back off, do not spin
                return WAITING
            expected = sum(1 for e in ENTRIES if e.enabled and e.ready and e.sites())
            applied = self.patcher.apply(self.log)
            if applied == 0 and expected:
                self.log.error("patch: NOTHING applied. This is almost certainly the "
                         "wrong build — the RVAs are for the C++ port (Oct "
                         "2024), not the original Fusion executable.")
                self.ready_since = None
                return WAITING
            if applied < expected:
                self.log.error(f"patch: only {applied}/{expected} in-place row(s) "
                         "took. Some pedestals will still hand out vanilla "
                         "items.")
            self.patched = True
            self.log.info("patch: game is redirected to the shadow slots")

        if not self.shadow_ready:
            if not init_shadows(self.game, sbase, self.log):
                return WAITING
            self.shadow_ready = True
            self.shadow_generation += 1

        self.last_why = None
        return READY

    # --- convenience ---
    def read(self, slot):
        name, length = SLOTS[slot]
        return self.game.read_slot(self.sbase, slot, length)

    def write(self, slot, text):
        return self.game.write_slot_inline(self.sbase, slot, text)

    def unpatch(self):
        if not self.proc:
            return
        self.tramp.remove(self.log)
        self.patcher.revert(self.log)
        self.patched = False
