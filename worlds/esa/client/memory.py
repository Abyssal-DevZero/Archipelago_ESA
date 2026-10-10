"""Game-side layer: process attach, global tables, shadow patch set."""

from __future__ import annotations

import ctypes
import struct
import sys
import time

from .patchdata import *

WINDOWS = sys.platform == "win32"

if WINDOWS:
    import ctypes.wintypes as wt
else:                       # lets the module import off Windows; nothing here runs there
    class wt:
        DWORD = ctypes.c_uint32
        HMODULE = ctypes.c_void_p
        WCHAR = ctypes.c_wchar

PROCESS_NAME = "Environmental Station Alpha.exe"

RVA_RUNTIME = 0x771120
RVA_GLOBAL_VALUES = 0x771128
RVA_GLOBAL_STRINGS = 0x771130

# cached INI files (respawn edit)
RVA_INI_CACHE = 0x7F0D80
MAP_SENTINEL = 0x08
MAP_SIZE = 0x10
NODE_KEY = 0x10
NODE_VALUE = 0x50
INLINE_MAX = 0x3E
SAVE_FILE_NAME = "esa_save.lar"
SHIP_SPAWN = {"paikkax": "11", "paikkay": "9", "pelaajax": "252", "pelaajay": "65"}

# runtime + offset
EVENTGROUP_PICKUP = 0x105B6         # pickup event group enable byte
OBJ_PLAYER = 0x1668                 # player instance
OBJ_HP_COUNTER = 0x3AB0             # HP bar counter
# also: 0x16B0 pickup message box, 0x2118 Health Pack pedestal
# object + 0x20 -> data block; data + 0x280 + n*8 -> Alterable Value n (double)

# Counter objects keep state in direct fields
COUNTER_VALUE = 0xC0                # double, current
COUNTER_MAX = 0xCC                  # int32, maximum

# Patching or writing shadows before a gameplay frame has run this long blanks the ability HUD.
INIT_DEBOUNCE_SECONDS = 4.0

SLOT_VALUE_INDEX = 2                # Global Value: active save slot
HPMAX_VALUE_INDEX = 6               # Global Value: saved max HP
VALUE_DO_NOT_WRITE = {2: "active save slot", 3: "current HP", 0x1A: "pickup sound volume"}
HPMAX_BASE = 10


def hpmax_for(upgrades: int) -> int:
    """Max HP after N Health Packs: +4 for the first two, +2 after."""
    return HPMAX_BASE + 4 * min(upgrades, 2) + 2 * max(0, upgrades - 2)


# x86-64 encoding

def _rel32(op: bytes, what: str, frm: int, to: int) -> bytes:
    rel = to - (frm + len(op) + 4)
    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise ValueError(f"{what} out of rel32 range: {rel:+d}")
    return op + struct.pack("<i", rel)


def jmp_rel32(frm: int, to: int) -> bytes:
    return _rel32(b"\xE9", "jump", frm, to)


def call_rel32(frm: int, to: int) -> bytes:
    return _rel32(b"\xE8", "call", frm, to)


def _jcc8(op: int, skip: int) -> bytes:
    if skip > 0x7F:
        raise ValueError(f"short jump over {skip} bytes")
    return bytes([op, skip])


def _mem_operand(op: int, ext: int, base_reg: str, disp: int, imm: bytes = b"") -> bytes:
    """`op /ext` on [base_reg + disp]; disp8 when it fits. `ext` is the modrm reg field."""
    rm = REG64[base_reg]
    if -0x80 <= disp <= 0x7F:
        return bytes([op, 0x40 | (ext << 3) | rm, disp & 0xFF]) + imm
    return bytes([op, 0x80 | (ext << 3) | rm]) + struct.pack("<i", disp) + imm

RIP_MOV_RDX = b"\x48\x8B\x15"       # mov rdx, [rip + d32]

def relocate(original: bytes, site_addr: int, stub_addr: int, declared_pi: bool = False) -> bytes:
    """Displaced bytes, rewritten to run at stub_addr."""
    if original[:3] == RIP_MOV_RDX and len(original) >= 7:
        target = site_addr + 7 + struct.unpack_from("<i", original, 3)[0]
        new_d = target - (stub_addr + 7)
        if not -0x80000000 <= new_d <= 0x7FFFFFFF:
            raise ValueError("relocated RIP displacement out of range")
        return RIP_MOV_RDX + struct.pack("<i", new_d) + original[7:]
    if declared_pi:
        return original
    raise ValueError(f"displaced bytes {original.hex(' ').upper()} are not a known RIP-relative "
                     "load; if they are position-independent, set base_pi=True on the entry")


