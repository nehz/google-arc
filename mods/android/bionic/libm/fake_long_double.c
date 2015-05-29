/*
 * Copyright (C) 2013 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <float.h>
#include <math.h>
// ARC MOD BEGIN bionic-long-double
#include <complex.h>
// ARC MOD END
// ARC MOD BEGIN UPSTREAM bionic-isnanl-crash-on-x86
// When sizeof(long double) != sizeof(double) (i.e., bare_metal_i686),
// isnan macro will be expanded to __isnanl, hence it causes an
// infinite recursion.
#undef isnan
// ARC MOD END UPSTREAM

// ARC MOD BEGIN bionic-long-double
// TODO(crbug.com/432441): Compile our code with 64bit long double.
// Note: These functions originally assume long double is 64bit, but it is
// actually 80bit under Bare Metal i686, so they loses precisions.
// ARC MOD END
#ifndef __LP64__
/*
 * The BSD "long double" functions are broken when sizeof(long double) == sizeof(double).
 * Android works around those cases by replacing the broken functions with our own trivial stubs
 * that call the regular "double" function.
 */

long double copysignl(long double a1, long double a2) { return copysign(a1, a2); }
long double fabsl(long double a1) { return fabs(a1); }
long double fmaxl(long double a1, long double a2) { return fmax(a1, a2); }
long double fmodl(long double a1, long double a2) { return fmod(a1, a2); }
long double fminl(long double a1, long double a2) { return fmin(a1, a2); }
int ilogbl(long double a1) { return ilogb(a1); }
long long llrintl(long double a1) { return llrint(a1); }
long lrintl(long double a1) { return lrint(a1); }
long long llroundl(long double a1) { return llround(a1); }
long lroundl(long double a1) { return lround(a1); }
long double modfl(long double a1, long double* a2) { double i; double f = modf(a1, &i); *a2 = i; return f; }
float nexttowardf(float a1, long double a2) { return nextafterf(a1, (float) a2); }
long double roundl(long double a1) { return round(a1); }

#endif // __LP64__
// ARC MOD BEGIN bionic-long-double
// TODO(crbug.com/432441): Compile our code with 64bit long double.
// Here we define additional stubs for 80bit long double under bare metal i686,
// possibly losing precisions.
#if LDBL_MANT_DIG != 53

// Note: The list of math functions to be wrapped can be obtained by:
// grep -r __weak_reference third_party/android/bionic/libm | sed '/imprecise/d;/#define/d;s/.*, //;s/).*//' | sort

#define SIMPLE_LONG_DOUBLE_MAP(name) \
  long double name ## l (long double a) { return name(a); }

SIMPLE_LONG_DOUBLE_MAP(acosh);
SIMPLE_LONG_DOUBLE_MAP(acos);
SIMPLE_LONG_DOUBLE_MAP(asinh);
SIMPLE_LONG_DOUBLE_MAP(asin);
SIMPLE_LONG_DOUBLE_MAP(atanh);
SIMPLE_LONG_DOUBLE_MAP(atan);
SIMPLE_LONG_DOUBLE_MAP(cbrt);
SIMPLE_LONG_DOUBLE_MAP(ceil);
SIMPLE_LONG_DOUBLE_MAP(cos);
SIMPLE_LONG_DOUBLE_MAP(exp2);
SIMPLE_LONG_DOUBLE_MAP(exp);
SIMPLE_LONG_DOUBLE_MAP(expm1);
SIMPLE_LONG_DOUBLE_MAP(floor);
SIMPLE_LONG_DOUBLE_MAP(log10);
SIMPLE_LONG_DOUBLE_MAP(log1p);
SIMPLE_LONG_DOUBLE_MAP(log2);
SIMPLE_LONG_DOUBLE_MAP(logb);
SIMPLE_LONG_DOUBLE_MAP(log);
SIMPLE_LONG_DOUBLE_MAP(rint);
SIMPLE_LONG_DOUBLE_MAP(sin);
SIMPLE_LONG_DOUBLE_MAP(sqrt);
SIMPLE_LONG_DOUBLE_MAP(tan);
SIMPLE_LONG_DOUBLE_MAP(trunc);
int __signbitl(long double a1) { return __signbit(a1); }
long double atan2l(long double a1, long double a2) { return atan2(a1, a2); }
long double fmal(long double a1, long double a2, long double a3) { return fma(a1, a2, a3); }
long double frexpl(long double a1, int* exp) { return frexp(a1, exp); }
long double hypotl(long double a1, long double a2) { return hypot(a1, a2); }
long double ldexpl(long double a1, int exp) { return scalbn(a1, exp); }
long double nanl(const char* tagp) { return nan(tagp); }
long double nextafterl(long double a1, long double a2) { return nextafter(a1, a2); }
double nexttoward(double a1, long double a2) { return nextafter(a1, a2); }
long double nexttowardl(long double a1, long double a2) { return nextafter(a1, a2); }
long double remainderl(long double a1, long double a2) { return remainder(a1, a2); }
long double remquol(long double a1, long double a2, int* quo) { return remquo(a1, a2, quo); }
long double scalbnl(long double a1, int exp) { return scalbn(a1, exp); }

#define EXPORT __attribute__((__visibility__("default")))
// android-21/arch-x86/usr/lib/libm.so exports these 3 symbols.
EXPORT long double cabsl(long double complex a1) { return cabs(a1); }
EXPORT long double complex cprojl(long double complex a1) { return cproj(a1); }
EXPORT long double complex csqrtl(long double complex a1) { return csqrt(a1); }

#endif  // LDBL_MANT_DIG != 53
// ARC MOD END
