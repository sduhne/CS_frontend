/*
 * Equilibrium solver for All-In or Fold hold'em (every player shoves or folds).
 *
 *   gcc -O3 -march=native -fopenmp -o aof_solver aof_solver.c -lm
 *   ./aof_solver 8,8,8,8 0.1 1 300000000 20000000 20000 > solution.json
 *
 * Arguments: stacks in big blinds, in acting order (first to act ... SB, BB);
 * fee in big blinds; fee mode (1 = taken from every pot, 0 = only when two or
 * more players are all-in); training deals; evaluation deals; samples per
 * hand class in the precision pass (default 20000); optional ante.
 *
 * Method: chance-sampled counterfactual regret minimisation.  Every iteration
 * deals real cards to all players plus a board, so card removal and multi-way
 * showdowns (side pots included) are exact, then walks the whole shove/fold
 * tree.  Private information is abstracted to the 169 starting-hand classes.
 * After training, a precision pass samples every decision point directly and
 * measures, for each hand, how much shoving earns over folding.
 *
 * A decision point is (player, mask) where mask has bit k set if player k
 * shoved earlier in the hand.  Output: for each decision point, the shove
 * frequency (percent) and the EV of shoving minus folding (1/100 bb) per
 * hand class, on the usual 13x13 grid with the ace first.
 */
#include <math.h>
#include <omp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXN 6
#define MAXMASK 64

/* ---------------------------------------------------------------- evaluator */
static int8_t straight_hi[8192];
static uint16_t top1[8192], top2[8192], top3[8192], top5[8192];

static uint16_t topn(int mask, int n) {
    uint16_t out = 0;
    for (int r = 12; r >= 0 && n > 0; r--)
        if (mask & (1 << r)) { out |= (uint16_t)(1 << r); n--; }
    return out;
}

static void init_tables(void) {
    for (int m = 0; m < 8192; m++) {
        int hi = -1;
        for (int top = 12; top >= 4; top--) {
            int need = 0x1F << (top - 4);
            if ((m & need) == need) { hi = top; break; }
        }
        if (hi < 0 && (m & 0x100F) == 0x100F) hi = 3;
        straight_hi[m] = (int8_t)hi;
        top1[m] = topn(m, 1); top2[m] = topn(m, 2);
        top3[m] = topn(m, 3); top5[m] = topn(m, 5);
    }
}

/* card = rank*4 + suit, rank 0 = deuce ... 12 = ace */
static inline int eval7(const int *c) {
    int sm[4] = {0, 0, 0, 0};
    int cnt[13] = {0};
    for (int i = 0; i < 7; i++) {
        int r = c[i] >> 2, s = c[i] & 3;
        sm[s] |= 1 << r;
        cnt[r]++;
    }
    int rm = sm[0] | sm[1] | sm[2] | sm[3];
    for (int s = 0; s < 4; s++) {
        if (__builtin_popcount(sm[s]) >= 5) {
            int st = straight_hi[sm[s]];
            if (st >= 0) return (8 << 24) | st;
            return (5 << 24) | top5[sm[s]];
        }
    }
    int quad = -1, trips[2], ntr = 0, pairs[3], np = 0;
    for (int r = 12; r >= 0; r--) {
        if (cnt[r] == 4) quad = r;
        else if (cnt[r] == 3) trips[ntr++] = r;
        else if (cnt[r] == 2) pairs[np++] = r;
    }
    if (quad >= 0) return (7 << 24) | (quad << 13) | top1[rm & ~(1 << quad)];
    if (ntr >= 1 && (ntr >= 2 || np >= 1)) {
        int p = -1;
        if (ntr >= 2) p = trips[1];
        if (np >= 1 && pairs[0] > p) p = pairs[0];
        return (6 << 24) | (trips[0] << 4) | p;
    }
    int st = straight_hi[rm];
    if (st >= 0) return (4 << 24) | st;
    if (ntr == 1) return (3 << 24) | (trips[0] << 13) | top2[rm & ~(1 << trips[0])];
    if (np >= 2)
        return (2 << 24) | (pairs[0] << 17) | (pairs[1] << 13) |
               top1[rm & ~(1 << pairs[0]) & ~(1 << pairs[1])];
    if (np == 1) return (1 << 24) | (pairs[0] << 13) | top3[rm & ~(1 << pairs[0])];
    return top5[rm];
}

