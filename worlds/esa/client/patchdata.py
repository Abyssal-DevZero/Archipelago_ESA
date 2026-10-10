"""Patch table: every code site the client touches.

Kept apart from data.py so a bad address breaks the client, not seed generation.
"""

from __future__ import annotations

import functools
import struct
from dataclasses import dataclass, field

__all__ = [
    "ALL_INDICES", "ENTRIES", "ENTRIES_BY_SLOT", "ENTRY_BY_ID", "Entry", "IconFix",
    "JMP_LEN", "NOP", "REAL_OF", "REAL_SLOTS", "REG64", "RUNTIME_STRINGS",
    "SHADOW_OF", "SLOTS", "STRING_STRIDE", "add_rdx", "mov_edx", "mov_r64_mem",
    "read_slot_for", "shadow_coverage", "shadow_live", "slot_disp", "test_reg8",
]

STRING_STRIDE = 0x40
RUNTIME_STRINGS = 0x102E0           # runtime + this -> Global String table
JMP_LEN = 5
NOP = b"\x90"

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

# real slot -> shadow slot
SHADOW_OF = {
    6: 13,   # superjump  -> +0x340
    2: 14,   # tavarat    -> +0x380
    4: 15,   # bonus      -> +0x3C0
    1: 16,   # bombs      -> +0x400
    5: 17,   # lisa       -> +0x440
    0: 18,   # health     -> +0x480
    8: 19,   # mark       -> +0x4C0
}
REAL_OF = {sh: real for real, sh in SHADOW_OF.items()}
SLOTS = {**REAL_SLOTS, **{sh: ("shadow_" + REAL_SLOTS[r][0], REAL_SLOTS[r][1])
                          for r, sh in SHADOW_OF.items()}}

# original bytes of a 4-byte cave site, by real slot
SITE_EXPECT = {
    1: bytes.fromhex("4883C240"),   # add rdx,0x40
    2: bytes.fromhex("4883EA80"),   # sub rdx,-0x80
}

REG64 = {"rax": 0, "rcx": 1, "rdx": 2, "rbx": 3, "rsi": 6, "rdi": 7}
REG8 = {"al": 0, "cl": 1, "dl": 2, "bl": 3}
REG8_REX = {"spl": 4, "bpl": 5, "sil": 6, "dil": 7}     # need a REX prefix


def slot_disp(slot: int) -> int:
    return slot * STRING_STRIDE


def add_rdx(disp: int) -> bytes:
    """add rdx, imm32"""
    return b"\x48\x81\xC2" + struct.pack("<I", disp)


def mov_edx(k: int) -> bytes:
    """mov edx, imm32"""
    return b"\xBA" + struct.pack("<I", k)


def mov_r64_mem(dst: str, base: str, disp: int) -> bytes:
    """mov dst, [base + disp32]  (REG64 only)"""
    return b"\x48\x8B" + bytes([0x80 | (REG64[dst] << 3) | REG64[base]]) + struct.pack("<i", disp)

def test_reg8(name: str) -> bytes:
    """test r8, r8"""
    if name in REG8:
        code, rex = REG8[name], b""
    elif name in REG8_REX:
        code, rex = REG8_REX[name], b"\x40"
    else:
        raise ValueError(f"unsupported 8-bit register {name!r}")
    return rex + bytes([0x84, 0xC0 | (code << 3) | code])


@dataclass
class IconFix:
    """Where the HUD icon sits in one pickup event."""
    branch_rva: int                 # test <flag>,<flag> ; jnz <exit>
    icon_rva: int                   # first instruction of the icon block
    exit_rva: int                   # jnz target (epilogue)
    base_reg: str = "rdi"           # holds the runtime pointer there
    flag_reg: str = "bl"            # byte the SETcc wrote
    show_slot: int = None           # runtime offset of the HUD icon object
    show_fn: int = None             # show routine, called with dl=1
    guard_rva: int = None           # first instruction of the destroy block
    guard_expect: bytes = None      # its bytes: >= 5, no RIP, copied verbatim
    owned_rva: int = None
    owned_expect: bytes = None      # >= 5, no RIP, copied verbatim
    owned_skip: int = None

    @property
    def branch_len(self) -> int:
        return len(test_reg8(self.flag_reg)) + 6

    @property
    def expect(self) -> bytes:
        """Bytes the branch site must hold."""
        rel = self.exit_rva - (self.branch_rva + self.branch_len)
        return test_reg8(self.flag_reg) + b"\x0F\x85" + struct.pack("<i", rel)

    @property
    def show_expect(self) -> bytes:
        """mov dl,1 ; mov rcx,[base+show_slot] ; call show_fn, right after the branch."""
        if self.show_slot is None:
            return b""
        mov = mov_r64_mem("rcx", self.base_reg, self.show_slot)
        call_at = self.branch_rva + self.branch_len + 2 + len(mov)
        return b"\xB2\x01" + mov + b"\xE8" + struct.pack("<i", self.show_fn - (call_at + 5))

