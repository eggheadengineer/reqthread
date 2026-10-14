/* @file
 * @infrastructure Host entry point for the reference project. On target, Zephyr's
 * main starts the receiver thread and holds no safety logic. */
#include <stdio.h>

int main(void)
{
	puts("wb55 black-channel receiver (reference project)");
	return 0;
}
