"""Fault injection against the real C receiver, through faultbench on a virtual CAN FD bus under virtual time.

The DUT below wraps libwb55.so (the same build the module tests use) so the frames faultbench injects go
through frame_accept() and hb_supervise() exactly as they would on the board. The replay scenario is here
too, deliberately left untraced: SSR-003 is the reference project's known traceability gap, and adding the
one-line trace tag to that test is the fix the gate report asks for.
"""
import ctypes
import os
import struct
from ctypes import byref, c_uint8, c_uint32

import pytest
from faultbench import CorruptTag, Delay, Drop, FaultPlan, Harness, HeartbeatSource, Replay, Stop

FTTI_MS = 300          # SSR-001: enable must drop within 300 ms of the last valid heartbeat
PERIOD_MS = 100        # 10 Hz heartbeat, so two consecutive losses are tolerated


class CFrame(ctypes.Structure):
    _fields_ = [("seq", c_uint32), ("payload", c_uint8 * 4), ("tag", c_uint32)]


class CAuth(ctypes.Structure):
    _fields_ = [("key", c_uint32), ("last_seq", c_uint32), ("have_seq", ctypes.c_bool)]


class CHb(ctypes.Structure):
    _fields_ = [("last_valid_ms", c_uint32), ("enable", ctypes.c_bool), ("started", ctypes.c_bool)]


class WB55Receiver:
    """faultbench DUT adapter over the C receiver: frame_accept() then hb_on_valid_frame()/hb_supervise()."""

    def __init__(self, lib, key=0x1234):
        self.lib = lib
        self.lib.frame_tag.restype = c_uint32
        self.lib.frame_accept.restype = ctypes.c_bool
        self.lib.hb_supervise.restype = ctypes.c_bool
        self.auth = CAuth(key=key)
        self.hb = CHb()
        self.lib.hb_init(byref(self.hb), c_uint32(0))

    def tagger(self, key, seq, payload):
        f = CFrame(seq=seq)
        f.payload[:] = list(payload)
        return self.lib.frame_tag(byref(CAuth(key=key)), byref(f))

    def on_frame(self, data, now_ms):
        seq, payload, tag = struct.unpack("<I4sI", data)
        f = CFrame(seq=seq, tag=tag)
        f.payload[:] = list(payload)
        if self.lib.frame_accept(byref(self.auth), byref(f)):
            self.lib.hb_on_valid_frame(byref(self.hb), c_uint32(now_ms))

    def step(self, now_ms):
        return bool(self.lib.hb_supervise(byref(self.hb), c_uint32(now_ms)))


@pytest.fixture
def rig():
    lib = ctypes.CDLL(os.environ["WB55_LIB"])
    dut = WB55Receiver(lib)

    def make(*faults):
        return Harness(dut, HeartbeatSource(period_ms=PERIOD_MS, tagger=dut.tagger), FaultPlan(*faults))
    return make


def test_link_loss_trips_within_ftti(rig):
    """@verifies SSR-001"""
    with rig(Stop(at_ms=1000)) as h:
        detect_ms = h.assert_safe_within(1000, FTTI_MS)
        assert detect_ms <= FTTI_MS


def test_two_lost_heartbeats_do_not_trip(rig):
    """@verifies SSR-001

    Availability side of the timeout: two consecutive lost frames at 10 Hz must not cause a nuisance trip."""
    with rig(Drop(at_ms=1000, count=2)) as h:
        h.assert_stays_enabled(PERIOD_MS, 3000)


def test_three_lost_heartbeats_trip(rig):
    """@verifies SSR-001"""
    with rig(Drop(at_ms=1000, count=3)) as h:
        h.assert_safe_within(1000, FTTI_MS)


def test_delayed_heartbeats_beyond_ftti_trip(rig):
    """@verifies SSR-001"""
    with rig(Delay(at_ms=1000, ms=400)) as h:
        h.assert_safe_within(1000, FTTI_MS + 100)


def test_forged_heartbeats_are_rejected_and_link_trips(rig):
    """@verifies SSR-002"""
    with rig(CorruptTag(at_ms=1000)) as h:
        h.assert_safe_within(1000, FTTI_MS)


def test_replayed_heartbeats_do_not_extend_enable(rig):
    # Exercises seq_check() through the real receiver. Tracing this test to SSR-003 closes the known gap.
    with rig(Replay(at_ms=1000)) as h:
        h.assert_safe_within(1000, FTTI_MS)
