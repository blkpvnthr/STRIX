/*
 * strix_native.c — native-CPU quantitative kernels (R1 §5.3, §8, L).
 *
 * Two-pass algorithms are used for variance/covariance to minimise
 * catastrophic cancellation, keeping agreement with the exact Decimal
 * reference tight enough to pass parity certification. Kernels return NaN on
 * invalid input so the Python caller fails closed rather than fabricating a
 * value.
 */
#include "strix_native.h"

#include <math.h>

#define STRIX_NATIVE_ABI 1

int strix_native_abi_version(void) { return STRIX_NATIVE_ABI; }

double strix_sum(const double *x, size_t n) {
    if (n == 0) {
        return NAN;
    }
    double s = 0.0;
    for (size_t i = 0; i < n; i++) {
        s += x[i];
    }
    return s;
}

double strix_mean(const double *x, size_t n) {
    if (n == 0) {
        return NAN;
    }
    return strix_sum(x, n) / (double)n;
}

double strix_minimum(const double *x, size_t n) {
    if (n == 0) {
        return NAN;
    }
    double m = x[0];
    for (size_t i = 1; i < n; i++) {
        if (x[i] < m) {
            m = x[i];
        }
    }
    return m;
}

double strix_maximum(const double *x, size_t n) {
    if (n == 0) {
        return NAN;
    }
    double m = x[0];
    for (size_t i = 1; i < n; i++) {
        if (x[i] > m) {
            m = x[i];
        }
    }
    return m;
}

double strix_variance(const double *x, size_t n, int sample) {
    size_t denom_floor = sample ? 1 : 0;
    if (n <= denom_floor) {
        return NAN;
    }
    double mu = strix_mean(x, n);
    double ss = 0.0;
    for (size_t i = 0; i < n; i++) {
        double d = x[i] - mu;
        ss += d * d;
    }
    double denom = (double)(n - denom_floor);
    return ss / denom;
}

double strix_stdev(const double *x, size_t n, int sample) {
    double var = strix_variance(x, n, sample);
    if (isnan(var)) {
        return NAN;
    }
    return sqrt(var);
}

double strix_covariance(const double *x, const double *y, size_t n, int sample) {
    size_t denom_floor = sample ? 1 : 0;
    if (n <= denom_floor) {
        return NAN;
    }
    double mx = strix_mean(x, n);
    double my = strix_mean(y, n);
    double acc = 0.0;
    for (size_t i = 0; i < n; i++) {
        acc += (x[i] - mx) * (y[i] - my);
    }
    double denom = (double)(n - denom_floor);
    return acc / denom;
}

double strix_correlation(const double *x, const double *y, size_t n) {
    if (n < 2) {
        return NAN;
    }
    double mx = strix_mean(x, n);
    double my = strix_mean(y, n);
    double sxy = 0.0, sxx = 0.0, syy = 0.0;
    for (size_t i = 0; i < n; i++) {
        double dx = x[i] - mx;
        double dy = y[i] - my;
        sxy += dx * dy;
        sxx += dx * dx;
        syy += dy * dy;
    }
    /* Fail closed if any sum-of-squares is non-finite (overflow) or a variance
     * is non-positive (undefined correlation) — never fabricate a value. */
    if (!isfinite(sxx) || !isfinite(syy) || !isfinite(sxy) || sxx <= 0.0 || syy <= 0.0) {
        return NAN;
    }
    /* Scale before multiplying so sxx*syy cannot overflow to +Inf (which the old
     * code turned into a fabricated 0.0 via a finite/Inf division). */
    double r = (sxy / sqrt(sxx)) / sqrt(syy);
    if (!isfinite(r)) {
        return NAN;
    }
    return r;
}
