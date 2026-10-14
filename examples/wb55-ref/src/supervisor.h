#ifndef SUPERVISOR_H
#define SUPERVISOR_H

#include <stdbool.h>
#include <stdint.h>

#define HB_TIMEOUT_MS 300u

typedef struct {
	uint32_t last_valid_ms;
	bool enable;
	bool started;
} hb_state_t;

void hb_init(hb_state_t *s, uint32_t now_ms);
void hb_on_valid_frame(hb_state_t *s, uint32_t now_ms);
bool hb_supervise(hb_state_t *s, uint32_t now_ms);

#endif
