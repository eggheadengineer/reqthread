---
id: DD-AUTH
derives_from: [ARCH-RX]
satisfies: [SSR-002, SSR-003]
---
# Frame authentication and sequencing

Each frame carries a sequence number and a tag over sequence and payload. A frame is accepted only if its tag verifies and its sequence number is strictly greater than the last accepted one.