static inline int class_of(int c1, int c2) {
    int r1 = c1 >> 2, r2 = c2 >> 2;
    if (r1 == r2) return (12 - r1) * 14;
    int hi = r1 > r2 ? r1 : r2, lo = r1 > r2 ? r2 : r1;
    int row = 12 - hi, col = 12 - lo;
    return ((c1 & 3) == (c2 & 3)) ? row * 13 + col : col * 13 + row;
}

/* ------------------------------------------------------------------- game */
static int N;
static double live[MAXN], blind[MAXN], ante_v = 0.0, fee = 0.0;
static int fee_mode = 1;

typedef struct {
    int npots;
    double amt[MAXN];
    int elig[MAXN];
    double base[MAXN];   /* payoff before any pot is awarded */
} MaskInfo;
static MaskInfo minfo[MAXMASK];

static void build_masks(void) {
    for (int mask = 0; mask < (1 << N); mask++) {
        MaskInfo *mi = &minfo[mask];
        double contrib[MAXN];
        for (int k = 0; k < N; k++) contrib[k] = ((mask >> k) & 1) ? live[k] : blind[k];
        mi->npots = 0;
        if (mask == 0) {                       /* everyone folds: the big blind takes it */
            double pot = N * ante_v;
            for (int k = 0; k < N; k++) { pot += contrib[k]; mi->base[k] = -contrib[k] - ante_v; }
            if (fee_mode == 1) pot -= fee;
            mi->npots = 1; mi->amt[0] = pot > 0 ? pot : 0; mi->elig[0] = 1 << (N - 1);
            continue;
        }
        double levels[MAXN]; int nl = 0;
        for (int k = 0; k < N; k++) if ((mask >> k) & 1) {
            int dup = 0;
            for (int j = 0; j < nl; j++) if (fabs(levels[j] - live[k]) < 1e-9) dup = 1;
            if (!dup) levels[nl++] = live[k];
        }
        for (int a = 0; a < nl; a++) for (int b = a + 1; b < nl; b++)
            if (levels[b] < levels[a]) { double t = levels[a]; levels[a] = levels[b]; levels[b] = t; }
        double prev = 0.0, top = levels[nl - 1];
        for (int j = 0; j < nl; j++) {
            double L = levels[j], pot = 0.0;
            int elig = 0;
            for (int k = 0; k < N; k++) {
                double a = contrib[k] < L ? contrib[k] : L;
                double b = contrib[k] < prev ? contrib[k] : prev;
                pot += a - b;
                if (((mask >> k) & 1) && live[k] >= L - 1e-9) elig |= 1 << k;
            }
            if (j == 0) {
                pot += N * ante_v;
                if (fee_mode == 1 || __builtin_popcount(mask) >= 2) pot -= fee;
                if (pot < 0) pot = 0;
            }
            mi->amt[mi->npots] = pot; mi->elig[mi->npots] = elig; mi->npots++;
            prev = L;
        }
        for (int k = 0; k < N; k++)
            mi->base[k] = -(contrib[k] < top ? contrib[k] : top) - ante_v;
    }
}

static double regret[MAXN][MAXMASK][169][2];
static double ssum[MAXN][MAXMASK][169], wsum[MAXN][MAXMASK][169];
static double avg[MAXN][MAXMASK][169];
static double evnum[MAXN][MAXMASK][169], evden[MAXN][MAXMASK][169];

typedef struct {
    int cls[MAXN];
    double pay[MAXMASK][MAXN];
    double weight;
    int mode;            /* 0 = train, 1 = evaluate the average strategy, 2 = value only */
} Deal;

