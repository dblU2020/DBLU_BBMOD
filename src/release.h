/*
 * A PUBLIC build: `RELEASE=1 ./build.sh`. Two things differ from the builds that go on the test unit:
 *   - the version reads as the release's name, not the letter of a test build;
 *   - the raw USB peek / poke (usbdev.c) is left out. It reads and writes any address in the machine, bank 1's flash
 *     controls included, which is how a unit can be killed for good; it is a development tool and nothing more.
 * The name of the first release under this scheme (2026-10-13): JOEBOX 1. This fork's first, with the per-pad EQ
 * (2026-10-28): DBLUEQ1. With the classic ladder Filter Type (2026-10-31): DBLU02; the same with the EQ's other-bank
 * fix: DBLU03; with the EQ's frequencies and Q as lists (the knob types showed nothing on the unit): DBLU04; with the
 * EQ's "new note" told apart by the pad object, not its id (still glitching on the unit): DBLU05; with the Low Cut
 * fading in / out and the ENV.V mod source: DBLU06. Its public release (2026-11-04), DBLU_BBMOD_01, reads DBLUBB01.
 * Eight characters is the most a knob-page header shows before it wraps (cpu.c), so the name and its number have to
 * fit in that.
 */
#ifndef RELEASE_H
#define RELEASE_H

#define RELEASE_NAME "DBLUBB01"
_Static_assert(sizeof RELEASE_NAME - 1 <= 8, "a release name is eight characters at most: longer wraps on a knob page");

#endif
