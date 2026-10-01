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

from .patchdata import *          # the patch table; see __all__ there

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

#Respawn Manipulation
RVA_INI_CACHE = 0x7F0D80
MAP_SENTINEL = 0x08
MAP_SIZE = 0x10
NODE_KEY = 0x10
NODE_VALUE = 0x50
INLINE_MAX = 0x3E
SAVE_FILE_NAME = "esa_save.lar"
SHIP_SPAWN = {"paikkax": "11", "paikkay": "9", "pelaajax": "252", "pelaajay": "65"}

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

# Writing shadows at the title screen or straight after a table realloc leaves the ability HUD blank. Require a gameplay frame live this long first.
INIT_DEBOUNCE_SECONDS = 4.0

# Global Value 6 (+0x30) is the saved max HP
HPMAX_VALUE_INDEX = 6
SLOT_VALUE_INDEX = 2
# Indices the client must never write
VALUE_DO_NOT_WRITE = {
    2: "active save slot",
    3: "current HP",
    0x1A: "pickup sound volume",
}
HPMAX_BASE = 10


def hpmax_for(upgrades: int) -> int:
    """Max HP after N Health Pack items.  First two give +4, the rest +2."""
    return HPMAX_BASE + 4 * min(upgrades, 2) + 2 * max(0, upgrades - 2)

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


# UI fix
#
# A pickup event gates BOTH, the destrcution of an item pedestal and show UI Icon on one flag "destroy my pedestal" and "light my HUD icon" on one read of the flag.  
# Suppression points that read at the shadow so an item. This aims to re-split them.

def _mem_operand(op: int, ext: int, base_reg: str, disp: int,
                 imm: bytes = b"") -> bytes:
    """`op /ext` with operand [base_reg + disp], disp8 when it fits.

    `ext` is the opcode extension that lives in the modrm reg field — the /0,
    /7 in the manual.  Getting it wrong silently assembles a different
    instruction, so it is not optional.
    """
    rm = REG64[base_reg]
    if -0x80 <= disp <= 0x7F:
        return bytes([op, 0x40 | (ext << 3) | rm, disp & 0xFF]) + imm
    return bytes([op, 0x80 | (ext << 3) | rm]) + struct.pack("<i", disp) + imm


def mov_rdx_strings(base_reg: str) -> bytes:
    """mov rdx, [base_reg + 0x102E0]"""
    return b"\x48\x8B" + bytes([0x80 | (REG64["rdx"] << 3) | REG64[base_reg]]) \
        + struct.pack("<i", RUNTIME_STRINGS)


def jcc_rel32(cc: int, from_addr: int, to_addr: int) -> bytes:
    rel = to_addr - (from_addr + 6)
    if not -0x80000000 <= rel <= 0x7FFFFFFF:
        raise ValueError(f"conditional jump out of rel32 range: {rel:+d}")
    return bytes([0x0F, cc]) + struct.pack("<i", rel)






def build_icon_stub(stub_addr: int, fix: IconFix, real_disp: int, index: int,
                    base: int) -> bytes:
    """Absolute addresses in, stub bytes out."""
    vanilla = base + fix.branch_rva + fix.branch_len     # the destroy block
    icon = base + fix.icon_rva
    exit_addr = base + fix.exit_rva
    prefix, char = real_disp, real_disp + 1 + index

    body = test_reg8(fix.flag_reg)
    body += b"\x75\x05"                                  # jnz +5 -> ask the real flag
    body += jmp_rel32(stub_addr + len(body), vanilla)     # shadow has it: vanilla path

    head = len(body)
    tail = mov_rdx_strings(fix.base_reg)
    tail += _mem_operand(0xF6, 0, "rdx", prefix, b"\x01")  # test byte [rdx+prefix],1
    tail += b"\x75\x00"                                   # jnz -> give up (heap mode)
    heap_out = len(tail)
    tail += _mem_operand(0x80, 7, "rdx", char, b"\x30")    # cmp byte [rdx+char],'0'
    tail += b"\x76\x00"                                   # jbe -> give up (not owned)
    zero_out = len(tail)
    tail += jmp_rel32(stub_addr + head + len(tail), icon)  # owned: light the icon

    give_up = len(tail)                                    # jmp <exit> lands here
    tail = tail[:heap_out - 1] + bytes([give_up - heap_out]) + tail[heap_out:]
    tail = tail[:zero_out - 1] + bytes([give_up - zero_out]) + tail[zero_out:]
    tail += jmp_rel32(stub_addr + head + give_up, exit_addr)
    return body + tail


ICON_STUB_MAX = 64