static void walk(const Deal *d, int i, int mask, double cfr, double *out) {
    if (i == N || (i == N - 1 && mask == 0)) {
        memcpy(out, d->pay[mask], sizeof(double) * N);
        return;
    }
    int c = d->cls[i];
    double p;
    if (d->mode == 0) {
        double *R = regret[i][mask][c];
        double a = R[0] > 0 ? R[0] : 0, b = R[1] > 0 ? R[1] : 0;
        p = (a + b > 0) ? b / (a + b) : 0.5;
    } else {
        p = avg[i][mask][c];
    }
    double us[MAXN], uf[MAXN];
    walk(d, i + 1, mask | (1 << i), cfr * p, us);
    walk(d, i + 1, mask, cfr * (1.0 - p), uf);
    for (int k = 0; k < N; k++) out[k] = p * us[k] + (1.0 - p) * uf[k];
    if (d->mode == 0) {
        double *R = regret[i][mask][c];
        R[1] += cfr * (us[i] - out[i]);
        R[0] += cfr * (uf[i] - out[i]);
        ssum[i][mask][c] += d->weight * p;
        wsum[i][mask][c] += d->weight;
    } else if (cfr > 0) {
        evnum[i][mask][c] += cfr * (us[i] - uf[i]);
        evden[i][mask][c] += cfr;
    }
}

static inline uint64_t rng_next(uint64_t *s) {
    uint64_t x = *s;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    return *s = x;
}

static double value_sum[MAXN];

static void run(long iters, int mode) {
    #pragma omp parallel
    {
        int tid = omp_get_thread_num(), nth = omp_get_num_threads();
        uint64_t seed = 0x9E3779B97F4A7C15ULL ^ ((uint64_t)(tid + 1 + 131 * mode) * 0xD1B54A32D192ED03ULL);
        int deck[52];
        for (int c = 0; c < 52; c++) deck[c] = c;
        Deal d;
        d.mode = mode;
        double local_val[MAXN] = {0};
        long mine = iters / nth;
        int need = 2 * N + 5;
        for (long it = 0; it < mine; it++) {
            for (int k = 0; k < need; k++) {
                int j = k + (int)(rng_next(&seed) % (uint64_t)(52 - k));
                int t = deck[k]; deck[k] = deck[j]; deck[j] = t;
            }
            int rank[MAXN], cards[7];
            for (int k = 0; k < 5; k++) cards[2 + k] = deck[2 * N + k];
            for (int p = 0; p < N; p++) {
                cards[0] = deck[2 * p]; cards[1] = deck[2 * p + 1];
                rank[p] = eval7(cards);
                d.cls[p] = class_of(cards[0], cards[1]);
            }
            for (int mask = 0; mask < (1 << N); mask++) {
                const MaskInfo *mi = &minfo[mask];
                double *pay = d.pay[mask];
                for (int k = 0; k < N; k++) pay[k] = mi->base[k];
                for (int j = 0; j < mi->npots; j++) {
                    int best = -1, cnt = 0;
                    for (int k = 0; k < N; k++) if ((mi->elig[j] >> k) & 1) {
                        if (rank[k] > best) { best = rank[k]; cnt = 1; }
                        else if (rank[k] == best) cnt++;
                    }
                    double share = mi->amt[j] / cnt;
                    for (int k = 0; k < N; k++)
                        if (((mi->elig[j] >> k) & 1) && rank[k] == best) pay[k] += share;
                }
            }
            d.weight = (double)(it + 1);
            double out[MAXN];
            walk(&d, 0, 0, 1.0, out);
            if (mode == 1) for (int k = 0; k < N; k++) local_val[k] += out[k];
        }
        if (mode == 1) {
            #pragma omp critical
            for (int k = 0; k < N; k++) value_sum[k] += local_val[k];
        }
    }
}

/*
 * Precision pass.  Regret updates at rarely reached decision points (calling
 * three all-ins, say) rest on few deals.  Here each decision point and hand
 * class is sampled directly: hero holds the class, the players who acted
 * before are dealt hands and the deal is kept with the probability that they
 * would have acted that way, and the players behind respond with the average
 * strategy.  The result is the EV of shoving minus folding to about 0.05bb.
 */
static double ev_ref[MAXN][MAXMASK][169];
static long n_ref[MAXN][MAXMASK][169];

