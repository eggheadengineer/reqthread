---
id: DD-TIMEOUT
derives_from: [ARCH-RX]
satisfies: [SSR-001]
---
# Heartbeat supervision timer

Records the time of the last valid frame. Each supervision call compares elapsed time (unsigned, wrap-safe) against a 300 ms limit and clears machine-enable once it is reached. Enable is only ever set by a valid frame.