def with_return(stub_addr: int, body: bytes, return_addr: int) -> bytes:
    """body ; jmp return_addr"""
    return body + jmp_rel32(stub_addr + len(body), return_addr)


def _if_owned(at: int, base_reg: str, disp: int, index: int, then) -> bytes:
    """Run then(addr) only if the slot at `disp` is inline and char `index` is above '0'.
    """
    head = mov_r64_mem("rdx", base_reg, RUNTIME_STRINGS)
    head += _mem_operand(0xF6, 0, "rdx", disp, b"\x01")             # test byte [slot],1 (heap)
    cmp = _mem_operand(0x80, 7, "rdx", disp + 1 + index, b"\x30")   # cmp byte [char],'0'
    body = then(at + len(head) + 2 + len(cmp) + 2)
    tail = cmp + _jcc8(0x76, len(body)) + body                       # jbe past
    return head + _jcc8(0x75, len(tail)) + tail                      # jnz past


def build_icon_stub(stub_addr: int, fix: IconFix, real_disp: int, index: int, base: int) -> bytes:
    """Shadow has it: vanilla path. Otherwise, real slot owned: light the icon. Else exit."""
    code = test_reg8(fix.flag_reg) + b"\x75\x05"                     # jnz: ask the real slot
    code += jmp_rel32(stub_addr + len(code), base + fix.branch_rva + fix.branch_len)

    def light(at):
        out = b""
        if fix.show_slot is not None:                                # show it ourselves
            out = b"\xB2\x01" + mov_r64_mem("rcx", fix.base_reg, fix.show_slot)
            out += call_rel32(at + len(out), base + fix.show_fn)
        return out + jmp_rel32(at + len(out), base + fix.icon_rva)

    code += _if_owned(stub_addr + len(code), fix.base_reg, real_disp, index, light)
    return code + jmp_rel32(stub_addr + len(code), base + fix.exit_rva)


def build_guard_stub(stub_addr: int, fix: IconFix, disp: int, index: int,
                     original: bytes, return_addr: int, exit_addr: int) -> bytes:
    """Slot at `disp` owns `index`: run the displaced bytes and continue. Else exit."""
    code = _if_owned(stub_addr, fix.base_reg, disp, index,
                     lambda at: with_return(at, original, return_addr))
    return code + jmp_rel32(stub_addr + len(code), exit_addr)


ICON_STUB_MAX = 80
GUARD_STUB_MAX = 48
TAIL_LEN = {"base": 7, "slot": 5}

def stub_size(covered: int, kind: str = "cave") -> int:
    """Upper bound on one stub."""
    if kind == "icon":
        return ICON_STUB_MAX
    if kind in ("guard", "owned"):
        return GUARD_STUB_MAX
    if kind in TAIL_LEN:
        return covered + TAIL_LEN[kind] + JMP_LEN
    return covered + 3 + JMP_LEN                                      # imm8 add grows to imm32

# Win32

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
    # Without these, ctypes returns a 32-bit int and truncates addresses above 4 GB.
    k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                   ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
    k32.VirtualAllocEx.restype = ctypes.c_void_p
else:
    k32 = None

class AttachError(Exception):
    pass

class Process:
    """ReadProcessMemory / WriteProcessMemory wrapper."""

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
            raise AttachError(f"OpenProcess failed (err {ctypes.get_last_error()}), "
                              "run the client as administrator")

    @staticmethod
    def _snapshot(flags, pid, entry, first, nxt):
        """Yield each entry of a Toolhelp snapshot."""
        snap = k32.CreateToolhelp32Snapshot(flags, pid)
        if snap == INVALID_HANDLE_VALUE:
            return
        try:
            entry.dwSize = ctypes.sizeof(entry)
            ok = first(snap, ctypes.byref(entry))
            while ok:
                yield entry
                ok = nxt(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)

    @classmethod
    def _find_pid(cls, name):
        for e in cls._snapshot(TH32CS_SNAPPROCESS, 0, PROCESSENTRY32W(),
                               k32.Process32FirstW, k32.Process32NextW):
            if e.szExeFile.lower() == name.lower():
                return e.th32ProcessID
        return None

    @classmethod
    def _module_base(cls, pid, name):
        for m in cls._snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid, MODULEENTRY32W(),
                               k32.Module32FirstW, k32.Module32NextW):
            if m.szModule.lower() == name.lower():
                return ctypes.cast(m.modBaseAddr, ctypes.c_void_p).value
        return None

    def read(self, addr, size):
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr),
                                   ctypes.byref(buf), size, ctypes.byref(got))
        return bytes(buf) if ok and got.value == size else None

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
        k32.VirtualProtectEx(self.handle, ctypes.c_void_p(addr), size, old, ctypes.byref(old))
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
    """User-mode, 8-aligned, non-null."""
    return bool(p) and 0x10000 <= p < 0x7FFF_FFFF_FFFF and not (p & 7)


