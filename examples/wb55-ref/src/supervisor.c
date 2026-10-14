#include "supervisor.h"

/* @implements DD-TIMEOUT */
void hb_init(hb_state_t *s, uint32_t now_ms)
{
	s->last_valid_ms = now_ms;
	s->enable = false;
	s->started = true;
}

/* @satisfies SSR-001
 * @implements DD-TIMEOUT */
void hb_on_valid_frame(hb_state_t *s, uint32_t now_ms)
{
	s->last_valid_ms = now_ms;
	s->enable = true;
}

/* @satisfies SSR-001
 * @implements DD-TIMEOUT */
bool
hb_supervise(hb_state_t *s, uint32_t now_ms)
{
	uint32_t elapsed = now_ms - s->last_valid_ms; /* unsigned: wrap-safe */

	if (!s->started) {
		s->enable = false;
	} else if (elapsed >= HB_TIMEOUT_MS) {
		s->enable = false;
	}
	return s->enable;
}
