#ifndef FRAME_AUTH_H
#define FRAME_AUTH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FRAME_PAYLOAD_LEN 4u

typedef struct {
	uint32_t seq;
	uint8_t payload[FRAME_PAYLOAD_LEN];
	uint32_t tag;
} frame_t;

typedef struct {
	uint32_t key;
	uint32_t last_seq;
	bool have_seq;
} auth_state_t;

uint32_t frame_tag(const auth_state_t *a, const frame_t *f);
bool frame_verify(const auth_state_t *a, const frame_t *f);
bool seq_check(auth_state_t *a, const frame_t *f);
bool frame_accept(auth_state_t *a, const frame_t *f);

#endif
