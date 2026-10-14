#include <string.h>

#include "frame_auth.h"

/* Placeholder keyed checksum. NOT CRYPTOGRAPHIC: stands in for AES-CMAC on the
 * WB55 AES peripheral so this reference project builds on any host.
 * @implements DD-AUTH */
uint32_t frame_tag(const auth_state_t *a, const frame_t *f)
{
	uint32_t h = a->key ^ 0x811c9dc5u;
	uint8_t buf[sizeof f->seq + FRAME_PAYLOAD_LEN];

	memcpy(buf, &f->seq, sizeof f->seq);
	memcpy(buf + sizeof f->seq, f->payload, FRAME_PAYLOAD_LEN);
	for (size_t i = 0; i < sizeof buf; i++) {
		h = (h ^ buf[i]) * 0x01000193u;
	}
	return h;
}

/* @satisfies SSR-002
 * @implements DD-AUTH */
bool frame_verify(const auth_state_t *a, const frame_t *f)
{
	return frame_tag(a, f) == f->tag;
}

/* @satisfies SSR-003
 * @implements DD-AUTH */
bool seq_check(auth_state_t *a, const frame_t *f)
{
	if (a->have_seq && f->seq <= a->last_seq) {
		return false;
	}
	a->last_seq = f->seq;
	a->have_seq = true;
	return true;
}

/* @satisfies SSR-002, SSR-003
 * @implements DD-AUTH */
bool frame_accept(auth_state_t *a, const frame_t *f)
{
	if (!frame_verify(a, f)) {
		return false;
	}
	return seq_check(a, f);
}