# "first" makes the pedestal-destroy gate read the shadow. "last" leaves it on the real flag, so an item received from AP destroys its own pedestal.
# To future me: Always keep "first". Kept in for debug purposes
SUPPRESSION_MODE = "first"

def select_sites(sites):
    if len(sites) <= 1 or SUPPRESSION_MODE == "all":
        return list(sites)
    ordered = sorted(sites, key=lambda s: s if isinstance(s, int) else s[0])
    return [ordered[0] if SUPPRESSION_MODE == "first" else ordered[-1]]


def _ints(v, n):
    return isinstance(v, tuple) and len(v) == n and all(isinstance(x, int) for x in v)

@dataclass
class Entry:
    id: str
    label: str
    slot: int
    index: object                   # int, tuple of ints, or "computed"
    suppress_fn: int = None
    pedestal: int = None
    suppress_rvas: list = field(default_factory=list)   # add rdx,imm32: in place
    cave_sites: list = field(default_factory=list)      # (rva, len) add rdx,imm8: CAVE stub
    base_sites: list = field(default_factory=list)      # (rva, len) no add: BASE stub
    nop_sites: list = field(default_factory=list)       # (rva, len) NOPed out in place
    grant_fn: int = None
    grant_src_rva: int = None
    grant_src_cave: tuple = None    # (rva, len)
    grant_src_base: tuple = None    # (rva, len)
    grant_slot_rva: int = None      # mov edx,imm32: in place
    grant_slot_base: tuple = None   # (rva, len) xor edx,edx: SLOT stub
    site_expect: dict = field(default_factory=dict)     # rva -> original bytes (BASE/SLOT/NOP)
    disp_sites: list = field(default_factory=list)      # (rva, original, patched)
    base_pi: bool = False           # displaced BASE/SLOT bytes are position-independent
    icon: IconFix = None
    suppression_only: bool = False
    grant_only: bool = False
    extra_grants: list = field(default_factory=list)    # (src rva, slot rva) extra writers
    enabled: bool = True
    note: str = ""

    def __post_init__(self):
        """Reject malformed rows at import, not mid-patch."""
        def bad(msg):
            raise ValueError(f"Entry({self.id!r}): {msg}")

        i = self.index
        if not (i == "computed" or isinstance(i, int)
                or (isinstance(i, tuple) and i and all(isinstance(x, int) for x in i))):
            bad(f"index must be an int, a non-empty tuple of ints or 'computed', got {i!r}")
        if self.grant_only and self.suppression_only:
            bad("grant_only and suppression_only are mutually exclusive")

        for f in ("suppress_fn", "pedestal", "grant_fn", "grant_src_rva", "grant_slot_rva"):
            v = getattr(self, f)
            if v is not None and not isinstance(v, int):
                bad(f"{f} must be a bare RVA, got {v!r}; (rva, len) belongs in a *_cave/*_base field")
        for f in ("grant_src_cave", "grant_src_base", "grant_slot_base"):
            v = getattr(self, f)
            if v is not None and not _ints(v, 2):
                bad(f"{f} must be (rva, len), got {v!r}")
        for f in ("cave_sites", "base_sites", "nop_sites", "extra_grants"):
            for v in getattr(self, f):
                if not _ints(v, 2):
                    bad(f"{f} entries must be int pairs, got {v!r}")
        for r in self.suppress_rvas:
            if not isinstance(r, int):
                bad(f"suppress_rvas holds bare RVAs, got {r!r}; stub sites go in cave_sites/base_sites")
        for rva, want in self.site_expect.items():
            if not isinstance(rva, int) or not isinstance(want, (bytes, bytearray)):
                bad(f"site_expect maps rva -> bytes, got {rva!r} -> {want!r}")

        for site in self.disp_sites:
            if not (isinstance(site, tuple) and len(site) == 3 and isinstance(site[0], int)
                    and all(isinstance(b, (bytes, bytearray)) for b in site[1:])):
                bad(f"disp_sites entries must be (rva, original, patched), got {site!r}")
            rva, orig, patched = site
            if len(orig) != len(patched):
                bad(f"disp_sites at +{rva:X} changes the instruction length")
            diff = [k for k, (a, b) in enumerate(zip(orig, patched)) if a != b]
            if not diff:
                bad(f"disp_sites at +{rva:X} patches to identical bytes")
            if diff[-1] - diff[0] > 3:
                bad(f"disp_sites at +{rva:X} changes more than one dword")

        fx = self.icon
        if fx is not None:
            if not isinstance(fx, IconFix):
                bad("icon must be an IconFix")
            if not isinstance(i, int):
                bad(f"icon rescue needs a single int index, got {i!r}")
            if fx.base_reg not in REG64 or fx.flag_reg not in {**REG8, **REG8_REX}:
                bad(f"icon: unsupported register ({fx.base_reg} / {fx.flag_reg})")
            if (fx.show_slot is None) != (fx.show_fn is None):
                bad("icon: show_slot and show_fn go together")
            for name, rva, raw in (("guard", fx.guard_rva, fx.guard_expect),
                                   ("owned", fx.owned_rva, fx.owned_expect)):
                if (rva is None) != (raw is None):
                    bad(f"icon: {name}_rva and {name}_expect go together")
                if raw is not None and len(raw) < JMP_LEN:
                    bad(f"icon: {name} displaces {len(raw)} byte(s), a JMP needs {JMP_LEN}")
                if raw is not None and len(raw) >= 3 and raw[2] & 0xC7 == 0x05:
                    bad(f"icon: {name} bytes are RIP-relative, they get copied verbatim")

        for label, rva, covered, kind in self.detour_sites:
            if covered < JMP_LEN:
                bad(f"{label} at +{rva:X} displaces {covered} byte(s), a JMP needs {JMP_LEN}")
            want = self.site_expect.get(rva)
            if kind in ("base", "slot") and want is not None and len(want) != covered:
                bad(f"site_expect for +{rva:X} is {len(want)} byte(s), the site displaces {covered}")

    @property
    def shadow(self):
        return SHADOW_OF.get(self.slot)

    @property
    def detour_sites(self):
        """Sites that need a stub: [(label, rva, bytes_displaced, kind)]."""
        out = [("suppression", r, c, "cave") for r, c in select_sites(self.cave_sites)]
        out += [("suppression", r, c, "base") for r, c in select_sites(self.base_sites)]
        if not self.suppression_only:
            for label, site, kind in (("grant parser source", self.grant_src_cave, "cave"),
                                      ("grant parser source", self.grant_src_base, "base"),
                                      ("grant setter slot", self.grant_slot_base, "slot")):
                if site:
                    out.append((label, *site, kind))
        fx = self.icon
        if fx is not None:
            out.append(("icon rescue", fx.branch_rva, fx.branch_len, "icon"))
            if fx.guard_rva is not None:
                out.append(("destroy guard", fx.guard_rva, len(fx.guard_expect), "guard"))
            if fx.owned_rva is not None:
                out.append(("owned guard", fx.owned_rva, len(fx.owned_expect), "owned"))
        return out

    def expect_at(self, rva, kind):
        """Bytes the site must hold before patching, or None."""
        if kind == "icon":
            return self.icon.expect
        if kind in ("guard", "owned"):
            return getattr(self.icon, kind + "_expect")
        if kind in ("base", "slot"):
            return self.site_expect.get(rva)
        return SITE_EXPECT.get(self.slot)

    @property
    def ready(self):
        """Every byte needed to patch this entry is known."""
        if not self.enabled or self.shadow is None:
            return False
        suppress = bool(self.suppress_rvas or self.cave_sites or self.base_sites)
        if not (suppress or self.nop_sites or self.disp_sites or self.grant_only):
            return False
        for rva, n in self.nop_sites:
            want = self.site_expect.get(rva)
            if not want or len(want) != n:
                return False
        if any(k in ("base", "slot") and not self.site_expect.get(r)
               for _, r, _, k in self.detour_sites):
            return False
        if self.suppression_only or not (suppress or self.grant_only):
            return True
        has_slot = self.grant_slot_rva is not None or self.grant_slot_base is not None
        has_src = any(v is not None for v in
                      (self.grant_src_rva, self.grant_src_cave, self.grant_src_base))
        return has_slot and has_src

    def sites(self):
        """In-place patches: [(label, rva, original, patched)]."""
        if self.shadow is None:
            return []
        real, sh = add_rdx(slot_disp(self.slot)), add_rdx(slot_disp(self.shadow))
        slot = (mov_edx(self.slot), mov_edx(self.shadow))
        chosen = select_sites(self.suppress_rvas)
        out = [("suppression" if len(chosen) == 1 else f"suppression #{n}", r, real, sh)
               for n, r in enumerate(chosen, 1)]
        if self.suppression_only:
            return out
        if self.grant_src_rva is not None:
            out.append(("grant parser source", self.grant_src_rva, real, sh))
        if self.grant_slot_rva is not None:
            out.append(("grant setter slot", self.grant_slot_rva, *slot))
        out += [(f"displacement #{n}", r, o, p) for n, (r, o, p) in enumerate(self.disp_sites, 1)]
        for n, (src, slot_rva) in enumerate(self.extra_grants, 2):
            out += [(f"grant parser source #{n}", src, real, sh),
                    (f"grant setter slot #{n}", slot_rva, *slot)]
        out += [("nop", r, w, NOP * n) for r, n in self.nop_sites
                if (w := self.site_expect.get(r)) and len(w) == n]
        return out


