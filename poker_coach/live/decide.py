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
from ..icm import Prizes
from ..postflop import PostflopSpot, Villain, advise_postflop, range_from_spec
from ..preflop import Act, advise
from ..ranges import position_name
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


def _preflop(read: TableRead, table: Table, settings: LiveSettings) -> Suggestion:
    hand, cards = _hand_of(read)
    spot, order = _engine_spot(table, hand, cards, settings)
    hero = order.index(1)
    n = len(order)
    pos = position_name(n - 1 - hero, n)
    hero_bb = spot.setup.start[hero] / spot.setup.bb
    info = f"{HANDS[hand]} · {pos} · {hero_bb:.0f}bb · {n} players · preflop"

    if settings.mode == "tag":
        adv = advise(spot)
        return Suggestion("act", _with_chips(adv.action, table.bb, table.unit), adv.why[0] if adv.why else "",
                          adv.numbers[:2], info, table.warnings + adv.warnings[:1])

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
        return Suggestion("act", action, why, [], info, table.warnings)

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
        return Suggestion("act", "CHECK", "nobody raised: see the flop for free", [], info, table.warnings)
    from ..cli import _spin_spot
    ns = SimpleNamespace(pos=pos_name, players=n, shoved=",".join(shoved), facing=facing)
    key = _spin_spot(ns)
    action, why = SP.decide(hand, key, eff)
    return Suggestion("act", action, why, [], info, table.warnings)


# --------------------------------------------------------------------------
# After the flop
# --------------------------------------------------------------------------

@dataclass
class HandMemory:
    """What was seen earlier in the same hand (the reads happen only when hero acts)."""
    key: tuple = ()
    raiser: str = ""                       # name of the last preflop raiser other than hero
    hero_raised: bool = False

    def update(self, read: TableRead, suggestion: Suggestion | None) -> None:
        key = (tuple(read.hero_cards), next((s.name for s in read.seats if s.has_button), ""))
        if key != self.key:
            self.key, self.raiser, self.hero_raised = key, "", False
        if read.board:
            return
        bets = [(s.bet, s.name) for s in read.seats if not s.is_hero]
        top = max(bets, default=(0.0, ""))
        if read.big_blind and top[0] > (read.big_blind or 0) * 1.01:
            self.raiser = top[1]
        if suggestion and suggestion.kind == "act" and re.match(r"(RAISE|3-BET|4-BET|ALL-IN|RE-RAISE)", suggestion.action):
            self.hero_raised = True
            self.raiser = ""

    def matches(self, read: TableRead) -> bool:
        return self.key == (tuple(read.hero_cards), next((s.name for s in read.seats if s.has_button), ""))


def _postflop(read: TableRead, table: Table, settings: LiveSettings, memory: HandMemory | None) -> Suggestion:
    _, cards = _hand_of(read)
    board = parse_cards("".join(read.board))
    if len(board) not in (3, 4, 5):
        raise ValueError(f"the board could not be read ({' '.join(read.board)})")
    n = table.n
    pre_order = S.action_order(table.state)              # preflop: first to act ... SB, BB
    # after the flop the small blind acts first and the button last
    post_order = pre_order[-2:] + pre_order[:-2] if n > 2 else pre_order[::-1]
    rank = {seat: k for k, seat in enumerate(post_order)}
    opp = [k + 1 for k, s in enumerate(table.seats) if k > 0 and not s.folded and not s.sitting_out]
    if not opp:
        return Suggestion("wait", "", "nobody else is in the hand", [], "", table.warnings)
    bets_total = sum(table.bets)
    if read.middle_pot is not None:
        pot = read.middle_pot + bets_total
    elif read.total_pot is not None:
        pot = max(read.total_pot, bets_total)
    else:
        raise ValueError("the pot could not be read")
    hero_bet = table.bets[0]
    top_bet = max(table.bets[s - 1] for s in opp)
    to_call = max(0.0, min(top_bet - hero_bet, table.behind[0]))
    main = max(opp, key=lambda s: (table.bets[s - 1], table.behind[s - 1]))
    in_position = all(rank[1] > rank[s] for s in opp)
    known = memory is not None and memory.matches(read)
    hero_pfr = bool(known and memory.hero_raised and not memory.raiser)
    pre_pot = max(pot - bets_total, 1e-9)
    villains = []
    for s in opp:
        seat = table.seats[s - 1]
        pos = position_name(n - 1 - pre_order.index(s), n)
        if known and memory.raiser and seat.name == memory.raiser:
            spec = "3bet" if memory.hero_raised else f"open:{pos}"
        else:
            spec = f"call:{pos}"
        w, label = range_from_spec(spec, n, "unknown", None)
        line = []
        street = {3: "flop", 4: "turn", 5: "river"}[len(board)]
        bet = table.bets[s - 1]
        if bet > 0 and hero_bet == 0:
            line = [(street, "shove" if table.behind[s - 1] <= 0 else "bet", bet / pre_pot)]
        villains.append(Villain(w, "unknown", line, f"{seat.name or pos}: {label}"))
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
    street = {3: "flop", 4: "turn", 5: "river"}[len(board)]
    info = (f"{''.join(read.hero_cards)} on {''.join(read.board)} · pot {pot / table.bb:.1f}bb · "
            f"{'to call ' + format(to_call / table.bb, '.1f') + 'bb' if to_call else 'checked to you'} · {street}")
    warns = list(table.warnings)
    if not known:
        warns.append("preflop action not seen: opponents are read as callers")
    return Suggestion("act", _with_chips(adv.action, table.bb, table.unit), adv.why[0] if adv.why else "",
                      adv.numbers[:2], info, warns + adv.warnings[:1])


# --------------------------------------------------------------------------

def suggest(read: TableRead, settings: LiveSettings, memory: HandMemory | None = None,
            force: bool = False) -> Suggestion:
    """The coach's suggestion for a reading, or why there is none."""
    if not read.is_poker_table:
        return Suggestion("wait", "", "no poker table in the picture")
    ok, why = play_money_check(read, settings.markers)
    if not ok:
        return Suggestion("blocked", "", why)
    if not read.hero_to_act and not force:
        return Suggestion("wait", "", "not your turn")
    if len(read.hero_cards) < 2:
        return Suggestion("wait", "", "no cards in front of you")
    try:
        table = to_table(read, settings)
        if read.board:
            sug = _postflop(read, table, settings, memory)
        else:
            sug = _preflop(read, table, settings)
    except ValueError as exc:
        return Suggestion("error", "", str(exc))
    if not read.hero_to_act:
        sug.warnings.insert(0, "the action buttons are not showing: read on request")
    if read.unreadable:
        sug.warnings.append(f"unreadable: {read.unreadable}")
    if memory is not None:
        memory.update(read, sug)
    return sug