class Game:
    def __init__(self, proc):
        self.p = proc

    def strings_base(self):
        return self.p.read_u64(self.p.base + RVA_GLOBAL_STRINGS)

    def values_base(self):
        return self.p.read_u64(self.p.base + RVA_GLOBAL_VALUES)

    def runtime(self):
        return self.p.read_u64(self.p.base + RVA_RUNTIME)

    def runtime_ok(self, rt=None):
        """The runtime's cached string table pointer matches the global one."""
        rt = self.runtime() if rt is None else rt
        cached = self.p.read_u64(rt + RUNTIME_STRINGS) if rt else None
        return bool(cached) and cached == self.strings_base()

    def read_u8(self, addr):
        b = self.p.read(addr, 1)
        return b[0] if b else None

    # Chowdren strings: byte 0 bit 0 set = heap (size u32 at +4, pointer at +8),
    # clear = inline (length << 1, chars from +1).

    def _raw_str(self, addr, heap_max, inline_max):
        head = self.p.read(addr, 16)
        if head is None:
            return None
        if head[0] & 1:
            size, ptr = struct.unpack_from("<IQ", head, 4)
            if not (0 < size <= heap_max) or not ptr:
                return None
            raw = self.p.read(ptr, size)
        else:
            size = head[0] >> 1
            if size > inline_max:
                return None
            raw = head[1:1 + size] if size <= 15 else self.p.read(addr + 1, size)
        return raw if raw is not None and len(raw) == size else None

    def read_slot(self, base, slot, expect_len=None):
        """Global String `slot` as ASCII, or None on a torn/invalid read."""
        raw = self._raw_str(base + slot * STRING_STRIDE, 4096, STRING_STRIDE - 1)
        if raw is None or (expect_len is not None and len(raw) != expect_len):
            return None
        if any(b not in PRINTABLE for b in raw):
            return None
        return raw.decode("ascii")

    def read_str_at(self, addr, max_len=1024):
        """Any Chowdren string (file paths may be non-ASCII)."""
        raw = self._raw_str(addr, max_len, INLINE_MAX)
        return None if raw is None else raw.decode("utf-8", errors="replace")

    def write_slot_inline(self, base, slot, text):
        """Overwrite a slot inline. Refuses heap mode: it would clobber the pointer."""
        if len(text) > STRING_STRIDE - 2:
            return False
        elem = base + slot * STRING_STRIDE
        head = self.p.read(elem, 1)
        if head is None or head[0] & 1:
            return False
        return self.p.write(elem, bytes([len(text) << 1]) + text.encode("ascii"))

    def write_char(self, base, slot, index, ch, expect_len):
        """Poke one character of an inline slot of the expected length."""
        if len(ch) != 1 or not 0 <= index < expect_len:
            return False
        elem = base + slot * STRING_STRIDE
        head = self.p.read(elem, 1)
        if head is None or head[0] & 1 or (head[0] >> 1) != expect_len:
            return False
        return self.p.write(elem + 1 + index, ch.encode("ascii"))

    # Global Values: 8-byte doubles

    def read_value(self, base, index):
        b = self.p.read(base + index * 8, 8)
        return struct.unpack("<d", b)[0] if b else None

    def write_value(self, base, index, x):
        return self.p.write(base + index * 8, struct.pack("<d", float(x)))

    def active_slot(self):
        """Loaded save slot 1-3, or None. The values base moves, so it is re-read."""
        vb = self.values_base()
        v = self.read_value(vb, SLOT_VALUE_INDEX) if vb else None
        return int(v) if v in (1.0, 2.0, 3.0) else None

    # INI cache: std::map, sentinel at +8, size at +0x10; node key at +0x10, value at +0x50

    def map_nodes(self, map_addr, limit=256):
        sentinel = self.p.read_u64(map_addr + MAP_SENTINEL)
        count = self.p.read_u64(map_addr + MAP_SIZE)
        if not plausible_ptr(sentinel) or count is None or count > limit:
            return
        node = self.p.read_u64(sentinel)
        for _ in range(count):                      # count bounds a torn list
            if not plausible_ptr(node) or node == sentinel:
                return
            yield node
            node = self.p.read_u64(node)

    def map_find(self, map_addr, match):
        for node in self.map_nodes(map_addr):
            key = self.read_str_at(node + NODE_KEY)
            if key is not None and match(key):
                return node
        return None

    def save_keys_map(self, slot):
        """Key map of [save{slot}] in the cached esa_save.lar, or None."""
        f = self.map_find(self.p.base + RVA_INI_CACHE,
                          lambda k: k.replace("\\", "/").lower().endswith("/" + SAVE_FILE_NAME))
        sec = self.map_find(f + NODE_VALUE, lambda k: k == f"save{slot}") if f else None
        return sec + NODE_VALUE if sec else None

    def read_save_key(self, keys_map, key):
        node = self.map_find(keys_map, lambda k: k == key)
        return self.read_str_at(node + NODE_VALUE) if node else None

    def write_save_key(self, keys_map, key, text):
        """Inline only; the prefix byte carries the new length."""
        if len(text) > INLINE_MAX:
            return False
        node = self.map_find(keys_map, lambda k: k == key)
        if node is None:
            return False
        elem = node + NODE_VALUE
        head = self.p.read(elem, 1)
        if head is None or head[0] & 1:
            return False
        payload = bytes([len(text) << 1]) + text.encode("ascii") + b"\0"
        return self.p.write(elem, payload) and self.read_str_at(elem) == text

    # Objects

    def object_instances(self, slot, limit=64):
        """Live instances of an object type.

        runtime + slot: default instance, often null. runtime + slot + 8: instance list,
        head index at +8, then 16-byte entries {instance, next index at +8}.
        """
        rt = self.runtime()
        if not rt or not self.runtime_ok(rt):
            return []
        out = []
        direct = self.p.read_u64(rt + slot)
        if plausible_ptr(direct):
            out.append(direct)
        lst = self.p.read_u64(rt + slot + 8)
        head = self.p.read(lst + 8, 4) if plausible_ptr(lst) else None
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

    def read_counter(self, slot):
        """(current, maximum) of a Counter object, or None."""
        obj = self.object_ptr(slot)
        cur = self.p.read(obj + COUNTER_VALUE, 8) if obj else None
        mx = self.p.read(obj + COUNTER_MAX, 4) if obj else None
        if cur is None or mx is None:
            return None
        return struct.unpack("<d", cur)[0], struct.unpack("<i", mx)[0]

    def _write_field(self, slot, off, data):
        obj = self.object_ptr(slot)
        return bool(obj) and self.p.write(obj + off, data)

    def write_counter_max(self, slot, n):
        return self._write_field(slot, COUNTER_MAX, struct.pack("<i", int(n)))

    def write_counter_value(self, slot, x):
        return self._write_field(slot, COUNTER_VALUE, struct.pack("<d", float(x)))

