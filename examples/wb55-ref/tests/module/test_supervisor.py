"""Module tests for heartbeat supervision, run against the C code via ctypes."""
import ctypes
from ctypes import byref, c_uint32


class HbState(ctypes.Structure):
    _fields_ = [("last_valid_ms", ctypes.c_uint32), ("enable", ctypes.c_bool), ("started", ctypes.c_bool)]


def _started(lib, now=0):
    lib.hb_supervise.restype = ctypes.c_bool
    s = HbState()
    lib.hb_init(byref(s), c_uint32(now))
    return s


def test_trip_after_300ms(lib):
    """@verifies SSR-001"""
    s = _started(lib)
    lib.hb_on_valid_frame(byref(s), c_uint32(1000))
    assert lib.hb_supervise(byref(s), c_uint32(1299))
    assert not lib.hb_supervise(byref(s), c_uint32(1300))


def test_enable_requires_valid_frame(lib):
    """@verifies SSR-001"""
    s = _started(lib)
    assert not lib.hb_supervise(byref(s), c_uint32(10))


def test_timer_wraparound(lib):
    """@verifies SSR-001"""
    s = _started(lib)
    lib.hb_on_valid_frame(byref(s), c_uint32(0xFFFFFF00))
    assert lib.hb_supervise(byref(s), c_uint32(0x00000010))       # 272 ms after the frame
    assert not lib.hb_supervise(byref(s), c_uint32(0x00000030))   # 304 ms