static void refine(long samples) {
    for (int i = 0; i < N; i++) {
        for (int m = 0; m < (1 << i); m++) {
            if (i == N - 1 && m == 0) continue;
            #pragma omp parallel for schedule(dynamic, 4)
            for (int c = 0; c < 169; c++) {
                uint64_t seed = 0xA0761D6478BD642FULL ^ ((uint64_t)(c + 1 + 169 * (m + 64 * i)) * 0xE7037ED1A0B428DBULL);
                int row = c / 13, col = c % 13;
                int combos[12][2], nc = 0;
                int hi = 12 - (row < col ? row : col), lo = 12 - (row < col ? col : row);
                if (row == col) {
                    for (int a = 0; a < 4; a++) for (int b = a + 1; b < 4; b++) { combos[nc][0] = hi * 4 + a; combos[nc][1] = hi * 4 + b; nc++; }
                } else if (row < col) {
                    for (int a = 0; a < 4; a++) { combos[nc][0] = hi * 4 + a; combos[nc][1] = lo * 4 + a; nc++; }
                } else {
                    for (int a = 0; a < 4; a++) for (int b = 0; b < 4; b++) if (a != b) { combos[nc][0] = hi * 4 + a; combos[nc][1] = lo * 4 + b; nc++; }
                }
                long per = samples / nc + 1, acc_total = 0;
                double num = 0.0;
                Deal d;
                d.mode = 2;
                d.weight = 0.0;
                for (int x = 0; x < nc; x++) {
                    int deck[50], nd = 0;
                    for (int card = 0; card < 52; card++)
                        if (card != combos[x][0] && card != combos[x][1]) deck[nd++] = card;
                    long acc = 0, tries = 0, max_tries = per * 200000L;
                    int pre = 2 * i, rest = 2 * (N - 1 - i) + 5;
                    while (acc < per && tries < max_tries) {
                        tries++;
                        for (int k = 0; k < pre; k++) {
                            int j = k + (int)(rng_next(&seed) % (uint64_t)(50 - k));
                            int t = deck[k]; deck[k] = deck[j]; deck[j] = t;
                        }
                        double a = 1.0;
                        int hole[MAXN][2];
                        for (int k = 0; k < i; k++) {
                            hole[k][0] = deck[2 * k]; hole[k][1] = deck[2 * k + 1];
                            double pk = avg[k][m & ((1 << k) - 1)][class_of(hole[k][0], hole[k][1])];
                            a *= ((m >> k) & 1) ? pk : (1.0 - pk);
                        }
                        if (a <= 0.0) continue;
                        if (a < 1.0 && (double)(rng_next(&seed) >> 11) * (1.0 / 9007199254740992.0) >= a) continue;
                        for (int k = pre; k < pre + rest; k++) {
                            int j = k + (int)(rng_next(&seed) % (uint64_t)(50 - k));
                            int t = deck[k]; deck[k] = deck[j]; deck[j] = t;
                        }
                        hole[i][0] = combos[x][0]; hole[i][1] = combos[x][1];
                        for (int k = i + 1; k < N; k++) { hole[k][0] = deck[pre + 2 * (k - i - 1)]; hole[k][1] = deck[pre + 2 * (k - i - 1) + 1]; }
                        int cards[7], rank[MAXN];
                        for (int k = 0; k < 5; k++) cards[2 + k] = deck[pre + rest - 5 + k];
                        for (int p2 = 0; p2 < N; p2++) {
                            cards[0] = hole[p2][0]; cards[1] = hole[p2][1];
                            rank[p2] = eval7(cards);
                            d.cls[p2] = class_of(cards[0], cards[1]);
                        }
                        for (int mask = 0; mask < (1 << N); mask++) {
                            if ((mask & ((1 << i) - 1)) != m) continue;   /* only histories that match */
                            const MaskInfo *mi = &minfo[mask];
                            double *pay = d.pay[mask];
                            for (int k = 0; k < N; k++) pay[k] = mi->base[k];
                            for (int j = 0; j < mi->npots; j++) {
                                int best = -1, cnt = 0;
                                for (int k = 0; k < N; k++) if ((mi->elig[j] >> k) & 1) {
                                    if (rank[k] > best) { best = rank[k]; cnt = 1; }
                                    else if (rank[k] == best) cnt++;
                                }
                                double share = mi->amt[j] / cnt;
                                for (int k = 0; k < N; k++)
                                    if (((mi->elig[j] >> k) & 1) && rank[k] == best) pay[k] += share;
                            }
                        }
                        double us[MAXN], uf[MAXN];
                        walk(&d, i + 1, m | (1 << i), 1.0, us);
                        walk(&d, i + 1, m, 1.0, uf);
                        num += us[i] - uf[i];
                        acc++;
                    }
                    acc_total += acc;
                }
                ev_ref[i][m][c] = acc_total ? num / acc_total : 0.0;
                n_ref[i][m][c] = acc_total;
            }
        }
    }
}

