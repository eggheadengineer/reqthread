"""Hardware-in-the-loop tests against the P-NUCLEO-WB55 rig (board as receiver, USB dongle as transmitter)."""
import os

import pytest

RIG = os.environ.get("WB55_RIG")


@pytest.mark.skipif(not RIG, reason="requires the WB55 HIL rig")
def test_link_loss_trips():
    """@verifies SSR-001

    Power off the transmitter dongle and assert the board drops machine-enable within 300 ms.
    """
    raise NotImplementedError("rig driver lands with the Zephyr port")