def frame_state(game, sbase):
    """(ready, why). Slots are readable at the menu too; the event group and player are not."""
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
    """Fill every shadow slot with zeros of its real slot's length."""
    done = []
    for sh in sorted(REAL_OF):
        name, length = SLOTS[sh]
        if not game.write_slot_inline(base, sh, "0" * length):
            log.error(f"shadow: write refused for slot {sh} ({name}), heap mode? will retry")
            return False
        if game.read_slot(base, sh, length) != "0" * length:
            log.debug(f"shadow: slot {sh} ({name}) did not read back, retrying")
            return False
        done.append(f"{sh}:{name}({length})")
    log.debug("shadow: initialised " + ", ".join(done))
    return True

# Patching

class Patcher:
    """In-place sites."""

    def __init__(self, proc):
        self.p = proc

    def site_state(self, rva, orig, new):
        cur = self.p.read(self.p.base + rva, len(orig))
        if cur is None:
            return "unreadable"
        return "patched" if cur == new else "clean" if cur == orig else "foreign"

    def entry_state(self, e):
        if not e.enabled:
            return "off"
        if not e.ready:
            return "pending"
        sites = e.sites()
        if not sites:
            return "none"                           # stub-only entry
        seen = {self.site_state(rva, o, n) for _, rva, o, n in sites}
        if len(seen) == 1 and seen <= {"clean", "patched"}:
            return seen.pop()
        return "foreign" if seen & {"foreign", "unreadable"} else "mixed"

    def apply(self, log, entries=None):
        applied = skipped = 0
        for e in ENTRIES if entries is None else entries:
            st = self.entry_state(e)
            if st == "patched":
                applied += 1
                continue
            if st == "none":
                continue
            if st != "clean":
                if st not in ("pending", "off"):
                    log.error(f"patch: {e.id} ABORT, byte state is '{st}'. Wrong build, "
                              "or something else already wrote there.")
                skipped += 1
                continue
            for label, rva, _, new in e.sites():
                if not self.p.write(self.p.base + rva, new):
                    log.error(f"patch: {e.id} WRITE FAILED at +{rva:X} ({label})")
                    break
            else:
                if self.entry_state(e) == "patched":
                    applied += 1
                    continue
            log.error(f"patch: {e.id} verification failed after write")
        log.debug(f"patch: {applied} in-place row(s) redirected, {skipped} skipped")
        return applied

    def revert(self, log, entries=None):
        n = 0
        for e in ENTRIES if entries is None else entries:
            if not e.ready:
                continue
            sites = e.sites()
            for label, rva, orig, _ in sites:
                if not self.p.write(self.p.base + rva, orig):
                    log.error(f"unpatch: WRITE FAILED at +{rva:X} ({e.id}/{label})")
                    return n
            n += bool(sites)
        log.info(f"unpatch: {n} row(s) restored")
        return n

