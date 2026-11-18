"""Reading of the table -> what the coach would do.

``suggest`` takes a ``TableRead`` and gives a ``Suggestion``: the action in
a few words, the reason in one line, and the numbers behind it.  Before the
flop it uses the same engine as ``advise`` (or the all-in or fold tables in
``binary`` and ``spin`` mode); after the flop the postflop advisor.

Nothing is suggested unless the table shows one of the play-money markers
(``play_money_check``): the reader is for play money and research.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from .. import binary as BN
from .. import spin as SP
from .. import state as S
from ..cards import HANDS, class_of, parse_cards
from ..cards import range_pct
from ..postflop import PostflopSpot, Villain, advise_postflop
from ..preflop import Act, advise
from ..ranges import (norm_type, play_order, position_name, threebet_range, top_percent, villain_limp_range,
                      villain_open_range, vs_open_chart)
from .schema import SeatRead, TableRead

DEFAULT_MARKERS = ("play money", "play chips", "play-money", "practice", "free chips", "fun chips",
                   "play for fun")
MODES = ("tag", "binary", "spin")


@dataclass
class LiveSettings:
    """What the reader cannot see: the mode and the tournament numbers."""
    mode: str = "tag"                       # tag: tight-aggressive engine; binary: all-in or fold; spin
    markers: tuple = DEFAULT_MARKERS        # text that must be visible on the table (play money)
    goal: str = "itm"
    entrants: int | None = None
    paid: int | None = None
    buyin: float | None = None
    stage: str = "before"                   # binary mode: before or money
    opponents: str = "unknown"              # how the table plays: unknown, or a type such as loose or tight


@dataclass
class Suggestion:
    kind: str                               # act | wait | blocked | error
    action: str = ""
    reason: str = ""
    details: list[str] = field(default_factory=list)
    info: str = ""
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f">>> {self.action}" if self.action else f"[{self.kind}]"]
        for x in [self.info, self.reason] + self.details + [f"!! {w}" for w in self.warnings]:
            if x:
                lines.append(f"  {x}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# The play-money check
# --------------------------------------------------------------------------

def play_money_check(read: TableRead, markers=DEFAULT_MARKERS) -> tuple[bool, str]:
    """(allowed, why).  Allowed only when a marker is visible on the table."""
    seen = f"{read.money_text} {read.table_text}".lower()
    for m in markers:
        if m and m.strip().lower() in seen:
            return True, f"play money ({m.strip()})"
    shown = read.money_text.strip() or read.table_text.strip() or "nothing"
    return False, (f"not reading: this table does not show play money (it shows {shown!r}). "
                   "If your play-money client marks its tables differently, add that text with --marker")


# --------------------------------------------------------------------------
# Reading -> table state
# --------------------------------------------------------------------------

@dataclass
class Table:
    """A reading turned into seat numbers (hero is seat 1, clockwise)."""
    state: dict
    seats: list[SeatRead]                   # index k is seat k + 1
    behind: list[float]
    bets: list[float]
    sb: float
    bb: float
    ante: float
    bb_ante: float
    button: int
    unit: str                               # "chips" or "bb"
    warnings: list[str]

    @property
    def n(self) -> int:
        return len(self.seats)


def _order_from_hero(seats: list[SeatRead]) -> list[SeatRead]:
    heroes = [k for k, s in enumerate(seats) if s.is_hero]
    k = heroes[0] if heroes else 0
    return seats[k:] + seats[:k]


def _infer_button(seats: list[SeatRead], sb: float, bb: float, preflop: bool) -> int | None:
    """Seat number (1-based) of the button, from the disc or from the blinds in front."""
    marked = [k for k, s in enumerate(seats) if s.has_button]
    if marked:
        return marked[0] + 1
    if not preflop:
        return None
    n = len(seats)
    for k in range(n):
        nxt = (k + 1) % n
        if abs(seats[k].bet - sb) < 1e-6 and abs(seats[nxt].bet - bb) < 1e-6:
            return (k if n == 2 else (k - 1) % n) + 1
    return None


def to_table(read: TableRead, settings: LiveSettings) -> Table:
    """The reading as a table the engine understands (start-of-hand stacks before the flop)."""
    if not read.seats:
        raise ValueError("no seats were read")
    warnings: list[str] = []
    seats = _order_from_hero(list(read.seats))
    if not any(s.is_hero for s in seats):
        warnings.append("the reading did not mark the hero: assumed the first seat listed")
    in_bb = read.amounts_in_bb
    bb = read.big_blind
    if in_bb:
        bb, unit = 1.0, "bb"
    else:
        unit = "chips"
    if not bb:
        raise ValueError("the blinds could not be read (the local reader learns them from the blinds in front "
                         "of the players before the flop: it will know them from the next hand)")
    sb = read.small_blind if (read.small_blind and not in_bb) else bb / 2.0
    ante = float(read.ante or 0.0)
    if in_bb and read.ante and read.big_blind and read.ante > 1.0:
        ante = read.ante / read.big_blind      # the title shows chips, the seats show big blinds
    kind = read.ante_kind
    if kind == "unknown" and ante:
        kind = "big_blind" if ante >= 0.5 * bb else "per_player"
    per_player = ante if kind == "per_player" else 0.0
    bb_ante = ante if kind == "big_blind" else 0.0

    known = [s.stack for s in seats if s.stack is not None]
    fill = sorted(known)[len(known) // 2] if known else 100 * bb
    behind, bets = [], []
    for s in seats:
        if s.stack is None:
            warnings.append(f"could not read {s.name or 'a'} stack: assumed {fill:,.0f}")
        behind.append(0.0 if s.all_in else float(s.stack if s.stack is not None else fill))
        bets.append(float(s.bet or 0.0))

    preflop = len(read.board) == 0
    button = _infer_button(seats, sb, bb, preflop)
    if button is None:
        raise ValueError("the dealer button could not be found")
    if not any(s.has_button for s in seats):
        warnings.append("dealer button not seen: placed from the blinds")

    n = len(seats)
    order_after_button = [((button - 1 + j) % n) + 1 for j in range(1, n + 1)]
    bb_seat = order_after_button[0] if n == 2 else order_after_button[1]
    snap_seats = {}
    for k, s in enumerate(seats):
        start = behind[k] + bets[k] + per_player + (bb_ante if (k + 1) == bb_seat else 0.0)
        entry = {"name": s.name or f"Seat{k + 1}", "stack": start}
        if k and norm_type(settings.opponents) != "unknown":
            entry["type"] = norm_type(settings.opponents)
        if s.sitting_out:
            entry["status"] = "away"
        snap_seats[str(k + 1)] = entry
    st = S.blank_state()
    snap = {"blinds": [sb, bb, per_player], "bb_ante": bb_ante, "button": button, "hero": 1,
            "seats": snap_seats, "complete": True, "max_seats": max(n, 2), "goal": settings.goal}
    t = {"remaining": read.players_left, "paid": read.places_paid or settings.paid,
         "entrants": read.entrants or settings.entrants, "buyin": settings.buyin}
    if read.average_stack:
        t["avg_stack"] = read.average_stack        # the same units as the stacks
    snap.update({k: v for k, v in t.items() if v is not None})
    S.apply_snapshot(st, snap)
    return Table(st, seats, behind, bets, sb, bb, per_player, bb_ante, button, unit, warnings)


# --------------------------------------------------------------------------
# Before the flop: what happened before hero acts
# --------------------------------------------------------------------------

def preflop_acts(table: Table, order: list[int]) -> list[Act]:
    """The actions in front of hero, rebuilt from the chips each player has in front.

    ``order`` is seat numbers in preflop acting order.  Posted blinds are not
    actions; a bet equal to the current level is a limp (at the big blind) or a
    call, a bigger one a raise, and a player with nothing behind is all-in.
    The bets are sorted by size: each raise is bigger than the one before.
    Equal bets are ordered by seat, so the first of them is taken as the raiser.
    """
    idx_of = {seat: i for i, seat in enumerate(order)}
    blind = {order[-1]: table.bb, order[-2]: table.sb}     # heads-up order[-2] is the button, the small blind
    vol = []
    for seat in order:
        k = seat - 1
        bet = table.bets[k]
        if bet <= blind.get(seat, 0.0) + 1e-9:
            continue
        vol.append((bet, idx_of[seat], seat))
    vol.sort()
    acts, level = [], table.bb
    for bet, i, seat in vol:
        allin = table.behind[seat - 1] <= 1e-9
        if bet > level + 1e-9:
            acts.append(Act(i, "allin" if allin else "raise", bet))
            level = bet
        elif abs(bet - table.bb) < 1e-9 and level <= table.bb + 1e-9:
            acts.append(Act(i, "limp", bet))
        else:
            acts.append(Act(i, "allin" if allin else "call", bet))
    return acts


def _facing_text(acts: list[Act], hero: int, n: int, bb: float) -> str:
    """'UTG raises to 2.5bb, CO calls' — what the reader saw happen before hero acts."""
    if not acts:
        return "folded to you"
    parts, raised = [], False
    for a in acts:
        who = "you" if a.idx == hero else position_name(n - 1 - a.idx, n)
        size = f"{a.amount / bb:.1f}bb".replace(".0bb", "bb")
        if a.kind == "limp":
            verb = "limped" if who == "you" else "limps"
        elif a.kind == "call":
            verb = "called" if who == "you" else "calls"
        elif a.kind == "allin":
            verb = f"all-in {size}"
        else:
            verb = (("re-raised to " if raised else "raised to ") if who == "you"
                    else ("re-raises to " if raised else "raises to ")) + size
        raised = raised or a.kind in ("raise", "allin")
        parts.append(f"{who} {verb}")
    return ", ".join(parts)


def _waiting_for(table: Table, order: list[int], first_round_level: float) -> list[str]:
    """Players who have to act before hero and have not: their cards are showing and
    they have put in less than the bet.  ``order`` is the acting order of this street;
    ``first_round_level`` is the bet everybody starts the street owing (the big blind
    before the flop, 0 after it)."""
    n = len(order)
    hero = order.index(1)
    bets = [table.bets[s - 1] for s in order]

    def live(i: int) -> bool:
        seat = table.seats[order[i] - 1]
        return i != hero and not seat.folded and not seat.sitting_out and table.behind[order[i] - 1] > 1e-9

    top = max(bets)
    if top <= first_round_level + 1e-9:
        if first_round_level <= 0:
            return []                                  # checks leave no trace
        pending = [i for i in range(hero) if live(i) and bets[i] < first_round_level - 1e-9]
    elif bets[hero] >= top - 1e-9:
        pending = [i for i in range(n) if live(i) and bets[i] < top - 1e-9]
    else:
        raiser = next((hero + j) % n for j in range(1, n) if bets[(hero + j) % n] >= top - 1e-9)
        between = []
        i = (raiser + 1) % n
        while i != hero:
            between.append(i)
            i = (i + 1) % n
        pending = [i for i in between if live(i) and bets[i] < top - 1e-9]
    return [table.seats[order[i] - 1].name or position_name(n - 1 - i, n) for i in pending]


def _hand_of(read: TableRead) -> tuple[int, tuple[int, int]]:
    cards = parse_cards("".join(read.hero_cards))
    if len(cards) != 2:
        raise ValueError(f"hero's cards could not be read ({' '.join(read.hero_cards) or 'none'})")
    return class_of(*cards), (cards[0], cards[1])


def _with_chips(action: str, bb: float, unit: str) -> str:
    """'RAISE to 2.2bb' -> 'RAISE to 2.2bb (440)' when the table counts chips."""
    if unit != "chips" or bb <= 1.5:
        return action
    m = re.search(r"(\d+(?:\.\d+)?)bb", action)
    if not m:
        return action
    return f"{action} ({float(m.group(1)) * bb:,.0f})"


def _engine_spot(table: Table, hand: int, cards, settings: LiveSettings):
    from ..cli import _state_spot              # the same spot `advise` builds from a tracked table

    spot, order = _state_spot(table.state, SimpleNamespace(hand=HANDS[hand], goal=settings.goal, facing=""))
    spot.cards = cards
    spot.acts = preflop_acts(table, order)
    hero_seat = 1
    hero_acted = table.bets[0] > {order[-1]: table.bb, order[-2]: table.sb}.get(hero_seat, 0.0) + 1e-9
    if hero_acted:                             # players behind who folded since are out of the hand
        for i, seat in enumerate(order):
            if table.seats[seat - 1].folded:
                spot.away[i] = True
    return spot, order


def _binary_players(n: int) -> int:
    return 8 if n >= 8 else 7 if n == 7 else 6


def _preflop(read: TableRead, table: Table, settings: LiveSettings, force: bool = False) -> Suggestion:
    hand, cards = _hand_of(read)
    spot, order = _engine_spot(table, hand, cards, settings)
    hero = order.index(1)
    n = len(order)
    pos = position_name(n - 1 - hero, n)
    hero_bb = spot.setup.start[hero] / spot.setup.bb
    info = (f"{HANDS[hand]} · {pos} · {hero_bb:.0f}bb · {n} players · "
            f"{_facing_text(spot.acts, hero, n, spot.setup.bb)}")
    warnings = list(table.warnings)
    waiting = _waiting_for(table, order, table.bb)
    if waiting:
        note = f"{', '.join(waiting)} still to act before you (cards showing, no chips in)"
        if not force:
            return Suggestion("wait", "", f"not your turn yet: {note}. If it is your turn, press Read now",
                              [], info, warnings)
        warnings.insert(0, note)

    if settings.mode == "tag":
        adv = advise(spot)
        return Suggestion("act", _with_chips(adv.action, table.bb, table.unit), adv.why[0] if adv.why else "",
                          adv.numbers[:2], info, warnings + adv.warnings[:1])

    raises = [a for a in spot.acts if a.kind in ("raise", "allin")]
    limps = [a for a in spot.acts if a.kind == "limp"]
    # the stack that matters: the smaller of hero's and the biggest still to act or already in
    rivals = [i for i in range(hero + 1, n) if not spot.away[i]] + [a.idx for a in spot.acts if a.idx != hero]
    rivals = rivals or [i for i in range(n) if i != hero]
    eff = min(spot.setup.start[hero], max(spot.setup.start[i] for i in rivals)) / spot.setup.bb
    shoves = [a for a in raises if a.kind == "allin"]
    if shoves:                                  # against an all-in: its size, or hero's stack if smaller
        eff = min(spot.setup.start[hero], max(min(a.amount, spot.setup.start[a.idx]) for a in shoves)) / spot.setup.bb
    if settings.mode == "binary":
        players = _binary_players(n)
        nb = n - 1 - hero
        facing, seat, size = "", None, None
        allins = [a for a in raises if a.kind == "allin"]
        if len(raises) >= 2 or (allins and len(raises) + len([a for a in spot.acts if a.kind == "call"]) >= 2):
            facing = "allins"
            size = max(a.amount for a in raises) / spot.setup.bb
        elif raises:
            r = raises[0]
            seat = n - 1 - r.idx
            facing = "allin" if r.kind == "allin" or r.amount >= 0.33 * spot.setup.start[r.idx] else "raise"
            size = min(r.amount, spot.setup.start[r.idx]) / spot.setup.bb if facing == "allin" else None
        elif limps and nb > 0:
            nb = min(players - 1, nb + 1)              # a limper in front: the range of the seat before
        action, why = BN.decide(hand, min(nb, players - 1), eff, settings.stage, facing, seat, size,
                                False, players)
        return Suggestion("act", action, why, [], info, warnings)

    # spin: three players or heads-up
    if n > 3:
        return Suggestion("error", "", "spin mode is for tables of 2 or 3 players", [], info)
    names = {n - 1: "BB", n - 2: "SB"}
    if n == 3:
        names[0] = "BTN"
    shoved = [names[a.idx] for a in raises if a.kind == "allin"]
    small = [a for a in raises if a.kind == "raise"]
    facing = ""
    if small and not shoved:
        facing = f"{names[small[0].idx]} raise"
    elif limps and not raises:
        facing = f"{names[limps[0].idx]} limp"
    pos_name = names[hero] if n == 3 else ("SB" if hero == 0 else "BB")
    if pos_name == "BB" and not raises and not limps:
        return Suggestion("act", "CHECK", "nobody raised: see the flop for free", [], info, warnings)
    from ..cli import _spin_spot
    ns = SimpleNamespace(pos=pos_name, players=n, shoved=",".join(shoved), facing=facing)
    key = _spin_spot(ns)
    action, why = SP.decide(hand, key, eff)
    return Suggestion("act", action, why, [], info, warnings)


# --------------------------------------------------------------------------
# What was seen earlier in the hand
# --------------------------------------------------------------------------

_STREET = {3: "flop", 4: "turn", 5: "river"}
_WEIGHT = {"check": 0, "call": 1, "bet": 2, "raise": 3, "shove": 4}


def _read_pot(read: TableRead) -> float | None:
    bets = sum(s.bet for s in read.seats)
    if read.middle_pot is not None:
        return read.middle_pot + bets
    if read.total_pot is not None:
        return max(read.total_pot, bets)
    return None


@dataclass
class HandMemory:
    """What was seen earlier in the same hand.

    ``observe`` takes every reading of the table (the local reader looks several
    times a second, also when it is not hero's turn); ``update`` is ``observe``
    plus the advice that was shown, for readers that look only when hero acts."""
    key: tuple = ()
    pre_seen: bool = False                 # this hand was seen before the flop
    raises: int = 0                        # raises seen before the flop
    raiser: str = ""                       # the last player to raise before the flop, if not hero
    hero_raised: bool = False              # hero made the last raise before the flop
    opener_behind: int | None = None       # players behind the first raiser
    roles: dict = field(default_factory=dict)      # name -> open | 3bet | call | limp
    lines: dict = field(default_factory=dict)      # name -> [(street, action, size)]
    street: int = 0                        # cards on the board at the last look
    aggressor: str = ""                    # who made the last bet or raise on this street
    _levels: dict = field(default_factory=dict, repr=False)      # raise size -> who was first seen with it
    _pre_total: float = field(default=0.0, repr=False)
    _street_bets: dict = field(default_factory=dict, repr=False)
    _level: float = field(default=0.0, repr=False)
    _start_pot: float | None = field(default=None, repr=False)

    @staticmethod
    def _key(read: TableRead) -> tuple:
        return (tuple(read.hero_cards), next((s.name for s in read.seats if s.has_button), ""))

    def matches(self, read: TableRead) -> bool:
        return self.key == self._key(read)

    def _reset(self, key: tuple) -> None:
        self.key, self.pre_seen, self.raises, self.raiser, self.hero_raised = key, False, 0, "", False
        self.opener_behind, self.roles, self.lines, self.street, self.aggressor = None, {}, {}, 0, ""
        self._levels, self._pre_total, self._street_bets, self._level, self._start_pot = {}, 0.0, {}, 0.0, None

    # -- every look -----------------------------------------------------
    def observe(self, read: TableRead) -> None:
        key = self._key(read)
        if key != self.key:
            self._reset(key)
        if len(read.hero_cards) < 2 or len(read.seats) < 2:
            return
        if not read.board:
            self._preflop(read)
        elif len(read.board) in _STREET:
            self._postflop(read)

    def update(self, read: TableRead, suggestion: Suggestion | None) -> None:
        self.observe(read)
        if read.board or not suggestion or suggestion.kind != "act":
            return
        hero = next((s for s in read.seats if s.is_hero), None)
        if re.match(r"(RAISE|3-BET|4-BET|ALL-IN|RE-RAISE)", suggestion.action) and hero is not None \
                and hero.name not in self._levels.values():
            # the advice was to raise; if hero's chips are not seen going in, take it that he did
            self.pre_seen, self.hero_raised, self.raiser = True, True, ""
            self.raises = max(self.raises, 1) + (1 if self.raises else 0)
            if self.opener_behind is None:
                order = self._order(read)
                self.opener_behind = len(order) - 1 - order.index(read.seats.index(hero))

    @staticmethod
    def _order(read: TableRead) -> list[int]:
        """Indexes into ``read.seats`` in preflop acting order (first to act ... SB, BB)."""
        n = len(read.seats)
        btn = next((k for k, s in enumerate(read.seats) if s.has_button), None)
        if btn is None:
            return list(range(n))
        if n == 2:
            return [btn, (btn + 1) % n]
        return [(btn + 3 + j) % n for j in range(n)]

    def _preflop(self, read: TableRead) -> None:
        bb = read.big_blind
        if not bb and not read.amounts_in_bb:
            return
        if read.amounts_in_bb:
            bb = 1.0
        sb = read.small_blind if (read.small_blind and not read.amounts_in_bb) else bb / 2.0
        total = sum(s.bet for s in read.seats)
        if total + 1e-9 < self._pre_total:
            return                                   # the chips are being pushed to the middle
        self._pre_total = total
        self.pre_seen = True
        order = self._order(read)
        n = len(order)
        blind = {order[-1]: bb, order[-2]: sb}
        place = {k: i for i, k in enumerate(order)}
        vol = [(read.seats[k].bet, place[k], k) for k in order if read.seats[k].bet > blind.get(k, 0.0) + 1e-9]
        for bet in sorted({b for b, _, _ in vol if b > bb + 1e-9}):
            if bet not in self._levels:
                first = min((i, k) for b, i, k in vol if b == bet)
                self._levels[bet] = read.seats[first[1]].name
        sizes = sorted(self._levels)
        roles = {}
        for bet, _i, k in vol:
            name = read.seats[k].name
            if bet in self._levels and self._levels[bet] == name:
                roles[name] = "open" if sizes.index(bet) == 0 else "3bet"
            elif bet <= bb + 1e-9:
                roles[name] = "limp"
            else:
                roles[name] = "call"
        for name, role in roles.items():             # who raised and then called a re-raise still raised
            if role != "call" or self.roles.get(name) not in ("open", "3bet", "limp"):
                self.roles[name] = role
        self.raises = len(sizes)
        hero = next((s.name for s in read.seats if s.is_hero), "")
        if sizes:
            last = self._levels[sizes[-1]]
            self.hero_raised, self.raiser = (last == hero), ("" if last == hero else last)
            first_name = self._levels[sizes[0]]
            k = next((k for k in order if read.seats[k].name == first_name), None)
            if k is not None:
                self.opener_behind = n - 1 - place[k]

    def _put(self, name: str, street: str, action: str, size: float | None) -> None:
        line = self.lines.setdefault(name, [])
        for j, (st, act, _sz) in enumerate(line):
            if st == street:
                if _WEIGHT[action] > _WEIGHT[act]:
                    line[j] = (street, action, size)
                return
        line.append((street, action, size))

    def _postflop(self, read: TableRead) -> None:
        cards = len(read.board)
        pot = _read_pot(read)
        bets = sum(s.bet for s in read.seats)
        if cards != self.street:
            if self.street in _STREET and cards > self.street:
                self._close(read)
            self.street, self._street_bets, self._level, self.aggressor = cards, {}, 0.0, ""
            self._start_pot = (pot - bets) if pot is not None else None
        street = _STREET[cards]
        base = self._start_pot if self._start_pot else (read.big_blind or 1.0)
        ups = sorted((s.bet, k) for k, s in enumerate(read.seats)
                     if s.bet > self._street_bets.get(s.name, 0.0) + 1e-9)
        for bet, k in ups:
            seat = read.seats[k]
            before = base + sum(self._street_bets.values())
            if bet > self._level + 1e-9:
                action = "shove" if (seat.all_in or seat.stack == 0) else ("raise" if self._level > 0 else "bet")
                self._level, self.aggressor = bet, seat.name
                size = bet / max(before, 1e-9)
            else:
                action, size = "call", None
            self._street_bets[seat.name] = bet
            if not seat.is_hero:
                self._put(seat.name, street, action, size)

    def _close(self, read: TableRead) -> None:
        """The street is over: who is still in and was not seen putting chips in called
        (if somebody bet) or checked."""
        street = _STREET[self.street]
        for s in read.seats:
            if s.is_hero or s.folded:
                continue
            if not any(st == street for st, _, _ in self.lines.get(s.name, [])):
                self._put(s.name, street, "call" if self.aggressor else "check", None)


# --------------------------------------------------------------------------
# After the flop
# --------------------------------------------------------------------------

def _range_for(role: str, behind: int, opener_behind: int | None, ptype: str) -> tuple[list[float], str]:
    """An opponent's range from what he did before the flop."""
    t = norm_type(ptype)
    wide = t in ("loose", "station", "maniac", "lag")
    if role == "open":
        return villain_open_range(behind, ptype), "opened"
    if role == "3bet":
        return threebet_range(max(1, 3 if opener_behind is None else opener_behind), ptype), "re-raised"
    if role == "any":
        return [1.0] * 169, "any two cards"
    if role == "limp":
        return villain_limp_range(behind, ptype), "limped"
    ch = vs_open_chart(max(1, 3 if opener_behind is None else opener_behind), behind)
    w = [max(c, sm, d) for c, sm, d in zip(ch["call"], ch["setmine"], ch["deep"])]
    w = [max(x, 0.25 * v) for x, v in zip(w, ch["value"])]
    if range_pct(w) < 6.0:                           # the chart re-raises or folds here; people still call
        ip = vs_open_chart(max(1, 3 if opener_behind is None else opener_behind), 2)
        w = [max(x, c, sm, d) for x, c, sm, d in zip(w, ip["call"], ip["setmine"], ip["deep"])]
    if wide:                                         # tables that call too much call with far more
        extra = top_percent(35.0 if behind == 0 else 25.0, list(play_order()))
        w = [max(x, 0.7 * e) for x, e in zip(w, extra)]
    return w, "called"


def _postflop(read: TableRead, table: Table, settings: LiveSettings, memory: HandMemory | None,
              force: bool = False) -> Suggestion:
    _, cards = _hand_of(read)
    board = parse_cards("".join(read.board))
    if len(board) not in (3, 4, 5):
        raise ValueError(f"the board could not be read ({' '.join(read.board)})")
    street = _STREET[len(board)]
    n = table.n
    pre_order = S.action_order(table.state)              # preflop: first to act ... SB, BB
    # after the flop the small blind acts first and the button last
    post_order = pre_order[-2:] + pre_order[:-2] if n > 2 else pre_order[::-1]
    rank = {seat: k for k, seat in enumerate(post_order)}
    opp = [k + 1 for k, s in enumerate(table.seats) if k > 0 and not s.folded and not s.sitting_out]
    if not opp:
        return Suggestion("wait", "", "nobody else is in the hand", [], "", table.warnings)
    bets_total = sum(table.bets)
    pot = _read_pot(read)
    if pot is None:
        raise ValueError("the pot could not be read (mark the pot in the setup: it is needed after the flop)")
    hero_bet = table.bets[0]
    top_bet = max(table.bets[s - 1] for s in opp)
    to_call = max(0.0, min(top_bet - hero_bet, table.behind[0]))
    hero_pos = position_name(n - 1 - pre_order.index(1), n)
    info = (f"{''.join(read.hero_cards)} on {''.join(read.board)} · {hero_pos} · "
            f"{table.behind[0] / table.bb:.0f}bb behind · pot {pot / table.bb:.1f}bb · "
            f"{'to call ' + format(to_call / table.bb, '.1f') + 'bb' if to_call else 'checked to you'} · {street}"
            + (f" · {len(opp)} opponents" if len(opp) > 1 else ""))
    warns = list(table.warnings)
    waiting = _waiting_for(table, post_order, 0.0)
    if waiting:
        note = f"{', '.join(waiting)} still to act before you (cards showing, less than the bet in)"
        if not force:
            return Suggestion("wait", "", f"not your turn yet: {note}. If it is your turn, press Read now",
                              [], info, warns)
        warns.insert(0, note)

    # the opponent the decision is about: who made the bet hero faces, else the biggest stack in
    cyc = post_order[rank[1] + 1:] + post_order[:rank[1]]
    cyc = [s for s in cyc if s in opp]
    aggr = next((s for s in cyc if top_bet > 0 and table.bets[s - 1] >= top_bet - 1e-9), None)
    main = aggr if aggr is not None else max(opp, key=lambda s: table.behind[s - 1])
    in_position = all(rank[1] > rank[s] for s in opp)
    known = memory is not None and memory.matches(read) and memory.pre_seen
    hero_pfr = bool(known and memory.hero_raised)
    pre_pot = max(pot - bets_total, 1e-9)
    ptype = norm_type(settings.opponents)
    low = min((b for b in table.bets if b > 0), default=0.0)
    villains = []
    for s in [main] + [x for x in opp if x != main]:
        seat = table.seats[s - 1]
        behind = n - 1 - pre_order.index(s)
        pos = position_name(behind, n)
        if not known:
            role = "call"
        elif seat.name in memory.roles:
            role = memory.roles[seat.name]
        elif memory.raises == 0:
            role = "any" if behind == 0 else "limp"
        else:
            role = "call"
        w, label = _range_for(role, behind, memory.opener_behind if known else None, ptype)
        line = [e for e in (memory.lines.get(seat.name, []) if known else []) if e[0] != street]
        seen_now = [e for e in (memory.lines.get(seat.name, []) if known else []) if e[0] == street]
        bet = table.bets[s - 1]
        if bet > 0:
            if s == aggr:
                act = "shove" if table.behind[s - 1] <= 0 else ("raise" if low < top_bet - 1e-9 else "bet")
            elif bet >= top_bet - 1e-9 or (hero_bet > 0 and abs(bet - hero_bet) < 1e-9):
                act = "call"
            else:
                act = "bet" if bet <= low + 1e-9 else "raise"
            if seen_now and _WEIGHT[seen_now[0][1]] > _WEIGHT[act]:
                act = seen_now[0][1]
            line.append((street, act, bet / pre_pot if act != "call" else None))
        elif seen_now:
            line.append(seen_now[0])
        elif top_bet <= 0 and rank[s] < rank[1]:
            line.append((street, "check", None))     # checked to hero
        villains.append(Villain(w, ptype, line, f"{seat.name or pos} ({pos}): {label}"))
    facing = None
    if hero_bet > 0 and top_bet > hero_bet:
        facing = "shove" if table.behind[main - 1] <= 0 else "raise"
    prizes = S.build_prizes(table.state, settings.goal)
    rp = 0.0
    if not prizes.chip_ev:
        stacks = [b + x for b, x in zip(table.behind, table.bets)]
        rp = prizes.risk_premium(stacks, 0, main - 1)
    spot = PostflopSpot(hero=cards, board=board, pot=pot, to_call=to_call, hero_stack=table.behind[0],
                        villain_stack=table.behind[main - 1], villains=villains, in_position=in_position,
                        hero_pfr=hero_pfr, facing=facing, bb=table.bb, risk_premium=rp,
                        stage=S.stage(table.state)["label"])
    adv = advise_postflop(spot)
    if not known:
        warns.append("preflop action not seen: opponents are read as callers")
    return Suggestion("act", _with_chips(adv.action, table.bb, table.unit), adv.why[0] if adv.why else "",
                      adv.numbers[:2], info, warns + adv.warnings[:1])


# --------------------------------------------------------------------------

def suggest(read: TableRead, settings: LiveSettings, memory: HandMemory | None = None,
            force: bool = False, blocking: list[str] | None = None) -> Suggestion:
    """The coach's suggestion for a reading, or why there is none.

    ``blocking`` is what the reader could not read for sure that a decision
    depends on: with any of it there is no advice, only what to teach."""
    if not read.is_poker_table:
        return Suggestion("wait", "", "no poker table in the picture")
    ok, why = play_money_check(read, settings.markers)
    if not ok:
        return Suggestion("blocked", "", why)
    if memory is not None and not blocking:
        memory.observe(read)
    if not read.hero_to_act and not force:
        return Suggestion("wait", "", "not your turn")
    if blocking:
        return Suggestion("error", "", "cannot advise yet: " + "; ".join(blocking)
                          + ". Teach it (Teach in the launcher, or live-teach --log)")
    if len(read.hero_cards) < 2:
        return Suggestion("wait", "", "no cards in front of you")
    try:
        table = to_table(read, settings)
        if read.board:
            sug = _postflop(read, table, settings, memory, force)
        else:
            sug = _preflop(read, table, settings, force)
    except ValueError as exc:
        return Suggestion("error", "", str(exc))
    if not read.hero_to_act:
        sug.warnings.insert(0, "the action buttons are not showing: read on request")
    if read.unreadable:
        sug.warnings.append(f"unreadable: {read.unreadable}")
    if memory is not None:
        memory.update(read, sug)
    return sug
