#!/usr/bin/env python3
"""patch table

Static description of every site the client touches.

Split from the data.py, because if some wrong addresses break the client, it doesn't stop the seed generation and you can (probably) use an old version of the client.
Therefore seed generation and client are seperate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

__all__ = [
    "ALL_INDICES",
    "ENTRIES",
    "ENTRIES_BY_SLOT",
    "ENTRY_BY_ID",
    "ENTRY_BY_SLOT",
    "Entry",
    "IconFix",
    "JMP_LEN",
    "NOP",
    "REAL_OF",
    "REAL_SLOTS",
    "REG8",
    "REG8_REX",
    "REG64",
    "RUNTIME_STRINGS",
    "SHADOW_OF",
    "SITE_EXPECT",
    "SLOTS",
    "STRING_COUNT",
    "STRING_STRIDE",
    "SUPPRESSION_MODE",
    "VALUE_COUNT",
    "add_rdx",
    "mov_edx",
    "read_slot_for",
    "select_sites",
    "shadow_coverage",
    "shadow_live",
    "slot_disp",
    "test_reg8",
]

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
    8: 19,   # mark       -> +0x4C0
}
REAL_OF = {v: k for k, v in SHADOW_OF.items()}

SLOTS = {}
for _s, (_n, _l) in REAL_SLOTS.items():
    SLOTS[_s] = (_n, _l)
for _real, _sh in SHADOW_OF.items():
    _n, _l = REAL_SLOTS[_real]
    SLOTS[_sh] = ("shadow_" + _n, _l)

def slot_disp(slot: int) -> int:
    return slot * STRING_STRIDE

def add_rdx(disp: int) -> bytes:
    """add rdx, imm32 — the 7-byte form."""
    return b"\x48\x81\xC2" + struct.pack("<I", disp)

def mov_edx(k: int) -> bytes:
    return b"\xBA" + struct.pack("<I", k)

JMP_LEN = 5
NOP = b"\x90"

# what a 4-byte trampoline site must contain before touching it
SITE_EXPECT = {
    1: bytes.fromhex("4883C240"),      # ADD RDX,0x40
    2: bytes.fromhex("4883EA80"),      # SUB RDX,-0x80
}

REG64 = {"rax": 0, "rcx": 1, "rdx": 2, "rbx": 3, "rsi": 6, "rdi": 7}
REG8 = {"al": 0, "cl": 1, "dl": 2, "bl": 3}
# These only exist with a REX prefix, so TEST becomes three bytes, not two.
REG8_REX = {"spl": 4, "bpl": 5, "sil": 6, "dil": 7}
RUNTIME_STRINGS = 0x102E0          # runtime + this = the Global String table

@dataclass
class IconFix:
    """Where the icon lives in one pickup event, and how to reach it."""
    branch_rva: int                 # test <flag>,<flag> ; jnz <exit>
    icon_rva: int                   # first instruction of the icon block
    exit_rva: int                   # where the jnz goes (function epilogue)
    base_reg: str = "rdi"           # register holding the runtime pointer there
    flag_reg: str = "bl"            # the byte SETcc wrote

    @property
    def branch_len(self) -> int:
        """TEST (2, or 3 with a REX prefix) + JNZ rel32 (6)."""
        return len(test_reg8(self.flag_reg)) + 6

    @property
    def expect(self) -> bytes:
        """The exact bytes the branch site must hold."""
        rel = self.exit_rva - (self.branch_rva + self.branch_len)
        return test_reg8(self.flag_reg) + b"\x0F\x85" + struct.pack("<i", rel)

def test_reg8(name: str) -> bytes:
    """test <r8>,<r8>, with the REX prefix when the register needs one."""
    if name in REG8:
        code, rex = REG8[name], b""
    elif name in REG8_REX:
        code, rex = REG8_REX[name], b"\x40"
    else:
        raise ValueError("unsupported 8-bit register %r" % name)
    return rex + bytes([0x84, 0xC0 | (code << 3) | code])

# "first": the gate deciding both pedestal destruction reads the shadow. "last" would leave that gate on the real flag, so an item received from AP would destroy its own pedestal. 
# Do. not. change. Please.
SUPPRESSION_MODE = "first"

def select_sites(sites):
    if len(sites) <= 1 or SUPPRESSION_MODE == "all":
        return list(sites)
    key = (lambda s: s if isinstance(s, int) else s[0])
    ordered = sorted(sites, key=key)
    return [ordered[0]] if SUPPRESSION_MODE == "first" else [ordered[-1]]

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
    icon: object = None             # IconFix: re-light the HUD icon, see above
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
        if self.icon is not None:
            if not isinstance(self.icon, IconFix):
                bad("icon must be an IconFix")
            if not isinstance(self.index, int):
                bad("icon rescue needs a single int index, got %r" % (self.index,))
            if self.icon.base_reg not in REG64 or \
                    self.icon.flag_reg not in REG8 and self.icon.flag_reg not in REG8_REX:
                bad("icon rescue: unsupported register (%s / %s)"
                    % (self.icon.base_reg, self.icon.flag_reg))
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
        if self.icon is not None:
            out.append(("icon rescue", self.icon.branch_rva,
                        self.icon.branch_len, "icon"))
        return out

    def expect_at(self, rva, kind):
        """Bytes the site must currently hold, or None if unknowable."""
        if kind == "icon":
            return self.icon.expect
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
          grant_src_rva=0x2F3331, grant_slot_rva=0x2F3384,
          icon=IconFix(branch_rva=0x2F5899, icon_rva=0x2F58F3, exit_rva=0x2F599C)),
    Entry("lisa24", "Teleport Access", 5, 24,
          suppress_fn=0x2F5510, pedestal=0xA5D8,
          suppress_rvas=[0x2F553B, 0x2F5636], grant_fn=0x2F2A20,
          grant_src_rva=0x2F2AF1, grant_slot_rva=0x2F2B44,
          icon=IconFix(branch_rva=0x2F55B9, icon_rva=0x2F5613, exit_rva=0x2F56BC)),

    # trampoline sites (4-byte encodings)
    Entry("tavarat0", "Rough Map", 2, 0, suppress_fn=0x2F4BB0, pedestal=0x3708,
          cave_sites=[(0x2F4BDB, 7), (0x2F4CCB, 7)], grant_fn=0x2F1B70,
          grant_src_cave=(0x2F1C41, 12), grant_slot_rva=0x2F1C8E,
          icon=IconFix(branch_rva=0x2F4C53, icon_rva=0x2F4CA8, exit_rva=0x2F4D4B)),
    Entry("tavarat1", "Hookshot", 2, 1, suppress_fn=0x2F6000, pedestal=0x4830,
          cave_sites=[(0x2F602B, 10), (0x2F6126, 10)], grant_fn=0x2F40C0,
          grant_src_cave=(0x2F4191, 12), grant_slot_rva=0x2F41E1,
          icon=IconFix(branch_rva=0x2F60A6, icon_rva=0x2F6103, exit_rva=0x2F61A9)),
    Entry("tavarat2", "Propeller", 2, 2, suppress_fn=0x2F68E0, pedestal=0x54D8,
          cave_sites=[(0x2F690B, 10), (0x2F6A06, 10)], grant_fn=0x2F4660,
          grant_src_cave=(0x2F4731, 12), grant_slot_rva=0x2F4781,
          icon=IconFix(branch_rva=0x2F6986, icon_rva=0x2F69E3, exit_rva=0x2F6A89)),
    Entry("tavarat3", "Charge Shot", 2, 3, suppress_fn=0x2F5CF0, pedestal=0x55F8,
          cave_sites=[(0x2F5D1B, 10), (0x2F5E16, 10)], grant_fn=0x2F37E0,
          grant_src_cave=(0x2F38B1, 12), grant_slot_rva=0x2F3901,
          icon=IconFix(branch_rva=0x2F5D96, icon_rva=0x2F5DF3, exit_rva=0x2F5E99)),
    Entry("tavarat4", "Heat-Resistant suit", 2, 4, suppress_fn=0x2F4D70,
          pedestal=0x8070,
          cave_sites=[(0x2F4D9B, 10), (0x2F4E96, 10)], grant_fn=0x2F1E30,
          grant_src_cave=(0x2F1F01, 12), grant_slot_rva=0x2F1F51,
          icon=IconFix(branch_rva=0x2F4E16, icon_rva=0x2F4E73, exit_rva=0x2F4F19)),
    Entry("tavarat5", "Plasma Shield", 2, 5, suppress_fn=0x2F4F30, pedestal=0x8538,
          cave_sites=[(0x2F4F5B, 10), (0x2F5056, 10)], grant_fn=0x2F20F0,
          grant_src_cave=(0x2F21D1, 12), grant_slot_rva=0x2F2221,
          icon=IconFix(branch_rva=0x2F4FD6, icon_rva=0x2F5033, exit_rva=0x2F50D9)),
    Entry("tavarat5b", "Plasma Shield (2nd suppression)", 2, 5,
          suppress_fn=0x2F59C0, cave_sites=[(0x2F59E6, 10)], suppression_only=True),
    Entry("tavarat6", "Triple Shot", 2, 6, suppress_fn=0x2F50F0, pedestal=0x8A48,
          cave_sites=[(0x2F511B, 10), (0x2F5213, 10), (0x2F52AD, 10)],
          grant_fn=0x2F24A0,
          grant_src_cave=(0x2F2571, 12), grant_slot_rva=0x2F25C1,
          icon=IconFix(branch_rva=0x2F5196, icon_rva=0x2F51F3, exit_rva=0x2F5331)),
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
          grant_src_cave=(0x2F3EB1, 12), grant_slot_rva=0x2F3F29,
          icon=IconFix(branch_rva=0x2FDAC3, icon_rva=0x2FDB18, exit_rva=0x2FDBBB)),
    Entry("bombs1", "Dash Booster V", 1, 1, suppress_fn=0x2F5350, pedestal=0x93D8,
          cave_sites=[(0x2F537B, 10), (0x2F5476, 10)], grant_fn=0x2F2760,
          grant_src_cave=(0x2F2831, 12), grant_slot_rva=0x2F2881,
          # +2F53F6  TEST BL,BL ; JNZ +2F54F9   (BL = "the shadow says no")
          # +2F53FE  destroy the pedestal   |   +2F5453  show and frame the icon
          icon=IconFix(branch_rva=0x2F53F6, icon_rva=0x2F5453,
                       exit_rva=0x2F54F9)),
    Entry("health_all", "All 8 Health Packs", 0, "computed",
          suppress_fn=0x2F4920, pedestal=0x2118, grant_fn=0x2F1490,
          base_sites=[(0x2F493D, 7)],
          grant_src_base=(0x2F155F, 7),
          grant_slot_base=(0x2F15EE, 5),
          nop_sites=[(0x2F1737, 5)],

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
    ),
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
          ),
    # text monitor in mark
    Entry("mark2", "Password", 8, 2,
          suppress_fn=0x3757B0,
          suppress_rvas=[0x375866],     # ADD RDX,0x200 -> str_size_helper (Mid$ guard) at +37587B
          grant_fn=0x3757B0,
          grant_src_rva=0x37597A,       # ADD RDX,0x200 -> parser_set_source at +375981
          grant_slot_rva=0x375A72,      # MOV EDX,8     -> set_global_string at +375A7A
          note="bytes checked against the listing, not yet in-game"),
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