def _monitor_reads(*rvas):
    """add rdx,0x140 (lisa) -> add rdx,0x440 (shadow lisa) at each site, in place."""
    real, shadow = add_rdx(slot_disp(5)), add_rdx(slot_disp(SHADOW_OF[5]))
    return [(rva, real, shadow) for rva in rvas]


ENTRIES = [
    # in place
    Entry("superjump_all", "Jump Booster", 6, "computed",
          suppress_fn=0x2F4A60, pedestal=0x36C0,
          suppress_rvas=[0x2F4A99], grant_fn=0x2F1880,
          grant_src_rva=0x2F1951, grant_slot_rva=0x2F19D8,
          note="verified in-game"),
    Entry("superjump1b", "The Bike", 6, 1,
          grant_fn=0x2F4380, grant_src_rva=0x2F446E, grant_slot_rva=0x2F44B1,
          grant_only=True),
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
          icon=IconFix(branch_rva=0x2F55B9, icon_rva=0x2F5613, exit_rva=0x2F56BC,
                       owned_rva=0x2F5613,
                       owned_expect=bytes.fromhex("B201488B8F10AA0000"))),

    # cave stubs (4-byte encodings)
    Entry("tavarat0", "Rough Map", 2, 0, suppress_fn=0x2F4BB0, pedestal=0x3708,
      cave_sites=[(0x2F4BDB, 7), (0x2F4CCB, 7)], grant_fn=0x2F1B70,
      grant_src_cave=(0x2F1C41, 12), grant_slot_rva=0x2F1C8E,
      icon=IconFix(branch_rva=0x2F4C53, icon_rva=0x2F4CA8, exit_rva=0x2F4D4B,
                   owned_rva=0x2F4CA8, owned_expect=bytes.fromhex("B201488B8F101A0000"))),  # mov dl,1 ; mov rcx,[rdi+0x1A10]
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
    Entry("tavarat4", "Heat-Resistant suit", 2, 4, suppress_fn=0x2F4D70, pedestal=0x8070,
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
          cave_sites=[(0x2F511B, 10), (0x2F5213, 10), (0x2F52AD, 10)], grant_fn=0x2F24A0,
          grant_src_cave=(0x2F2571, 12), grant_slot_rva=0x2F25C1,
          icon=IconFix(branch_rva=0x2F5196, icon_rva=0x2F51F3, exit_rva=0x2F5331)),
    Entry("tavarat7", "?? unassigned", 2, 7, suppress_fn=0x2F56E0, pedestal=0xA9C8,
          cave_sites=[(0x2F5706, 10)], grant_fn=0x2F2FA0,
          grant_src_cave=(0x2F3071, 12), grant_slot_rva=0x2F30C1,
          note="deleted item: patched defensively, NOT an AP location"),
    Entry("tavarat8", "Supercharge Module", 2, 8, suppress_fn=0x2F6AA0, pedestal=0xB040,
          cave_sites=[(0x2F6ACB, 10), (0x2F6BC8, 10)], grant_fn=0x2F2CE0,
          grant_src_cave=(0x2F2DB1, 12), grant_slot_rva=0x2F2E01,
          icon=IconFix(branch_rva=0x2F6B46, icon_rva=0x2F6BB3, exit_rva=0x2F6C4C,
                       show_slot=0x21A8, show_fn=0x78240)),
    Entry("tavarat9", "Gold Keycard", 2, 9, suppress_fn=0x2F6C70, pedestal=0xB988,
          cave_sites=[(0x2F6C9B, 10), (0x2F6D43, 10)], grant_fn=0x2F3520,
          grant_src_cave=(0x2F35F1, 12), grant_slot_rva=0x2F3641,
          icon=IconFix(branch_rva=0x2F6D17, icon_rva=0x2F6D20, exit_rva=0x2F6E13,
                       base_reg="rbx", flag_reg="dil",
                       guard_rva=0x2F6DC6,
                       guard_expect=bytes.fromhex("488D8B88B90000"))),  # lea rcx,[rbx+0xB988]
    Entry("bombs0", "Dash Booster H", 1, 0, suppress_fn=0x2FDA20, pedestal=0x6B10,
          cave_sites=[(0x2FDA4B, 7), (0x2FDB3B, 7)], grant_fn=0x2F3DE0,
          grant_src_cave=(0x2F3EB1, 12), grant_slot_rva=0x2F3F29,
          icon=IconFix(branch_rva=0x2FDAC3, icon_rva=0x2FDB18, exit_rva=0x2FDBBB)),
    Entry("bombs1", "Dash Booster V", 1, 1, suppress_fn=0x2F5350, pedestal=0x93D8,
          cave_sites=[(0x2F537B, 10), (0x2F5476, 10)], grant_fn=0x2F2760,
          grant_src_cave=(0x2F2831, 12), grant_slot_rva=0x2F2881,
          icon=IconFix(branch_rva=0x2F53F6, icon_rva=0x2F5453, exit_rva=0x2F54F9)),

    # base / slot stubs
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

    # Power monitor
    Entry("lisa8", "Power", 5, 8,
          grant_fn=0x378A10, grant_src_rva=0x378B35, grant_slot_rva=0x378B70,
          disp_sites=_monitor_reads(0x371F7F)),

    # Gate monitors. fires when the interaction object (+0x810) holds the monitor's "activate" text. 
    # A per-gate cluster of state events sets the monitor (+0x29D0) text/frame from the gate flag every frame:
    #   flag "0" + power "1" -> activate text   (the only state the grant accepts)
    #   flag "1"/"2" + power "1" -> "enabled", green frame
    #   flag "0" + power "0" -> no-power frame (Alpha only)

    Entry("lisa18", "Gate Alpha", 5, 0x12,
          grant_fn=0x37E0E0, grant_src_rva=0x37E195, grant_slot_rva=0x37E1E8,
          disp_sites=_monitor_reads(0x37C63F, 0x37C83F, 0x37CA6F, 0x37CC9F)),
    Entry("lisa19", "Gate Beta", 5, 0x13,
          grant_fn=0x37E370, grant_src_rva=0x37E425, grant_slot_rva=0x37E478,
          disp_sites=_monitor_reads(0x37CEAF, 0x37D0AF, 0x37D2DF)),
    Entry("lisa20", "Gate Gamma", 5, 0x14,
          grant_fn=0x37E600, grant_src_rva=0x37E6B5, grant_slot_rva=0x37E708,
          disp_sites=_monitor_reads(0x37D4EF, 0x37D6EF, 0x37D91F)),
    Entry("lisa21", "Gate Delta", 5, 0x15,
          grant_fn=0x37E890, grant_src_rva=0x37E945, grant_slot_rva=0x37E998,
          disp_sites=_monitor_reads(0x37DB2F, 0x37DD2F, 0x37DF5F)),
    Entry("lisa_pillars", "Pillars 1-4", 5, (0x20, 0x21, 0x22, 0x23),
          suppress_fn=0x384E30, pedestal=0xBD78,
          suppress_rvas=[0x384F17],
          grant_fn=0x39D5E0,
          grant_src_rva=0x39D682, grant_slot_rva=0x39D6C2,      # Pillar 1
          extra_grants=[
              (0x39D792, 0x39D7D2),                             # Pillar 2
              (0x39D8A2, 0x39D8E2),                             # Pillar 3
              (0x39D9B2, 0x39D9F2),                             # Pillar 4
          ]),
    Entry("lisa_keys", "Boss Keys", 5, (0x26, 0x27, 0x28, 0x29),
          suppress_fn=0x301C00, pedestal=0xCFC8, grant_fn=0x301C00,
          disp_sites=[
              # fn 140301C00, no-keys-held branch
              (0x301CFA, bytes.fromhex("4881C340010000"), bytes.fromhex("4881C340040000")),
              (0x30209E, bytes.fromhex("4881C240010000"), bytes.fromhex("4881C240040000")),
              (0x302138, bytes.fromhex("488D8E40010000"), bytes.fromhex("488D8E40040000")),
              (0x302144, bytes.fromhex("0FB68640010000"), bytes.fromhex("0FB68640040000")),
              (0x30214F, bytes.fromhex("488D8E41010000"), bytes.fromhex("488D8E41040000")),
              (0x302158, bytes.fromhex("488B8E48010000"), bytes.fromhex("488B8E48040000")),
              # fn 140302270, sibling branch, same shape
              (0x30236A, bytes.fromhex("4881C340010000"), bytes.fromhex("4881C340040000")),
              (0x3026FE, bytes.fromhex("4881C240010000"), bytes.fromhex("4881C240040000")),
              (0x302798, bytes.fromhex("488D8E40010000"), bytes.fromhex("488D8E40040000")),
              (0x3027A4, bytes.fromhex("0FB68640010000"), bytes.fromhex("0FB68640040000")),
              (0x3027AF, bytes.fromhex("488D8E41010000"), bytes.fromhex("488D8E41040000")),
              (0x3027B8, bytes.fromhex("488B8E48010000"), bytes.fromhex("488B8E48040000")),
          ]),

    # Password monitor in mark (the one after defeating station AI)
    Entry("mark2", "Password", 8, 2,
          suppress_fn=0x3757B0,
          suppress_rvas=[0x375866],     # add rdx,0x200 -> str_size_helper (Mid$ guard) at +37587B
          grant_fn=0x3757B0,
          grant_src_rva=0x37597A,       # add rdx,0x200 -> parser_set_source at +375981
          grant_slot_rva=0x375A72,)      # mov edx,8 -> set_global_string at +375A7A
]

