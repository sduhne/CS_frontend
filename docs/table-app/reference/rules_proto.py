"""Reference model of the hand state machine in proposal-rules.md.

Scratch code, not repository code: it exists to compute the expected numbers
of the proposal's test cases (rules_cases.py, rules_cases2.py) and to fuzz the
rules for chip conservation and progress (rules_fuzz.py).
"""
from __future__ import annotations

LABELS = {2: ["BTN/SB", "BB"], 3: ["BTN", "SB", "BB"], 4: ["CO", "BTN", "SB", "BB"],
          5: ["HJ", "CO", "BTN", "SB", "BB"], 6: ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
          7: ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
          8: ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
          9: ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]}


class Illegal(Exception):
    pass


def order_from_button(dealt: list[int], button: int) -> list[int]:
    """Preflop acting order (first ... SB, BB). `button` may be an empty seat (dead button)."""
    dealt = sorted(dealt)
    after = [s for s in dealt if s > button] + [s for s in dealt if s <= button]
    if len(dealt) == 2:
        btn = button if button in dealt else after[-1]
        return [btn, [s for s in dealt if s != btn][0]]
    return after[2:] + after[:2]


class Hand:
    def __init__(self, stacks: dict, button: int, sb: float, bb: float, ante: float = 0, bb_ante: float = 0,
                 away=(), short_post: str = "ante_first", allin_or_fold: bool = False, fee: float = 0.0):
        self.order = order_from_button([s for s, v in stacks.items() if v and v > 0], button)
        self.n = len(self.order)
        self.button = button
        self.sb, self.bb = sb, bb
        self.start = {s: stacks[s] for s in self.order}
        self.stack = dict(self.start)
        self.ante = {s: 0 for s in self.order}
        self.dead = 0                       # big-blind ante: dead money in the first pot
        self.commit = {s: 0 for s in self.order}
        self.street_commit = {s: 0 for s in self.order}
        self.folded, self.away = set(), set(away)
        self.aof, self.fee = allin_or_fold, fee
        self.fee_taken = 0
        self.events = []
        self.returned = {}
        self.result = None
        self.busted = []
        sbs, bbs = self.order[-2], self.order[-1]
        for s in self.order:
            self._pay_ante(s, ante)
        if short_post == "blind_first":
            self._post(sbs, sb)
            self._post(bbs, bb)
            self._pay_dead(bbs, bb_ante)
        else:
            self._pay_dead(bbs, bb_ante)
            self._post(sbs, sb)
            self._post(bbs, bb)
        self.street = "preflop"
        self.bet_to, self.last_raise = bb, bb
        self.acted_at = {s: None for s in self.order}
        self.last = None
        self._advance()

    # ---- forced bets
    def _pay_ante(self, s, amt):
        a = min(amt, self.stack[s])
        self.stack[s] -= a
        self.ante[s] += a

    def _pay_dead(self, s, amt):
        a = min(amt, self.stack[s])
        self.stack[s] -= a
        self.dead += a

    def _post(self, s, amt):
        a = min(amt, self.stack[s])
        self.stack[s] -= a
        self.commit[s] += a
        self.street_commit[s] += a

    # ---- views
    def labels(self):
        return dict(zip(self.order, LABELS[self.n]))

    def street_order(self):
        if self.street == "preflop":
            return self.order
        return self.order[::-1] if self.n == 2 else self.order[-2:] + self.order[:-2]

    def live(self):
        return [s for s in self.order if s not in self.folded]

    def can_act(self):
        return [s for s in self.live() if self.stack[s] > 0]

    def owe(self, s):
        """Chips this player must add to continue: capped by the stack and by what anybody can match."""
        others = [self.street_commit[o] + self.stack[o] for o in self.live() if o != s]
        cap = max(others) - self.street_commit[s] if others else 0
        return max(0, min(self.stack[s], self.bet_to - self.street_commit[s], cap))

    def _needs(self, s):
        if s in self.folded or self.stack[s] <= 0:
            return False
        if self.acted_at[s] is None:
            return self.owe(s) > 0 or self.may_raise(s)
        return self.street_commit[s] < self.bet_to and self.owe(s) > 0

    def to_act(self):
        if self.street in ("showdown", "done"):
            return None
        so = self.street_order()
        start = 0 if self.last is None else so.index(self.last) + 1
        for k in range(len(so)):
            s = so[(start + k) % len(so)]
            if self._needs(s):
                return s
        return None

    def to_call(self, s=None):
        s = self.to_act() if s is None else s
        return None if s is None else self.owe(s)

    def may_raise(self, s):
        if self.stack[s] <= self.bet_to - self.street_commit[s]:
            return False
        if not any(o != s and o not in self.folded and self.stack[o] > 0 for o in self.order):
            return False                                   # nobody left who could call a raise
        return self.acted_at[s] is None or self.bet_to - self.acted_at[s] >= self.last_raise

    def min_raise_to(self, s):
        return min(self.bet_to + self.last_raise, self.street_commit[s] + self.stack[s])

    def pot_total(self):
        return sum(self.ante.values()) + self.dead + sum(self.commit.values())

    def pots(self):
        tot = {s: self.ante[s] + self.commit[s] for s in self.order}
        levels = sorted({tot[s] for s in self.live()})
        out, prev = [], 0
        for lv in levels:
            amt = sum(min(tot[s], lv) - min(tot[s], prev) for s in self.order)
            elig = [s for s in self.live() if tot[s] >= lv]
            if lv == 0 or amt > 0:
                out.append({"amount": amt, "eligible": elig})
            prev = lv
        # chips of folded players above the top live level stay with the last pot
        extra = sum(max(0, tot[s] - prev) for s in self.order)
        if out:
            out[-1]["amount"] += extra
            out[0]["amount"] += self.dead
        out = [p for p in out if p["amount"] > 0]
        merged = []
        for p in out:                       # merge layers with the same eligible players
            if merged and merged[-1]["eligible"] == p["eligible"]:
                merged[-1]["amount"] += p["amount"]
            else:
                merged.append(p)
        return merged

    # ---- actions
    def act(self, seat, kind, to=None, force=False):
        if self.street in ("showdown", "done"):
            raise Illegal("no betting left")
        if seat != self.to_act():
            raise Illegal(f"not seat {seat}'s turn (to act: {self.to_act()})")
        owe = self.owe(seat)
        if self.aof and kind == "call" and any(e[2] == "allin" for e in self.events):
            kind = "allin"                                 # calling an all-in is an all-in
        if self.aof and kind not in ("fold", "allin"):
            raise Illegal("all-in or fold only")
        if kind == "check":
            if owe > 0:
                raise Illegal("cannot check facing a bet")
        elif kind == "fold":
            self.folded.add(seat)
        elif kind == "call":
            if owe <= 0:
                raise Illegal("nothing to call")
            self._put(seat, owe)
        elif kind in ("bet", "raise", "allin"):
            if kind == "allin":
                to = self.street_commit[seat] + self.stack[seat]
                if owe > 0 and not self.may_raise(seat):   # covers everybody left: it is a call
                    self._put(seat, owe)
                    self._done(seat, "call")
                    return
            add = to - self.street_commit[seat]
            if add > self.stack[seat]:
                raise Illegal("more than the stack")
            allin = add == self.stack[seat]
            if to <= self.bet_to:
                if not allin:
                    raise Illegal("a raise must exceed the bet")
                self._put(seat, add)                       # all-in for less: a call
            else:
                if not self.may_raise(seat):
                    raise Illegal("betting is not reopened: call or fold")
                full = to - self.bet_to >= self.last_raise
                if not full and not allin and not force:
                    raise Illegal(f"minimum raise is to {self.bet_to + self.last_raise}")
                if full or force:
                    self.last_raise = max(to - self.bet_to, self.last_raise if force else 0)
                self._put(seat, add)
                self.bet_to = to
        else:
            raise Illegal(kind)
        self._done(seat, kind)

    def _done(self, seat, kind):
        self.acted_at[seat] = self.bet_to
        self.last = seat
        self.events.append((self.street, seat, kind, self.street_commit[seat]))
        self._advance()

    def _put(self, s, amt):
        self.stack[s] -= amt
        self.commit[s] += amt
        self.street_commit[s] += amt

    def _advance(self):
        while True:
            if len(self.live()) == 1:
                self._refund()
                self._finish()
                return
            s = self.to_act()
            if s is not None and s in self.away:           # sitting out: check when free, else fold
                owe = self.owe(s)
                if owe > 0:
                    self.folded.add(s)
                self.acted_at[s] = self.bet_to
                self.last = s
                self.events.append((self.street, s, "auto-fold" if owe > 0 else "auto-check", self.street_commit[s]))
                continue
            if s is not None:
                return
            self._refund()
            if len(self.can_act()) <= 1 or self.street == "river":
                self.street = "showdown"
                return
            self.street = {"preflop": "flop", "flop": "turn", "turn": "river"}[self.street]
            self.street_commit = {k: 0 for k in self.order}
            self.acted_at = {k: None for k in self.order}
            self.bet_to, self.last_raise, self.last = 0, self.bb, None

    def _refund(self):
        sc = sorted(self.street_commit.items(), key=lambda kv: -kv[1])
        if len(sc) >= 2 and sc[0][1] > sc[1][1]:
            s, diff = sc[0][0], sc[0][1] - sc[1][1]
            self.stack[s] += diff
            self.commit[s] -= diff
            self.street_commit[s] -= diff
            self.returned[s] = self.returned.get(s, 0) + diff

    def award(self, ranking):
        """ranking: list of tiers, best hand first, e.g. [[3], [5, 1]]."""
        if self.street != "showdown":
            raise Illegal("hand is not at showdown")
        self._finish(ranking)

    def _finish(self, ranking=None):
        ranking = ranking or [self.live()]
        pots = self.pots()
        fee = min(self.fee, pots[0]["amount"]) if pots else 0
        if fee:
            pots[0]["amount"] -= fee
        won = {s: 0 for s in self.order}
        clockwise = self.order[-2:] + self.order[:-2] if self.n > 2 else self.order[::-1]
        plan = []
        for p in pots:
            winners = None
            for tier in ranking:
                w = [s for s in tier if s in p["eligible"]]
                if w:
                    winners = w
                    break
            if winners is None:
                if len(p["eligible"]) == 1:
                    winners = p["eligible"]
                else:
                    raise Illegal(f"who wins the pot of {p['amount']} between {p['eligible']}?")
            plan.append((p, winners))
        for p, winners in plan:
            if float(p["amount"]).is_integer():
                share, odd = divmod(p["amount"], len(winners))
            else:
                share, odd = p["amount"] / len(winners), 0
            for s in winners:
                won[s] += share
            for s in [x for x in clockwise if x in winners][:int(odd)]:
                won[s] += 1
        self.fee_taken = fee
        for s in self.order:
            self.stack[s] += won[s]
        self.result = {"pots": pots, "won": won}
        self.street = "done"
        self.busted = [s for s in self.order if self.stack[s] <= 0]

    def summary(self):
        s = self.to_act()
        return {"street": self.street, "pot": self.pot_total(), "to_act": s,
                "to_call": self.to_call(s) if s is not None else None,
                "min_raise_to": self.min_raise_to(s) if s is not None and self.may_raise(s) else None,
                "stacks": dict(self.stack)}
