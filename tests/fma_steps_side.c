/* One side of tests/test_fma_steps.py's comparison ((Triforce, 11-22, the performance audit's LIFT-05)): the guest words'
   lifted C compiled against one runtime header. Built twice, -DSIDE=now with the header nx2/fma_steps.py writes and
   -DSIDE=old with the kit's (A64_NO_FMA_STEPS=1); the same lifted text and the same a64_fpx.h in both. */
#include "a64.h"
#include "fma_steps_lifted.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)

/* form 0: as lifted; 1: as a hot function has it; 2: the exact body inline (translated with the fast path off) */
void CAT(SIDE, _run)(int k, int form, Ctx *c) { (form == 0 ? CASES[k].lifted : form == 1 ? CASES[k].hot : CASES[k].exact)(c); }
int CAT(SIDE, _count)(void) { return (int)(sizeof CASES / sizeof CASES[0]); }
const char *CAT(SIDE, _name)(int k) { return CASES[k].name; }
int CAT(SIDE, _rn)(int k) { return CASES[k].rn; }
int CAT(SIDE, _rm)(int k) { return CASES[k].rm; }
int CAT(SIDE, _dbl)(int k) { return CASES[k].dbl; }
int CAT(SIDE, _recps32)(uint64_t a, uint64_t b, uint32_t fz, uint64_t *v) { return recomp_fpx_recps32(a, b, fz, v); }
int CAT(SIDE, _rsqrts32)(uint64_t a, uint64_t b, uint32_t fz, uint64_t *v) { return recomp_fpx_rsqrts32(a, b, fz, v); }
/* whether this build's steps are the fused instruction (the guard nx2/fma_steps.py gives them) */
int CAT(SIDE, _fma)(void) {
#if RECOMP_FPX_HOST == 2 && defined(__FMA__) && !defined(A64_FPX_NO_FMA32)
    return 1;
#else
    return 0;
#endif
}
