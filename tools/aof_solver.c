/*
 * Equilibrium solver for All-In or Fold hold'em (every player shoves or folds).
 *
 *   gcc -O3 -march=native -fopenmp -o aof_solver aof_solver.c -lm
 *   ./aof_solver 8,8,8,8 0.1 1 300000000 20000000 20000 > solution.json
 *
 * Arguments: stacks in big blinds, in acting order (first to act ... SB, BB);
 * fee in big blinds; fee mode (1 = taken from every pot, 0 = only when two or
 * more players are all-in); training deals; evaluation deals; samples per
 * hand class in the precision pass (default 20000); optional ante paid by
 * every player; optional ante paid by the big blind alone (it comes out of
 * his stack before his blind, so a big blind with two big blinds and an ante
 * of one is all-in by posting); optional limit on the precision pass: only
 * decision points with at most that many players all-in before them (with
 * nine players there are 511 decision points, and nobody needs the answer
 * to five all-ins to a twentieth of a big blind).
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

#define MAXN 9
#define MAXMASK 512

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
static double live[MAXN], blind[MAXN], ante_v = 0.0, bb_ante_v = 0.0, fee = 0.0;
static int fee_mode = 1, refine_bits = MAXN;

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
            double pot = N * ante_v + bb_ante_v;
            for (int k = 0; k < N; k++) { pot += contrib[k]; mi->base[k] = -contrib[k] - ante_v; }
            mi->base[N - 1] -= bb_ante_v;
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
                pot += N * ante_v + bb_ante_v;
                if (fee_mode == 1 || __builtin_popcount(mask) >= 2) pot -= fee;
                if (pot < 0) pot = 0;
            }
            mi->amt[mi->npots] = pot; mi->elig[mi->npots] = elig; mi->npots++;
            prev = L;
        }
        for (int k = 0; k < N; k++)
            mi->base[k] = -(contrib[k] < top ? contrib[k] : top) - ante_v;
        mi->base[N - 1] -= bb_ante_v;
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

/* A decision that the equilibrium never reaches (with 2bb the button never folds, so "the button folded"
   never comes) still gets trained: its regrets are counted as if it were reached with at least this
   probability, with whatever hands the earlier players hold.  Its answer is then the one for an opponent
   who made the mistake.  Anywhere it is reached in earnest the floor is far below the real weight. */
#define REACH_FLOOR 1e-6

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
        double w = cfr > REACH_FLOOR ? cfr : REACH_FLOOR;
        R[1] += w * (us[i] - out[i]);
        R[0] += w * (uf[i] - out[i]);
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

static double value_sum[MAXN], value_sq[MAXN];