TAIL_LEN = {"base": 7, "slot": 5}


def stub_size(covered: int, kind: str = "cave") -> int:
    if kind == "icon":
        return ICON_STUB_MAX
    if kind in TAIL_LEN:
        return covered + TAIL_LEN[kind] + JMP_LEN   # relocation keeps length
    return 7 + (covered - 4) + JMP_LEN

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

    def active_slot(self):
        """Loaded slot 1–3, or None. Re-read the base every time, it gets reallocated."""
        vb = self.values_base()
        v = self.read_value(vb, SLOT_VALUE_INDEX) if vb else None
        return int(v) if v in (1.0, 2.0, 3.0) else None

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

    def read_str_at(self, addr, max_len=1024):
        """Chowdren string anywhere (read_slot is tied to the global table)."""
        head = self.p.read(addr, 16)
        if head is None:
            return None
        if head[0] & 1:                                  # heap (the file path is)
            size = struct.unpack_from("<I", head, 4)[0]
            ptr = struct.unpack_from("<Q", head, 8)[0]
            if not (0 < size <= max_len) or not ptr:
                return None
            raw = self.p.read(ptr, size)
        else:
            size = head[0] >> 1
            if size > INLINE_MAX:
                return None
            raw = head[1:1 + size] if size <= 15 else self.p.read(addr + 1, size)
        if raw is None or len(raw) != size:
            return None
        return raw.decode("utf-8", errors="replace")     # path may hold non-ASCII

    def map_nodes(self, map_addr, limit=256):
        sentinel = self.p.read_u64(map_addr + MAP_SENTINEL)
        count = self.p.read_u64(map_addr + MAP_SIZE)
        if not plausible_ptr(sentinel) or count is None or count > limit:
            return
        node = self.p.read_u64(sentinel)
        for _ in range(count):                           # count bounds a torn list
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
        """Key map of [save{slot}] in the cached ESA_save.lar, or None."""
        cache = self.p.base + RVA_INI_CACHE
        f = self.map_find(cache, lambda k: k.replace("\\", "/").lower()
                          .endswith("/" + SAVE_FILE_NAME))
        if f is None:
            return None
        sec = self.map_find(f + NODE_VALUE, lambda k: k == f"save{slot}")
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
        if head is None or head[0] & 1:                  # heap mode: hands off
            return False
        payload = bytes([len(text) << 1]) + text.encode("ascii") + b"\0"
        return self.p.write(elem, payload) and self.read_str_at(elem) == text

    def write_char(self, base, slot, index, ch, expect_len):
        """Poke ONE character of an inline slot and leave the rest alone.
        """
        if len(ch) != 1 or not 0 <= index < expect_len:
            return False
        elem = base + slot * STRING_STRIDE
        head = self.p.read(elem, 1)
        if head is None or head[0] & 1 or (head[0] >> 1) != expect_len:
            return False                     # heap mode or wrong length: hands off
        return self.p.write(elem + 1 + index, ch.encode("ascii"))

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
    """-> (ready, why).

    Slot readability is not sufficient: init_globals fills the slots at startup, so they read fine at the main menu. The event-group byte and the player object are frame-scoped.
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
    """One stub per site, in a single page within rel32 reach"""

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
                elif kind == "icon":
                    stub = build_icon_stub(cursor, e.icon, slot_disp(e.slot),
                                           e.index, self.p.base)
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
        self.hpmax_writable = None
        self.ready_since = None
        self.last_why = None
        self._last_attach_try = 0.0
        self.held_off: set[str] = set()

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
            active = [e for e in ENTRIES if e.id not in self.held_off]
            expected = sum(1 for e in active if e.enabled and e.ready and e.sites())
            applied = self.patcher.apply(self.log, active)
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
            self.log.debug("patch: game is redirected to the shadow slots")

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

    def write_char(self, slot, index, ch):
        _, length = SLOTS[slot]
        return self.game.write_char(self.sbase, slot, index, ch, length)

    # --- live bisect: pull one entry's bytes out of the running game ---
    def hold(self, entry_id):
        """Revert one in-place entry and keep it out until release()."""
        e = ENTRY_BY_ID.get(entry_id)
        if e is None:
            return f"no entry called {entry_id!r}"
        if e.detour_sites:
            return (f"{entry_id} uses trampolines and can't be pulled live — "
                    f"set enabled=False on it and restart the game instead")
        self.held_off.add(entry_id)
        if self.patched and self.patcher:
            self.patcher.revert(self.log, [e])
        return f"{entry_id} held off — the game runs vanilla code there now"

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
