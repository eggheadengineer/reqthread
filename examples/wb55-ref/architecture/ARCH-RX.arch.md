---
id: ARCH-RX
safety_related: true
integrity_level: SIL3
---
# Receiver safety channel

Receives heartbeat frames over the radio link, authenticates and sequences them, and supervises their arrival. Drives the machine-enable output. The radio stack and transport are a black channel: nothing in this element trusts them.
