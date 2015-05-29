/* test/include/test/jemalloc_test_defs.h.  Generated from jemalloc_test_defs.h.in by configure.  */
#include "jemalloc/internal/jemalloc_internal_defs.h"
#include "jemalloc/internal/jemalloc_internal_decls.h"

/* For use by SFMT. */
/* ARC MOD BEGIN */
/* TODO(crbug.com/448358): Does not compile with nacl-clang */
// #if defined(__x86_64__)
// #define HAVE_SSE2 
// #endif
/* ARC MOD END */
/* #undef HAVE_ALTIVEC */