ENTRY_BY_ID = {e.id: e for e in ENTRIES}
ENTRIES_BY_SLOT = {}
for _e in ENTRIES:
    ENTRIES_BY_SLOT.setdefault(_e.slot, []).append(_e)

ALL_INDICES = object()


@functools.cache
def shadow_coverage(real_slot):
    """Indices of `real_slot` redirected into its shadow.

    ALL_INDICES: a computed-index entry owns the slot. Empty: read the real slot.
    Cached: ENTRIES is fixed at runtime (toggle `enabled` in source, then restart).
    """
    if real_slot not in SHADOW_OF:
        return frozenset()
    covered = set()
    for e in ENTRIES_BY_SLOT.get(real_slot, ()):
        if not e.ready:
            continue
        if e.index == "computed":
            return ALL_INDICES
        covered.update(e.index if isinstance(e.index, tuple) else (e.index,))
    return frozenset(covered)


def shadow_live(real_slot, index=None):
    """Is the redirect installed for this slot (and index)?"""
    cov = shadow_coverage(real_slot)
    if cov is ALL_INDICES:
        return True
    return bool(cov) if index is None else index in cov


def read_slot_for(real_slot, index=None):
    """Slot the client reads checks from."""
    return SHADOW_OF[real_slot] if shadow_live(real_slot, index) else real_slot