int main(int argc, char **argv) {
    if (argc < 6) {
        fprintf(stderr, "usage: %s stacks(csv) fee fee_mode train_iters eval_iters [refine_samples] [ante]\n", argv[0]);
        return 2;
    }
    char buf[256];
    strncpy(buf, argv[1], 255); buf[255] = 0;
    N = 0;
    for (char *tok = strtok(buf, ","); tok && N < MAXN; tok = strtok(NULL, ",")) live[N++] = atof(tok);
    if (N < 2) { fprintf(stderr, "need at least two stacks\n"); return 2; }
    fee = atof(argv[2]);
    fee_mode = atoi(argv[3]);
    long train = atol(argv[4]), evals = atol(argv[5]);
    long refine_samples = argc > 6 ? atol(argv[6]) : 20000;
    if (argc > 7) ante_v = atof(argv[7]);
    double stacks[MAXN];
    for (int k = 0; k < N; k++) {
        stacks[k] = live[k];
        live[k] -= ante_v;
        blind[k] = 0.0;
    }
    blind[N - 2] = live[N - 2] < 0.5 ? live[N - 2] : 0.5;
    blind[N - 1] = live[N - 1] < 1.0 ? live[N - 1] : 1.0;

    init_tables();
    build_masks();
    run(train, 0);
    for (int i = 0; i < N; i++)
        for (int m = 0; m < (1 << i); m++)
            for (int c = 0; c < 169; c++)
                avg[i][m][c] = wsum[i][m][c] > 0 ? ssum[i][m][c] / wsum[i][m][c] : 0.5;
    run(evals, 1);
    if (refine_samples > 0) refine(refine_samples);

    int nth = omp_get_max_threads();
    long evals_done = (evals / nth) * nth;
    printf("{\"n\": %d, \"stacks\": [", N);
    for (int k = 0; k < N; k++) printf("%s%g", k ? "," : "", stacks[k]);
    printf("], \"fee\": %g, \"fee_mode\": %d, \"ante\": %g, \"train\": %ld, \"eval\": %ld,\n", fee, fee_mode, ante_v, train, evals);
    printf("\"value\": [");
    for (int k = 0; k < N; k++) printf("%s%.4f", k ? "," : "", evals_done ? value_sum[k] / evals_done : 0.0);
    printf("],\n\"nodes\": [\n");
    int first = 1;
    for (int i = 0; i < N; i++) {
        for (int m = 0; m < (1 << i); m++) {
            if (i == N - 1 && m == 0) continue;
            printf("%s{\"player\": %d, \"mask\": %d, \"freq\": [", first ? "" : ",\n", i, m);
            first = 0;
            for (int c = 0; c < 169; c++) printf("%s%d", c ? "," : "", (int)lround(100.0 * avg[i][m][c]));
            printf("], \"ev\": [");
            long least = -1;
            for (int c = 0; c < 169; c++) {
                double e = evden[i][m][c] > 0 ? evnum[i][m][c] / evden[i][m][c] : 0.0;
                if (refine_samples > 0) {
                    e = ev_ref[i][m][c];
                    if (least < 0 || n_ref[i][m][c] < least) least = n_ref[i][m][c];
                }
                printf("%s%d", c ? "," : "", (int)lround(100.0 * e));
            }
            printf("], \"samples\": %ld}", least);
        }
    }
    printf("\n]}\n");
    return 0;
}
