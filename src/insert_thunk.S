/*
 * Per-pad insert: the four hooks in the pad process functions (see insert.c). Each replaces one four-byte
 * `ldrb.w r3, [r4, #stage]` (r4 = the pad) with a bl here, and hands back r3 as stock would have loaded it.
 * lr is free at all four sites (the functions saved it on entry; class A only uses it as a scratch register in a loop
 * elsewhere that sets it first). Nothing but r3 may change: r0-r2 and r12 are saved round the C calls.
 */
    .syntax unified
    .thumb
    .text

    .equ STAGE_A, 0x560          /* class A: the pad's pan / level stage is on */
    .equ STAGE_B, 0xb8c          /* class B: the same */

/* @0x080599ec and @0x08068830: "take a separate mix buffer?" Stock says yes when the byte is set (or a send is). */
    .macro buf_hook name, stage
    .global \name
    .thumb_func
    .type \name, %function
\name:
    ldrb.w  r3, [r4, #\stage]
    cbnz    r3, 1f
    push    {r0, r1, r2, r3, r12, lr}
    mov     r0, r4
    bl      insert_on
    str     r0, [sp, #12]                /* the saved r3 */
    pop     {r0, r1, r2, r3, r12, lr}
1:  bx      lr
    .endm

    buf_hook insert_buf_a, STAGE_A
    buf_hook insert_buf_b, STAGE_B

/*
 * The early return, both classes. With no voice sounding, stock reads pad + 0x28 and gives up on the pad unless it
 * is set: class A @0x08059966 (FUN_080596b0), class B @0x08067fd4 (FUN_08067fa4) - the same instruction on the same
 * byte, with the pad in r4 in both. A pad carrying the live input has to render anyway, so answer yes for it.
 * r0 is live at the class B site (it is copied to r6 straight after), so it is saved and restored like the rest.
 */
    .macro live_hook name
    .global \name
    .thumb_func
    .type \name, %function
\name:
    ldrb.w  r3, [r4, #0x28]
    cbnz    r3, 1f
    push    {r0, r1, r2, r3, r12, lr}
    mov     r0, r4
    bl      insert_live
    str     r0, [sp, #12]                /* the saved r3 */
    pop     {r0, r1, r2, r3, r12, lr}
1:  bx      lr
    .endm

    live_hook insert_live_a
    live_hook insert_live_b

/* @0x08059a7c: class A, after the voice loop. [sp, #0x1c] = a separate buffer is in use, [sp, #0x18] = the buffer. */
    .global insert_run_a
    .thumb_func
    .type insert_run_a, %function
insert_run_a:
    push    {r0, r1, r2, r3, r12, lr}    /* 24 bytes */
    ldr     r1, [sp, #24 + 0x1c]
    cbz     r1, 1f
    mov     r0, r4
    ldr     r1, [sp, #24 + 0x18]
    bl      insert_process
1:  pop     {r0, r1, r2, r3, r12, lr}
    ldrb.w  r3, [r4, #STAGE_A]
    bx      lr

/* @0x0806889c: class B, after the two layers. [sp, #0x14] = the mix buffer; it is the pad's own unless it is sl. */
    .global insert_run_b
    .thumb_func
    .type insert_run_b, %function
insert_run_b:
    push    {r0, r1, r2, r3, r12, lr}
    ldr     r1, [sp, #24 + 0x14]
    cmp     r1, sl
    beq     1f
    mov     r0, r4
    bl      insert_process
1:  pop     {r0, r1, r2, r3, r12, lr}
    ldrb.w  r3, [r4, #STAGE_B]
    bx      lr

/*
 * INFO on a pad parameter screen (FUN_080a2e60, screens 0x18 .. 0x1d, @0x080a2fd6): stock loads app[0x8cc6] ("the
 * selected parameter can be modulated") and opens the modulation screen when it is set. The load is replaced by a bl
 * here: insert_info (master.c) opens the insert's knob page when the Insert row is selected and answers 0, else it
 * answers the byte. r0 = the app, which the stock code still needs.
 */
    .global insert_info_thunk
    .thumb_func
    .type insert_info_thunk, %function
insert_info_thunk:
    push    {r0, lr}
    bl      insert_info
    mov     r3, r0
    pop     {r0, lr}
    bx      lr
