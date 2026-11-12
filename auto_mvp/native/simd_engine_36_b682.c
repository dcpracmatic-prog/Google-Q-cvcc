#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <immintrin.h>
#include <math.h>

#define N 2048
#define DENSITY 0.02
#define K_COLS 31
#define K_STRIDE 32

typedef struct {
    int *row_ptr;
    int *col_idx;
    float *values;
    int nnz;
} CSRMatrix;

void spmm_hbag_simd(const CSRMatrix *A, const float *B, float *C, int n, int k_cols, int k_stride) {
    for (int i = 0; i < n; i++) {
        int row_start = A->row_ptr[i];
        int row_end = A->row_ptr[i + 1];
        float *c_row = &C[i * k_stride];

        for (int c = 0; c < k_cols; c += 8) {
            _mm256_storeu_ps(&c_row[c], _mm256_setzero_ps());
        }

        for (int j = row_start; j < row_end; j++) {
            __m256 v_val = _mm256_set1_ps(A->values[j]);
            const float *b_row = &B[A->col_idx[j] * k_stride];

            for (int c = 0; c < k_cols; c += 8) {
                __m256 v_b = _mm256_loadu_ps(&b_row[c]);
                __m256 v_c = _mm256_loadu_ps(&c_row[c]);
                v_c = _mm256_fmadd_ps(v_val, v_b, v_c);
                _mm256_storeu_ps(&c_row[c], v_c);
            }
        }
    }
}

void spmm_csr_std(const CSRMatrix *A, const float *B, float *C, int n, int k_cols, int k_stride) {
    for (int i = 0; i < n; i++) {
        int row_start = A->row_ptr[i];
        int row_end = A->row_ptr[i + 1];

        for (int c = 0; c < k_cols; c++) {
            float sum = 0.0f;
            for (int j = row_start; j < row_end; j++) {
                sum += A->values[j] * B[A->col_idx[j] * k_stride + c];
            }
            C[i * k_stride + c] = sum;
        }
    }
}

int main() {
    printf("=== HBAG-CORE SIMD ENGINE (AVX2/FMA) | ESTRÉS K=31 ===\n\n");

    int expected_nnz = (int)(N * N * DENSITY);
    CSRMatrix A;
    A.row_ptr = (int *)malloc((N + 1) * sizeof(int));
    A.col_idx = (int *)malloc(expected_nnz * 2 * sizeof(int));
    A.values = (float *)malloc(expected_nnz * 2 * sizeof(float));

    float *B = (float *)calloc(N * K_STRIDE, sizeof(float));
    float *C_std = (float *)calloc(N * K_STRIDE, sizeof(float));
    float *C_simd = (float *)calloc(N * K_STRIDE, sizeof(float));

    int current_nnz = 0;
    A.row_ptr[0] = 0;
    srand(42);

    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            if ((float)rand() / RAND_MAX < DENSITY) {
                A.col_idx[current_nnz] = j;
                A.values[current_nnz] = (float)(rand() % 10) + 1.0f;
                current_nnz++;
            }
        }
        A.row_ptr[i + 1] = current_nnz;
    }
    A.nnz = current_nnz;

    for (int i = 0; i < N; i++) {
        for(int c = 0; c < K_COLS; c++) {
            B[i * K_STRIDE + c] = 1.0f;
        }
    }

    struct timespec start, end;

    clock_gettime(CLOCK_MONOTONIC, &start);
    spmm_csr_std(&A, B, C_std, N, K_COLS, K_STRIDE);
    clock_gettime(CLOCK_MONOTONIC, &end);
    double time_std = (end.tv_sec - start.tv_sec) + (end.tv_nsec - start.tv_nsec) / 1e9;

    clock_gettime(CLOCK_MONOTONIC, &start);
    spmm_hbag_simd(&A, B, C_simd, N, K_COLS, K_STRIDE);
    clock_gettime(CLOCK_MONOTONIC, &end);
    double time_simd = (end.tv_sec - start.tv_sec) + (end.tv_nsec - start.tv_nsec) / 1e9;

    float max_diff = 0.0f;
    for (int i = 0; i < N; i++) {
        for (int c = 0; c < K_COLS; c++) {
            float diff = fabs(C_std[i * K_STRIDE + c] - C_simd[i * K_STRIDE + c]);
            if (diff > max_diff) max_diff = diff;
        }
    }

    if (max_diff > 1e-4) {
        printf("[FAILED] Apoptosis activada. Inconsistencia numérica de fase: %f\n", max_diff);
        return 1;
    }

    double gflops_std = (2.0 * A.nnz * K_COLS) / (time_std * 1e9);
    double gflops_simd = (2.0 * A.nnz * K_COLS) / (time_simd * 1e9);
    double speedup = (time_std / time_simd);

    printf("[PASSED] Coherencia Cinética Validada (Max diff: %.6f)\n", max_diff);
    printf("----------------------------------------------------------\n");
    printf("CSR Estándar (Auto-vectorización rota) : %.4f seg | %7.3f GFLOPS\n", time_std, gflops_std);
    printf("HBAG-Core SIMD (FMA manual + Padding)  : %.4f seg | %7.3f GFLOPS\n", time_simd, gflops_simd);
    printf("----------------------------------------------------------\n");
    printf("Multiplicador de Rendimiento Real      : %.2fx (%.2f%% más rápido)\n", speedup, (speedup - 1.0) * 100.0);

    free(A.row_ptr); free(A.col_idx); free(A.values);
    free(B); free(C_std); free(C_simd);
    return 0;
}
