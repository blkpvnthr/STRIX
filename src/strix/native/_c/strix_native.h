/*
 * strix_native.h — native-CPU quantitative kernels (R1 §5.3, §8, L).
 *
 * These kernels compute in IEEE-754 double precision and are therefore a
 * TOLERANCE-class backend: they are NOT exact against the Decimal reference and
 * must be certified for parity by the independent Python harness. Every kernel
 * returns NaN on an invalid request (e.g. empty input, sample variance of a
 * single point) so the caller can fail closed.
 */
#ifndef STRIX_NATIVE_H
#define STRIX_NATIVE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ABI version so the loader can reject a mismatched library. */
int strix_native_abi_version(void);

double strix_sum(const double *x, size_t n);
double strix_mean(const double *x, size_t n);
double strix_minimum(const double *x, size_t n);
double strix_maximum(const double *x, size_t n);

/* sample == 1 uses the (n-1) denominator; sample == 0 uses n. */
double strix_variance(const double *x, size_t n, int sample);
double strix_stdev(const double *x, size_t n, int sample);

double strix_covariance(const double *x, const double *y, size_t n, int sample);
double strix_correlation(const double *x, const double *y, size_t n);

#ifdef __cplusplus
}
#endif

#endif /* STRIX_NATIVE_H */
