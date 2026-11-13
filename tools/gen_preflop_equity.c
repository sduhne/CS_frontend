/*
 * Generates the 169x169 preflop all-in equity matrix used by poker_coach.
 *
 *   gcc -O3 -march=native -fopenmp -o gen_preflop_equity gen_preflop_equity.c
 *   ./gen_preflop_equity 2000000 > ../poker_coach/data/preflop_equity.json
 *
 * For every pair of starting-hand classes (AA, AKs, AKo, ...) it walks every
 * disjoint pair of concrete combos and Monte-Carlo samples boards, so card
 * removal between the two hands is exact and only the board is sampled.
 * The argument is the number of boards sampled per class pair.
 *
 * Output: {"hands": [...169 names], "eq": [[...]], "n": [[...]]}
 *   eq[a][b] = equity of class a against class b (win + tie/2)
 *   n[a][b]  = number of disjoint concrete combo pairs (card-removal weight)
 *
 * Class index = row*13 + col on the usual grid with A first:
 *   row < col -> suited, row > col -> offsuit, row == col -> pair.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
        if (hi < 0 && (m & 0x100F) == 0x100F) hi = 3; /* wheel: A-2-3-4-5 */
        straight_hi[m] = (int8_t)hi;
        top1[m] = topn(m, 1);
        top2[m] = topn(m, 2);
        top3[m] = topn(m, 3);
        top5[m] = topn(m, 5);
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

static const char RANKS[] = "AKQJT98765432"; /* grid order, index 0 = ace */

typedef struct { int n; int c[12][2]; } Class;
static Class classes[169];
static char names[169][4];

static void init_classes(void) {
    for (int i = 0; i < 13; i++) {
        for (int j = 0; j < 13; j++) {
            Class *k = &classes[i * 13 + j];
            char *nm = names[i * 13 + j];
            int ri = 12 - i, rj = 12 - j; /* rank values, 12 = ace */
            k->n = 0;
            if (i == j) {
                snprintf(nm, 4, "%c%c", RANKS[i], RANKS[i]);
                for (int s1 = 0; s1 < 4; s1++)
                    for (int s2 = s1 + 1; s2 < 4; s2++) {
                        k->c[k->n][0] = ri * 4 + s1;
                        k->c[k->n][1] = ri * 4 + s2;
                        k->n++;
                    }
            } else if (i < j) {
                snprintf(nm, 4, "%c%cs", RANKS[i], RANKS[j]);
                for (int s = 0; s < 4; s++) {
                    k->c[k->n][0] = ri * 4 + s;
                    k->c[k->n][1] = rj * 4 + s;
                    k->n++;
                }
            } else {
                snprintf(nm, 4, "%c%co", RANKS[j], RANKS[i]);
                for (int s1 = 0; s1 < 4; s1++)
                    for (int s2 = 0; s2 < 4; s2++) {
                        if (s1 == s2) continue;
                        k->c[k->n][0] = rj * 4 + s1;
                        k->c[k->n][1] = ri * 4 + s2;
                        k->n++;
                    }
            }
        }
    }
}

static inline uint64_t rng_next(uint64_t *s) {
    uint64_t x = *s;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    return *s = x;
}

static double eq[169][169];
static int npairs[169][169];

int main(int argc, char **argv) {
    long samples = argc > 1 ? atol(argv[1]) : 1000000;
    init_tables();
    init_classes();

    #pragma omp parallel for schedule(dynamic, 8)
    for (int a = 0; a < 169; a++) {
        uint64_t seed = 0x9E3779B97F4A7C15ULL ^ ((uint64_t)(a + 1) * 0xD1B54A32D192ED03ULL);
        for (int b = a; b < 169; b++) {
            int valid = 0;
            for (int x = 0; x < classes[a].n; x++)
                for (int y = 0; y < classes[b].n; y++) {
                    const int *h1 = classes[a].c[x], *h2 = classes[b].c[y];
                    if (h1[0] != h2[0] && h1[0] != h2[1] && h1[1] != h2[0] && h1[1] != h2[1]) valid++;
                }
            npairs[a][b] = npairs[b][a] = valid;
            if (valid == 0) { eq[a][b] = eq[b][a] = 0.5; continue; }
            long per = samples / valid + 1;
            double score = 0.0;
            long total = 0;
            for (int x = 0; x < classes[a].n; x++)
                for (int y = 0; y < classes[b].n; y++) {
                    const int *h1 = classes[a].c[x], *h2 = classes[b].c[y];
                    if (h1[0] == h2[0] || h1[0] == h2[1] || h1[1] == h2[0] || h1[1] == h2[1]) continue;
                    int deck[48], nd = 0;
                    for (int c = 0; c < 52; c++)
                        if (c != h1[0] && c != h1[1] && c != h2[0] && c != h2[1]) deck[nd++] = c;
                    int c1[7], c2[7];
                    c1[0] = h1[0]; c1[1] = h1[1];
                    c2[0] = h2[0]; c2[1] = h2[1];
                    for (long it = 0; it < per; it++) {
                        for (int k = 0; k < 5; k++) {
                            int j = k + (int)(rng_next(&seed) % (uint64_t)(48 - k));
                            int t = deck[k]; deck[k] = deck[j]; deck[j] = t;
                            c1[2 + k] = deck[k];
                            c2[2 + k] = deck[k];
                        }
                        int v1 = eval7(c1), v2 = eval7(c2);
                        if (v1 > v2) score += 1.0;
                        else if (v1 == v2) score += 0.5;
                    }
                    total += per;
                }
            eq[a][b] = score / (double)total;
            eq[b][a] = 1.0 - eq[a][b];
        }
    }

    printf("{\"samples_per_matchup\": %ld,\n\"hands\": [", samples);
    for (int a = 0; a < 169; a++) printf("%s\"%s\"", a ? "," : "", names[a]);
    printf("],\n\"eq\": [\n");
    for (int a = 0; a < 169; a++) {
        printf("[");
        for (int b = 0; b < 169; b++) printf("%s%.4f", b ? "," : "", eq[a][b]);
        printf("]%s\n", a < 168 ? "," : "");
    }
    printf("],\n\"n\": [\n");
    for (int a = 0; a < 169; a++) {
        printf("[");
        for (int b = 0; b < 169; b++) printf("%s%d", b ? "," : "", npairs[a][b]);
        printf("]%s\n", a < 168 ? "," : "");
    }
    printf("]}\n");
    return 0;
}
