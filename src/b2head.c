/*
 * The first 16 bytes of flash bank 2, and the bank 1 side that checks them.
 *
 * Bank 2 holds leaf DSP now (prism.c, confetti.c, insert_dsp.c), programmed to 0x08100000 over the USB poke and
 * persisting across bank 1 flashes and power cycles - all proven on his unit, see BANK2.md. What does NOT persist
 * is the pairing: a bank 1 image expects the bank 2 payload built beside it, and if the two drift apart the
 * engine would call into the wrong code. So build.sh stamps one id into both banks and fills in the length and a
 * sum over the payload after the link, and bank 1 checks all three before trusting any of it.
 *
 * The check is ADVISORY in this build, not protective: the audio engine can reach a relocated effect before the
 * GUI has ever drawn, so a bad bank 2 is reported (the version label gains a trailing "!") rather than prevented.
 * Making it protective means gating the registration of these three effect types on b2_ok(), which is where the
 * public loader will have to go, since a user with only BLACKBOX.bin and no extension file must still boot.
 *
 * 3.2.z: this comment is the whole change to bank 2. The id is a hash of the bank 2 sources and this file, so the
 * payload's body is byte for byte the 3.2.u one and only its id word differs - the smallest thing the card loader
 * (b2load.c) can be given to write, for its first write on hardware.
 * 3.3.b: and again, for the same reason - a new id makes his unit a "fresh" one whose bank 2 belongs to another
 * build, which is how a first install looks. The body is still the 3.2.u payload's.
 */
#include <stdint.h>

#define B2_MAGIC 0x21324242u             /* "BB2!" */
#define BANK2    0x08100000u

__attribute__((used, section(".b2head")))
const uint32_t b2_header[4] = { B2_MAGIC, B2_ID, 0, 0 };   /* length and checksum are filled in after the link */

/* Bank 1: is the payload up there the one this image was built with, and is all of it there? */
int b2_ok(void)
{
    const volatile uint32_t *h = (const volatile uint32_t *)BANK2;
    if (h[0] != B2_MAGIC || h[1] != (uint32_t)B2_ID)
        return 0;
    uint32_t len = h[2];
    if (len < 32u || len > 0xE0000u || (len & 31u))
        return 0;                        /* not a whole number of flash words, or past sector 6 */
    uint32_t chk = 0;
    const volatile uint32_t *p = (const volatile uint32_t *)(BANK2 + 16u);
    for (uint32_t i = 16u; i < len; i += 4u)
        chk += *p++;
    return chk == h[3];
}