class Trampolines:
    """Stub sites: one stub each, packed into a page within rel32 reach."""

    def __init__(self, proc):
        self.p = proc
        self.stub_base = self.cursor = self.stub_end = None
        self.saved = {}
        self.installed = set()

    @staticmethod
    def plan(entries=None):
        """[(entry, label, rva, covered, kind)]"""
        return [(e, *site) for e in (ENTRIES if entries is None else entries)
                if e.ready for site in e.detour_sites]

    def _alloc_near(self, size, log):
        base, step = self.p.base, ALLOC_GRANULARITY
        mbi = MEMORY_BASIC_INFORMATION64()
        probes = 0
        for direction in (1, -1):
            addr = (base + direction * step) & ~(step - 1)
            while abs(addr - base) < REL32_REACH and probes < 60000 and addr >= 0x10000:
                probes += 1
                if not k32.VirtualQueryEx(self.p.handle, ctypes.c_void_p(addr),
                                          ctypes.byref(mbi), ctypes.sizeof(mbi)):
                    addr += direction * step
                    continue
                if mbi.State == MEM_FREE:
                    target = max((mbi.BaseAddress + step - 1) & ~(step - 1), addr)
                    room = mbi.BaseAddress + mbi.RegionSize - target
                    if room >= size and abs(target - base) < REL32_REACH:
                        p = k32.VirtualAllocEx(self.p.handle, ctypes.c_void_p(target), size,
                                               MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
                        if p:
                            log.debug(f"trampolines: stub page at {p:X} ({p - base:+X} from the module)")
                            return p
                # step past this region, away from the module
                if direction > 0:
                    addr = max((mbi.BaseAddress + mbi.RegionSize + step - 1) & ~(step - 1), addr + step)
                else:
                    addr = min((mbi.BaseAddress - 1) & ~(step - 1), addr - step)
        log.error(f"trampolines: no free page within rel32 range ({probes} probes)")
        return None

    def site_state(self, rva, expect):
        cur = self.p.read(self.p.base + rva, JMP_LEN)
        if cur is None:
            return "unreadable"
        if cur[0] == 0xE9:
            return "installed"
        return "clean" if expect and cur[:4] == expect[:4] else "foreign"

    def state(self, entries=None):
        seen = {self.site_state(rva, e.expect_at(rva, kind))
                for e, _, rva, _, kind in self.plan(entries)}
        if not seen:
            return "none"
        if len(seen) == 1 and seen <= {"clean", "installed"}:
            return seen.pop()
        return "foreign" if seen & {"foreign", "unreadable"} else "mixed"

    def _stub(self, e, kind, at, original, site, ret):
        sdisp = slot_disp(e.shadow)
        if kind == "base":
            return with_return(at, relocate(original, site, at, e.base_pi) + add_rdx(sdisp), ret)
        if kind == "slot":
            return with_return(at, relocate(original, site, at, e.base_pi) + mov_edx(e.shadow), ret)
        if kind == "icon":
            return build_icon_stub(at, e.icon, slot_disp(e.slot), e.index, self.p.base)
        if kind == "guard":                         # shadow decides
            return build_guard_stub(at, e.icon, sdisp, e.index, original, ret,
                                    self.p.base + e.icon.exit_rva)
        if kind == "owned":                         # real slot decides
            return build_guard_stub(at, e.icon, slot_disp(e.slot), e.index, original, ret,
                                    self.p.base + (e.icon.owned_skip or e.icon.exit_rva))
        return with_return(at, add_rdx(sdisp) + original[4:], ret)      # cave

    def install(self, log, entries=None):
        sites = self.plan(entries)
        payloads = []
        for e, label, rva, covered, kind in sites:
            where = f"+{rva:X} ({e.id}/{label})"
            cur = self.p.read(self.p.base + rva, covered)
            if cur is None:
                log.error(f"trampolines: ABORT, cannot read {where}")
                return False
            if cur[0] == 0xE9:
                continue                            # already installed
            want = e.expect_at(rva, kind)
            if not want:
                log.error(f"trampolines: ABORT, no confirmed bytes recorded for {where}")
                return False
            if cur[:len(want)] != want:
                log.error(f"trampolines: ABORT, {where} is {cur[:len(want)].hex(' ').upper()}, "
                          f"expected {want.hex(' ').upper()}. Wrong build, or something else "
                          "already patched it.")
                return False
            if kind == "icon" and e.icon.show_slot is not None:
                show_at = self.p.base + e.icon.branch_rva + e.icon.branch_len
                if self.p.read(show_at, len(e.icon.show_expect)) != e.icon.show_expect:
                    log.error(f"trampolines: ABORT, show call after {where} is not where "
                              "the IconFix says")
                    return False
            payloads.append((e, label, rva, covered, kind, cur))
        if not payloads:
            return True

        need = sum(stub_size(c, k) for _, _, _, c, k, _ in payloads)
        if self.stub_base is None or self.cursor + need > self.stub_end:
            page = max(0x1000, (need + 0xFFF) & ~0xFFF)
            self.stub_base = self._alloc_near(page, log)
            if self.stub_base is None:
                return False
            self.cursor, self.stub_end = self.stub_base, self.stub_base + page

        for e, label, rva, covered, kind, original in payloads:
            site = self.p.base + rva
            try:
                stub = self._stub(e, kind, self.cursor, original, site, site + covered)
                patch = jmp_rel32(site, self.cursor) + NOP * (covered - JMP_LEN)
            except ValueError as exc:
                log.error(f"trampolines: ABORT, {e.id}/{label}: {exc}")
                return False
            if not self.p.write(self.cursor, stub) or self.p.read(self.cursor, len(stub)) != stub:
                log.error(f"trampolines: stub write failed for {e.id}/{label}")
                return False
            if not self.p.write(site, patch):
                log.error(f"trampolines: site write failed at +{rva:X}")
                return False
            self.saved[rva] = original
            self.installed.add(rva)
            self.cursor += len(stub)

        if self.state(entries) != "installed":
            log.error("trampolines: verification failed after install")
            return False
        kinds = {}
        for e, _, _, _, kind in sites:
            kinds.setdefault(e.id, set()).add(kind.upper())
        log.debug(f"trampolines: {len(payloads)} site(s) installed and verified: "
                  + ", ".join(f"{k}({'/'.join(sorted(v))})" for k, v in sorted(kinds.items())))
        return True

    def remove(self, log, entries=None):
        n = 0
        for e, label, rva, covered, kind in self.plan(entries):
            original = self.saved.get(rva)
            if original is None:
                if rva in self.installed:
                    log.warning(f"trampolines: no saved bytes for +{rva:X}, restart the game to restore it")
                continue
            if not self.p.write(self.p.base + rva, original):
                log.error(f"trampolines: restore failed at +{rva:X}")
                return n
            self.installed.discard(rva)
            n += 1
        self.saved.clear()
        if not self.installed:
            self.cursor = self.stub_base            # nothing jumps into the page any more
        log.debug(f"trampolines: {n} site(s) restored")
        return n


# Attachment: attach, wait for a frame, patch, initialise shadows

DETACHED = "detached"
WAITING = "waiting"
READY = "ready"

class Attachment:
    """Drives the process to a patched, shadow-initialised state.

    step() is idempotent, call it every poll. shadow_generation bumps whenever the shadows are rewritten, telling the caller to re-push its ledger.
    """

    def __init__(self, log, debounce=INIT_DEBOUNCE_SECONDS):
        self.log = log
        self.debounce = debounce
        self.shadow_generation = 0
        self._last_attach_try = 0.0
        self.held_off: set[str] = set()
        self.proc = None
        self.detach()

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
            return False
        self.game = Game(self.proc)
        self.patcher = Patcher(self.proc)
        self.tramp = Trampolines(self.proc)
        self.log.debug(f"attached: pid {self.proc.pid}, module {self.proc.base:X}")
        self.last_why = None
        return True

    def step(self):
        """One poll. Returns DETACHED, WAITING or READY."""
        if self.proc is None and not self._try_attach():
            return DETACHED
        if not self.proc.alive():
            self.detach("game process is gone")
            return DETACHED

        sbase, vbase = self.game.strings_base(), self.game.values_base()
        if not sbase or not vbase:
            self.ready_since = None
            return WAITING
        self.sbase, self.vbase = sbase, vbase

        if sbase != self.prev_base:
            if self.prev_base is not None:
                self.log.debug(f"string table reallocated ({self.prev_base:X} -> {sbase:X}), "
                               "shadows must be rewritten")
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
        if time.monotonic() - self.ready_since < self.debounce:
            return WAITING

        if not self.patched:
            if not self.tramp.install(self.log):
                self.ready_since = None             # back off, don't spin
                return WAITING
            active = [e for e in ENTRIES if e.id not in self.held_off]
            expected = sum(1 for e in active if e.ready and e.sites())
            applied = self.patcher.apply(self.log, active)
            if applied == 0 and expected:
                self.log.error("patch: NOTHING applied. Almost certainly the wrong build: the RVAs "
                               "are for the C++ port (Oct 2024), not the original Fusion executable.")
                self.ready_since = None
                return WAITING
            if applied < expected:
                self.log.error(f"patch: only {applied}/{expected} in-place row(s) took. "
                               "Some pedestals will still hand out vanilla items.")
            self.patched = True
            self.log.debug("patch: game is redirected to the shadow slots")

        if not self.shadow_ready:
            if not init_shadows(self.game, sbase, self.log):
                return WAITING
            self.shadow_ready = True
            self.shadow_generation += 1

        self.last_why = None
        return READY

    def read(self, slot):
        return self.game.read_slot(self.sbase, slot, SLOTS[slot][1])

    def write(self, slot, text):
        return self.game.write_slot_inline(self.sbase, slot, text)

    def write_char(self, slot, index, ch):
        return self.game.write_char(self.sbase, slot, index, ch, SLOTS[slot][1])

    # live bisect: pull one in-place entry out of the running game

    def hold(self, entry_id):
        """Revert one in-place entry and keep it out until release()."""
        e = ENTRY_BY_ID.get(entry_id)
        if e is None:
            return f"no entry called {entry_id!r}"
        if e.detour_sites:
            return (f"{entry_id} uses trampolines and can't be pulled live: "
                    "set enabled=False on it and restart the game")
        self.held_off.add(entry_id)
        if self.patched and self.patcher:
            self.patcher.revert(self.log, [e])
        return f"{entry_id} held off, the game runs vanilla code there now"

    def release(self, entry_id):
        e = ENTRY_BY_ID.get(entry_id)
        if e is None:
            return f"no entry called {entry_id!r}"
        self.held_off.discard(entry_id)
        if self.patched and self.patcher:
            self.patcher.apply(self.log, [e])
        return f"{entry_id} re-applied"

    def unpatch(self):
        if not self.proc:
            return
        self.tramp.remove(self.log)
        self.patcher.revert(self.log)
        self.patched = False