static void run(long iters, int mode) {
    #pragma omp parallel
    {
        int tid = omp_get_thread_num(), nth = omp_get_num_threads();
        uint64_t seed = 0x9E3779B97F4A7C15ULL ^ ((uint64_t)(tid + 1 + 131 * mode) * 0xD1B54A32D192ED03ULL);
        int deck[52];
        for (int c = 0; c < 52; c++) deck[c] = c;
        Deal d;
        d.mode = mode;
        double local_val[MAXN] = {0}, local_sq[MAXN] = {0};
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
            if (mode == 1) for (int k = 0; k < N; k++) { local_val[k] += out[k]; local_sq[k] += out[k] * out[k]; }
        }
        if (mode == 1) {
            #pragma omp critical
            for (int k = 0; k < N; k++) { value_sum[k] += local_val[k]; value_sq[k] += local_sq[k]; }
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
static int trembled[MAXN][MAXMASK];     /* the decision was sampled with trembling hands (the equilibrium never reaches it) */
/* br mode: when a list of hands is given, only those are sampled (the hands near zero, with many more
   samples than the first pass could afford for every hand) */
static int only_set = 0;
static unsigned char only[MAXN][MAXMASK][169];

/* The chance that the earlier players do what mask m says, over random hands (each history once, from a
   fixed stream): a decision the equilibrium all but never reaches is sampled with trembling hands. */
static double reach_of(int i, int m) {
    uint64_t seed = 0x2545F4914F6CDD1DULL ^ ((uint64_t)(i + 1 + 17 * m) * 0x9E3779B97F4A7C15ULL);
    int deck[52];
    for (int c = 0; c < 52; c++) deck[c] = c;
    double sum = 0.0;
    const int trials = 200000;
    for (int t = 0; t < trials; t++) {
        for (int k = 0; k < 2 * i; k++) {
            int j = k + (int)(rng_next(&seed) % (uint64_t)(52 - k));
            int tmp = deck[k]; deck[k] = deck[j]; deck[j] = tmp;
        }
        double a = 1.0;
        for (int k = 0; k < i; k++) {
            double pk = avg[k][m & ((1 << k) - 1)][class_of(deck[2 * k], deck[2 * k + 1])];
            a *= ((m >> k) & 1) ? pk : (1.0 - pk);
        }
        sum += a;
    }
    return sum / trials;
}

#define TREMBLE 0.02          /* trembling hands: every earlier action at least this likely */
#define RARE_REACH 1e-4       /* ... where the decision is reached less often than this */

static void refine(long samples) {
    for (int i = 0; i < N; i++) {
        for (int m = 0; m < (1 << i); m++) {
            if (i == N - 1 && m == 0) continue;
            if (__builtin_popcount(m) > refine_bits) continue;
            double tremble = (i > 0 && reach_of(i, m) < RARE_REACH) ? TREMBLE : 0.0;
            trembled[i][m] = tremble > 0.0;
            #pragma omp parallel for schedule(dynamic, 4)
            for (int c = 0; c < 169; c++) {
                if (only_set && !only[i][m][c]) continue;
                /* one stream of random numbers for each decision point (masks under 64 keep the seeds they always had) */
                uint64_t seed = 0xA0761D6478BD642FULL
                    ^ ((uint64_t)(c + 1 + 169 * (m + 64 * i) + 1000003 * (m >> 6)) * 0xE7037ED1A0B428DBULL);
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
                    /* a situation the earlier players never create is given up on,
                       and reported with zero samples */
                    long acc = 0, tries = 0, max_tries = per * 5000L;
                    int pre = 2 * i, rest = 2 * (N - 1 - i) + 5;
                    while (acc < per && tries < max_tries) {
                        if (acc == 0 && tries >= 1000000L) break;
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
                            pk = tremble + (1.0 - 2.0 * tremble) * pk;
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

/*
 * Fixed strategies, for play against opponents who are not at equilibrium.
 * A strategy file is text: the number of decision points, then for each one
 * "player mask" followed by 169 shove probabilities.
 */
static double strat_hero[MAXN][MAXMASK][169], strat_opp[MAXN][MAXMASK][169];

static int load_strategy(const char *path, double dst[MAXN][MAXMASK][169]) {
    FILE *f = fopen(path, "r");
    int nodes;
    if (!f) return -1;
    if (fscanf(f, "%d", &nodes) != 1) { fclose(f); return -1; }
    for (int q = 0; q < nodes; q++) {
        int i, m;
        if (fscanf(f, "%d %d", &i, &m) != 2 || i < 0 || i >= MAXN || m < 0 || m >= MAXMASK) { fclose(f); return -1; }
        for (int c = 0; c < 169; c++)
            if (fscanf(f, "%lf", &dst[i][m][c]) != 1) { fclose(f); return -1; }
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv) {
    /* Extra modes:
     *   aof_solver br   stacks fee fee_mode samples opp_file [ante] [bb_ante] [all_ins] [hands_file]
     *       best response: EV of shoving minus folding at every decision
     *       point (with at most all_ins players all-in before) when every
     *       other player follows opp_file.  With more samples than the solve
     *       used, this is the precision pass again with less noise; with
     *       hands_file ("player mask hand" lines after their count), for
     *       those hands only, the others are printed as 0;
     *   aof_solver eval stacks fee fee_mode deals hero_file opp_file
     *       average result and standard deviation per hand, seat by seat,
     *       for one player on hero_file against three on opp_file.
     */
    const char *mode = "solve";
    if (argc > 1 && (strcmp(argv[1], "br") == 0 || strcmp(argv[1], "eval") == 0)) {
        mode = argv[1];
        argv++;
        argc--;
    }
    if (argc < 6 || (strcmp(mode, "eval") == 0 && argc < 7)) {
        fprintf(stderr, "usage: %s stacks(csv) fee fee_mode train_iters eval_iters [refine_samples] [ante] [bb_ante] [refine_all_ins]\n"
                        "       %s br stacks fee fee_mode samples opp_file [ante] [bb_ante] [all_ins] [hands_file]\n"
                        "       %s eval stacks fee fee_mode deals hero_file opp_file\n", argv[0], argv[0], argv[0]);
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
    if (strcmp(mode, "solve") == 0 && argc > 7) ante_v = atof(argv[7]);
    if (strcmp(mode, "solve") == 0 && argc > 8) bb_ante_v = atof(argv[8]);
    if (strcmp(mode, "solve") == 0 && argc > 9) refine_bits = atoi(argv[9]);
    /* br: the antes and the limit of the precision pass follow the file */
    if (strcmp(mode, "br") == 0 && argc > 6) ante_v = atof(argv[6]);
    if (strcmp(mode, "br") == 0 && argc > 7) bb_ante_v = atof(argv[7]);
    if (strcmp(mode, "br") == 0 && argc > 8) refine_bits = atoi(argv[8]);
    if (strcmp(mode, "br") == 0 && argc > 9) {
        /* a file of "player mask hand" lines, after their count: the hands to sample */
        FILE *f = fopen(argv[9], "r");
        long count;
        if (!f || fscanf(f, "%ld", &count) != 1) { fprintf(stderr, "cannot read %s\n", argv[9]); return 2; }
        for (long q = 0; q < count; q++) {
            int i, m, c;
            if (fscanf(f, "%d %d %d", &i, &m, &c) != 3 || i < 0 || i >= MAXN || m < 0 || m >= MAXMASK || c < 0 || c >= 169) {
                fprintf(stderr, "%s: line %ld is not a decision point and a hand\n", argv[9], q + 2);
                return 2;
            }
            only[i][m][c] = 1;
        }
        fclose(f);
        only_set = 1;
    }
    double stacks[MAXN];
    for (int k = 0; k < N; k++) {
        stacks[k] = live[k];
        live[k] -= ante_v;
        blind[k] = 0.0;
    }
    if (bb_ante_v > live[N - 1]) bb_ante_v = live[N - 1];
    live[N - 1] -= bb_ante_v;
    blind[N - 2] = live[N - 2] < 0.5 ? live[N - 2] : 0.5;
    blind[N - 1] = live[N - 1] < 1.0 ? live[N - 1] : 1.0;

    init_tables();
    build_masks();

    if (strcmp(mode, "br") == 0) {
        if (load_strategy(argv[5], avg)) { fprintf(stderr, "cannot read %s\n", argv[5]); return 2; }
        refine(atol(argv[4]));
        printf("{\"n\": %d, \"nodes\": [\n", N);
        int first_node = 1;
        for (int i = 0; i < N; i++)
            for (int m = 0; m < (1 << i); m++) {
                if (i == N - 1 && m == 0) continue;
                long least = -1;
                printf("%s{\"player\": %d, \"mask\": %d, \"ev\": [", first_node ? "" : ",\n", i, m);
                first_node = 0;
                for (int c = 0; c < 169; c++) {
                    if (least < 0 || n_ref[i][m][c] < least) least = n_ref[i][m][c];
                    printf("%s%d", c ? "," : "", (int)lround(100.0 * ev_ref[i][m][c]));
                }
                printf("], \"samples\": %ld, \"trembled\": %d}", least, trembled[i][m]);
            }
        printf("\n]}\n");
        return 0;
    }
    if (strcmp(mode, "eval") == 0) {
        long deals = atol(argv[4]);
        if (load_strategy(argv[5], strat_hero) || load_strategy(argv[6], strat_opp)) {
            fprintf(stderr, "cannot read the strategy files\n");
            return 2;
        }
        double mean[MAXN], sd[MAXN];
        long done = (deals / omp_get_max_threads()) * omp_get_max_threads();
        for (int h = 0; h < N; h++) {
            for (int i = 0; i < N; i++)
                memcpy(avg[i], i == h ? strat_hero[i] : strat_opp[i], sizeof(avg[i]));
            memset(value_sum, 0, sizeof(value_sum));
            memset(value_sq, 0, sizeof(value_sq));
            run(deals, 1);
            mean[h] = value_sum[h] / done;
            sd[h] = sqrt(value_sq[h] / done - mean[h] * mean[h]);
        }
        printf("{\"n\": %d, \"value\": [", N);
        for (int h = 0; h < N; h++) printf("%s%.5f", h ? "," : "", mean[h]);
        printf("], \"sd\": [");
        for (int h = 0; h < N; h++) printf("%s%.4f", h ? "," : "", sd[h]);
        printf("]}\n");
        return 0;
    }
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
    printf("], \"fee\": %g, \"fee_mode\": %d, \"ante\": %g, \"bb_ante\": %g, \"train\": %ld, \"eval\": %ld,\n", fee, fee_mode, ante_v, bb_ante_v, train, evals);
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
                if (refine_samples > 0 && __builtin_popcount(m) <= refine_bits) {
                    e = ev_ref[i][m][c];
                    if (least < 0 || n_ref[i][m][c] < least) least = n_ref[i][m][c];
                }
                printf("%s%d", c ? "," : "", (int)lround(100.0 * e));
            }
            printf("], \"samples\": %ld, \"trembled\": %d}", least, trembled[i][m]);
        }
    }
    printf("\n]}\n");
    return 0;
}
