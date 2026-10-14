"""Module tests for frame authentication. Replay rejection (SSR-003) is deliberately untested."""
import ctypes
from ctypes import byref, c_uint8, c_uint32


class Frame(ctypes.Structure):
    _fields_ = [("seq", c_uint32), ("payload", c_uint8 * 4), ("tag", c_uint32)]


class Auth(ctypes.Structure):
    _fields_ = [("key", c_uint32), ("last_seq", c_uint32), ("have_seq", ctypes.c_bool)]


def _signed(lib, auth, seq):
    lib.frame_tag.restype = c_uint32
    lib.frame_accept.restype = ctypes.c_bool
    f = Frame(seq=seq)
    f.payload[:] = [1, 2, 3, 4]
    f.tag = lib.frame_tag(byref(auth), byref(f))
    return f


def test_valid_frame_accepted(lib):
    """@verifies SSR-002"""
    a = Auth(key=0x1234)
    assert lib.frame_accept(byref(a), byref(_signed(lib, a, 1)))


def test_bad_mac_rejected(lib):
    """@verifies SSR-002"""
    a = Auth(key=0x1234)
    f = _signed(lib, a, 1)
    f.tag ^= 1
    assert not lib.frame_accept(byref(a), byref(f))
