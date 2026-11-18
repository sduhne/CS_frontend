"""The advice adapter: the table on screen in, the coach's answer out.

    answer = advise(session)        # the dict of the build spec, section 7

``advise`` reads a ``model.Session`` and never changes it.  It never raises:
when the engine stops on a spot the answer says NO ADVICE and why.

How an answer is made, top to bottom of this file:

1. **What is awaited.**  No hand, no cards, not hero's turn: status "none"
   and a line saying what the table is waiting for.
2. **Reading the table** (``Seen``): the hand at hero's turn in the engine's
   terms.  Players are passed by their index in the acting order, never by
   name; stacks are start-of-hand stacks; an action is the total a player has
   in front of him.
3. **The tournament numbers** (``Money``): the prize model, how much of it is
   known (ICM off, estimated, on, exact), the stage, the fold clock.
4. **The route.**  Which part of the engine answers:

       tournament, full plan     preflop.advise, then the survival guard
       tournament, all-in plan   the all-in or fold tables (binary), the engine as a second line
       spin                      the spin tables to 16bb (20bb small blind and heads-up), the engine on chips above
       all-in or fold            aof.decide
       after the flop            postflop.advise_postflop, with roles and lines from the recorded actions

5. **The survival guard** (tournament, full plan, before the money).  When the
   engine's answer puts a third of the stack or more in before the flop, the
   all-in or fold table is asked as well.  If the table folds, the headline is
   FOLD, marked "survival fold", and the engine's answer becomes the second
   line.  The guard is off in the money, for a desperate stack, with a read on
   the player the decision depends on, while re-entry is open and in the
   Max EV style.
6. **The answer**: headline (verb, size, tone, how sure, the intent that
   carries it out), one sentence of reason, tiles, what flips it, plan lines,
   warnings, the source line, the range chart, the context.

Besides the keys of the build spec the answer carries ``icm`` (off,
estimated, on, exact) and ``guard`` (agrees, survival, off, none).  The user's
own notes on the opponents in the pot are shown among the warnings.

The engine is the baseline, not the last word: everything here is for study
and play money.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from .. import aof as AOF
from .. import binary as BN
from .. import latereg as LR
from .. import spin as SP
from .. import state as S
from .. import tag as TAG
from ..cards import COMBO_COUNT, HANDS, format_range, parse_cards, parse_hand, parse_range, range_pct
from ..equity import all_vs_range
from ..evaluator import describe
from ..icm import Prizes
from ..postflop import PostflopSpot, Villain, advise_postflop
from ..preflop import Act, Spot, _chart_shift
from ..preflop import advise as engine_advise
from ..pushfold import HandSetup, solve_open_shove, solve_reshove
from ..ranges import (PLAYER_TYPES, norm_type, parse, play_order, rfi_range, threebet_range, top_percent,
                      villain_limp_range, villain_open_range, vs_open_chart)
from .model import HERO, average_stack, goal_for, icm_level, imply_until, postflop_order, replay, session_level

# --------------------------------------------------------------------------
# Numbers a reader may want to change
# --------------------------------------------------------------------------

COMMIT_SHARE = 1 / 3            # the guard looks at plays that put this share of the stack in before the flop
RAISE_IS_ALLIN = 1 / 3          # a raise of this share of the raiser's stack is read as an all-in in the tables
# Players left per paid place from which the money is "close", and from which it is the bubble:
CLOSE_TO_MONEY = {"regular": (1.5, 1.2)}    # on the regular blind ladder ...
CLOSE_TO_MONEY_DEFAULT = (2.0, 1.3)         # ... and on every other one (turbo speed or faster)
SPIN_TABLE_BB = 16              # spin: first in, the solved all-in or fold table answers up to this stack ...
SPIN_TABLE_BB_LATE = 20         # ... and up to this one from the small blind and heads-up
STALE_AFTER_HANDS = 10          # "players left" this many hands old gets a warning ...
STALE_ON_BUBBLE = 3             # ... and this many near the bubble
BLINDS_UP_BB = 20               # under this stack a pending level gets a second look at the new blinds
POSTFLOP_ITERS = 20000          # samples for the equity after the flop (heads-up turn and river are exact)
PLAYBOOK_BIG_BET = 0.60         # a river bet of this share of the pot is "big" for the one-pair rule
PLAYBOOK_POTS_BEHIND = 1.5      # ... which does not apply with fewer pots than this behind
EV_CLOSE_BB = 0.05              # an all-in within this of its threshold is drawn as "close" in a chart
CHART_SOLVER_WORK = 72          # a solver chart may cost about this many (rounds x players who can call)

PASSIVE_TYPES = ("nit", "tight", "loose", "station")        # their big bets and raises are rarely bluffs
LOOSE_TYPES = ("loose", "station", "maniac", "lag")         # they call with far more than the charts
SPIN_TYPE = {"solid": "unknown", "loose": "loose", "very-loose": "station"}    # table-wide setting -> engine type

SEAT_WORDS = {"UTG": "under the gun", "UTG+1": "in UTG+1", "UTG+2": "in UTG+2", "LJ": "in the lojack",
              "HJ": "in the hijack", "CO": "in the cutoff", "BTN": "on the button", "BTN/SB": "on the button",
              "SB": "in the small blind", "BB": "in the big blind"}
SEAT_TITLES = {"UTG": "Under the gun", "UTG+1": "UTG+1", "UTG+2": "UTG+2", "LJ": "Lojack", "HJ": "Hijack",
               "CO": "Cutoff", "BTN": "Button", "BTN/SB": "Button", "SB": "Small blind", "BB": "Big blind"}

STAGE_LINES = {
    "early": "Early: tight from the first seats, no big bluffs, no big calls with one pair.",
    "middle": "Middle: take the blinds from the cutoff, the button and the small blind; "
              "with 12 to 24bb move all-in over late raises.",
    "approach": "Approaching the money: keep stealing, refuse marginal all-in calls.",
    "near_bubble": "Near the bubble: call an all-in only with a premium, and do not fight the big stack.",
    "bubble": "Bubble: survival is worth more than chips. Fold marginal all-ins; if you are short, read the fold clock.",
    "itm": "In the money: the brake is off. Steal and move all-in again; look at the next prize before a big call.",
    "final_table": "Final table: every jump is large. Let shorter stacks bust first and call tighter than the chips say.",
    "unknown": "Stage unknown: enter players left and places paid.",
}

# The engine's words, said the way the rest of the app says them.  Applied in this order: the longer phrase first.
PLAIN_WORDS = (
    ("push-or-fold", "all-in or fold"), ("re-shove or fold", "all-in or fold"), ("re-shoving", "moving all-in"),
    ("a re-shove", "an all-in"), ("re-shove", "all-in"), ("raise-folding", "raising and then folding"),
    ("raise-fold", "raise and fold"), ("shoving", "moving all-in"), ("shoves", "moves all-in"),
    ("they shove", "they move all-in with"), ("to shove", "to move all-in"), ("so shove", "so move all-in"),
    ("a shove", "an all-in"), ("shove", "all-in"),
    ("TAG opening range", "opening range"),
    ("3-bettor's", "re-raiser's"), ("3-bettor", "re-raiser"), ("3-betting", "re-raising"), ("3-bet", "re-raise"),
    ("a 4-bet", "another re-raise"), ("4-bet", "re-raise"), ("limpers", "callers"), ("the limper", "the caller"),
    ("limping along", "calling along"), ("set-mine", "play for a set"),
)

MINUS = "\u2212"                # the real minus sign, for losses
DOT = " \u00b7 "                 # the middle dot between two parts of a line
WARNING_ORDER = ("heads_up", "caller_behind", "covered_call", "engine", "close", "note", "blinds_up",
                 "preflop_unknown", "outside_tables", "charts_loading", "icm_off", "reentry_open", "left_stale",
                 "icm_estimated", "bounty")


# ==========================================================================
# Small helpers: numbers and words
# ==========================================================================

def chips_text(chips) -> str:
    """Chips with thousands separators: 13200 -> "13,200"."""
    return f"{round(chips):,}"


def bb_number(big_blinds) -> str:
    """Big blinds to one decimal, without a trailing .0: 12, 2.2, 11.9."""
    text = f"{big_blinds:.1f}"
    return text[:-2] if text.endswith(".0") else text


def signed_bb(value) -> str:
    """A gain or a loss in big blinds: "+1.20bb", and a real minus sign for a loss."""
    return f"{value:+.2f}bb".replace("-", MINUS)


def percent(share) -> str:
    return f"{100 * share:.0f}%"


def sign_of(value) -> int:
    """+1 a gain, -1 a loss, 0 nothing to speak of (the tiles are coloured by it)."""
    return 1 if value > 0.005 else -1 if value < -0.005 else 0


def plain(text: str) -> str:
    """An engine sentence in the app's words: "shove" becomes "all-in", and so on."""
    for theirs, ours in PLAIN_WORDS:
        text = text.replace(theirs, ours)
    return text


def sentence(text: str) -> str:
    """A capital at the start and a full stop at the end."""
    text = " ".join(str(text).split())
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def tile(label: str, value: str, note: str = "", sign: int = 0) -> dict:
    return {"label": label, "value": value, "note": note, "sign": sign}


def warning(code: str, text: str, short: str = "") -> dict:
    """One warning.  ``short`` is what is left of it when it is folded into the count."""
    return {"code": code, "text": text, "short": short or text}


def in_range(text: str, hand: int) -> bool:
    return parse_range(text)[hand] >= 0.5


def share_of_hands(weights) -> int:
    """How much of all starting hands a range holds, in percent."""
    return round(100.0 * sum(c for c, w in zip(COMBO_COUNT, weights) if w >= 0.5) / 1326.0)


# ==========================================================================
# 1. The way in
# ==========================================================================

def advise(session, now: float | None = None) -> dict:
    """The coach's answer for the table as it stands.  Never raises.

    ``now`` is the time to measure the age of "players left" against (tests
    pass their own); nothing else here looks at the clock.
    """
    try:
        return answer_for(session, time.time() if now is None else now)
    except Exception as err:                    # whatever went wrong, the table goes on working
        return no_advice(blank_answer(getattr(session, "rev", 0)), err)


def blank_answer(rev: int) -> dict:
    """Every key of the answer, empty."""
    return {"rev": rev, "status": "none", "headline": None, "spot": "", "reason": "", "tiles": [], "flip": "",
            "also": "", "source": "", "plans": [], "warnings": [], "chart": None,
            "context": {"stage": "", "gear": "", "fold_clock": ""}, "icm": "off", "guard": "none"}


def no_advice(answer: dict, err: Exception) -> dict:
    """The engine stopped on this spot: say so, and keep whatever was already known."""
    answer.update(status="ready", reason=sentence(f"The engine stopped on this spot ({type(err).__name__}: {err}). "
                                                  "Play it from the sheet; the next spot is advised as usual"),
                  headline={"verb": "NO ADVICE", "size_text": "", "qualifier": "", "tone": "wait", "sure": "",
                            "follow": None},
                  tiles=[], flip="", also="", source="", plans=[], chart=None, guard="none")
    return answer


def answer_for(session, now: float) -> dict:
    data = session.data
    answer = blank_answer(session.rev)
    money = read_money(session) if data["mode"] == "tournament" else None
    standing = []
    if money is not None:
        answer["icm"] = money.level
        standing = standing_warnings(data, money, now)
    answer["context"] = context_lines(data, money)
    view = session.view()
    awaited = what_is_awaited(session, view)
    if awaited:
        answer.update(spot=awaited, warnings=shown_warnings(standing))
        return answer
    seen = read_table(session, view)
    answer["spot"] = spot_line(seen)
    try:
        play = choose_play(seen, money)
    except Exception as err:                    # the engine stopped: the spot line and the context still stand
        answer["warnings"] = shown_warnings(standing)
        return no_advice(answer, err)
    return finished_answer(answer, seen, money, play, standing)


def what_is_awaited(session, view: dict) -> str | None:
    """What the table is waiting for when there is nothing to advise; ``None`` when hero has a decision."""
    data, hand = session.data, view["hand"]
    if data["mode"] == "spin" and data["game"]["over"] and (hand is None or hand["needs"] == "next"):
        return "The game is over: press N for a new game."
    if hand is None:
        return "No hand is being played: press N to deal."
    if hand["needs"] == "next":
        return "The hand is over: press N for the next hand."
    if hand["needs"] == "result":
        return "The betting is over: say who won."
    state = session.hand_state()
    if HERO not in state.order:
        return "You are not in this hand."
    if HERO in state.folded:
        return "You have folded: nothing left to decide."
    if hand["needs"] == "cards":
        if state.phase == "preflop":
            return "Type your two cards for advice."
        return "After the flop the coach needs your exact cards: type them with their suits, like AhKd."
    if hand["needs"] == "board":
        return {0: "Type the flop.", 3: "Type the turn card.", 4: "Type the river card."}.get(len(hand["board"]),
                                                                                             "Type the board.")
    if state.stack[HERO] <= 0:
        return "You are all-in: nothing left to decide."
    if not hand["target_is_hero"]:
        if state.phase == "preflop" and state.labels.get(HERO) == "BB" and state.raises == 0:
            # the big blind acts last: until somebody enters there is no decision
            if data["mode"] == "aof":
                return "Nobody has moved all-in yet: in the big blind you act last."
            return "Nobody has entered yet: in the big blind you act last. Enter the first call or raise."
        target = hand["target"]
        if target is None:
            return "The betting round is over."
        name = (data["table"]["seats"].get(str(target)) or {}).get("name", "")
        label = state.labels.get(target, f"seat {target}")
        return f"Waiting for {name + ' (' + label + ')' if name else label}: it is not your turn."
    return None


# ==========================================================================
# 2. Reading the table
# ==========================================================================

@dataclass
class Seen:
    """The hand as it stands when hero has to act, in the engine's terms."""
    data: dict                  # the session of the mode on screen
    mode: str                   # tournament, spin or aof
    hand: dict                  # the stored hand
    state: object               # model.HandState at hero's turn (players in front of him took the passive default)
    order: list                 # seats in the order they act before the flop
    hero: int                   # hero's index in that order
    bb: float
    setup: HandSetup            # stacks and forced bets, as the engine wants them
    hand_class: int             # 0..168
    cards: tuple | None         # the two exact cards, when the suits were typed
    types: list                 # opponent type by index: the seat's tag, else the table's default
    tags: list                  # the seat tags alone: a tag is a read on that player
    away: list                  # by index: sitting out (or gone from the hand when hero acts a second time)
    acts: list                  # engine actions before the flop, hero's own included
    to_call: float              # what hero must add to stay in
    legal: dict                 # what hero may do, from the view

    @property
    def n(self) -> int:
        return len(self.order)

    @property
    def hand_name(self) -> str:
        return HANDS[self.hand_class]

    @property
    def start(self) -> list:
        """Start-of-hand stacks by index."""
        return self.setup.start

    def behind(self, index: int) -> int:
        """Players still to act after this one before the flop: 0 is the big blind."""
        return self.n - 1 - index

    def label(self, index: int) -> str:
        return self.state.labels[self.order[index]]

    def who(self, index: int) -> str:
        """A player for a sentence: "Kim (CO)", or the seat name alone, or "you"."""
        seat = self.order[index]
        if seat == HERO:
            return "you"
        name = (self.data["table"]["seats"].get(str(seat)) or {}).get("name", "")
        return f"{name} ({self.label(index)})" if name else self.label(index)

    def bbs(self, chips) -> float:
        return chips / self.bb


def read_table(session, view: dict) -> Seen:
    data, hand = session.data, session.data["hand"]
    state = replay(hand)
    if state.to_act() != HERO:
        imply_until(state, HERO)                # "folded to you": the players in front take the passive default
    order = list(state.order)
    level = hand["level"]
    # Start-of-hand stacks; the engine posts antes and blinds itself.
    setup = HandSetup([state.start[seat] for seat in order], level["sb"], level["bb"],
                      level.get("ante") or 0, level.get("bb_ante") or 0)
    hand_class, cards = parse_hand(hand["hero_cards"])
    types, tags = seat_types(data, order)
    acts = preflop_acts(state, order)
    hero = order.index(HERO)
    away = [seat in state.away for seat in order]
    if any(act.idx == hero for act in acts):
        # hero acts a second time: the players behind him who folded since are out of the hand
        for index in range(hero + 1, len(order)):
            away[index] = away[index] or order[index] in state.folded
    return Seen(data=data, mode=data["mode"], hand=hand, state=state, order=order, hero=hero, bb=level["bb"],
                setup=setup, hand_class=hand_class, cards=cards, types=types, tags=tags, away=away, acts=acts,
                to_call=view["hand"]["to_call"], legal=view["hand"]["legal"] or {})


def seat_types(data: dict, order: list) -> tuple[list, list]:
    """(type the engine uses, the seat's own tag) for every player, by index."""
    setting = data["config"].get("opponents")
    if data["mode"] == "tournament":
        default = setting if setting in PLAYER_TYPES else "unknown"
    else:
        default = SPIN_TYPE.get(setting, "unknown")
    types, tags = [], []
    for seat in order:
        tag = norm_type((data["table"]["seats"].get(str(seat)) or {}).get("type"))
        if seat == HERO:
            tag = "unknown"
        tags.append(tag)
        types.append(tag if tag != "unknown" or seat == HERO else default)
    return types, tags


def preflop_acts(state, order: list) -> list:
    """What each player did before the flop, as the engine reads it.

    Folds and checks are left out.  A call before any raise is a limp.  The
    amount is the total the player has in front of him ("raise to").
    """
    acts, raised = [], False
    for entry in state.log:
        if entry["street"] != "preflop" or entry["kind"] in ("fold", "check"):
            continue
        index = order.index(entry["seat"])
        if entry["kind"] == "call":
            acts.append(Act(index, "call" if raised else "limp", entry["to"]))
        else:                                   # a raise (the big blind is the bet, so nobody "bets" before the flop)
            acts.append(Act(index, "allin" if entry["allin"] else "raise", entry["to"]))
            raised = True
    return acts


@dataclass
class Before:
    """What happened before hero acts, sorted the way the engine's own router sorts it."""
    kind: str = "first_in"      # first_in limped raise allin raise_allin allins raise_reraise reraised shoved_on
                                # called_then_raised wait
    raises: list = field(default_factory=list)      # the other players' raises and all-ins, in order
    limpers: list = field(default_factory=list)     # indexes of players who called the big blind
    callers: list = field(default_factory=list)     # indexes of players who called a raise or an all-in
    hero_raise: float = 0.0     # hero's own raise, if he made one
    hero_called: bool = False   # hero limped or called earlier in the hand


def what_happened(seen: Seen) -> Before:
    before = Before()
    live, hero = seen.setup.live, seen.hero
    level = seen.bb
    all_raises = []                             # hero's own included, to know what came after his
    called_an_allin = False                     # somebody called a player who is all-in: two hands will be shown
    for act in seen.acts:
        if act.kind in ("raise", "allin") and act.amount > level + 1e-9:
            all_in = act.kind == "allin" or act.amount >= live[act.idx] - 1e-9
            all_raises.append(Act(act.idx, "allin" if all_in else "raise", act.amount))
            level = act.amount
            if act.idx == hero:
                before.hero_raise = act.amount
        elif act.idx == hero:
            before.hero_called = True
        elif all_raises:
            before.callers.append(act.idx)
            called_an_allin = called_an_allin or all_raises[-1].kind == "allin"
        else:
            before.limpers.append(act.idx)
    before.raises = [r for r in all_raises if r.idx != hero]
    all_ins = [r for r in before.raises if r.kind == "allin"]
    if not all_raises:
        before.kind = "limped" if before.limpers else "first_in"
    elif called_an_allin or len(all_ins) >= 2:
        before.kind = "allins"
    elif before.hero_raise:
        mine = max(k for k, r in enumerate(all_raises) if r.idx == hero)
        later = all_raises[mine + 1:]
        before.kind = "wait" if not later else "shoved_on" if later[-1].kind == "allin" else "reraised"
    elif before.hero_called:
        before.kind = "called_then_raised"
    elif len(before.raises) == 1:
        before.kind = "allin" if all_ins else "raise"
    else:
        before.kind = "raise_allin" if before.raises[-1].kind == "allin" else "raise_reraise"
    return before


def effective_stack(seen: Seen) -> float:
    """The stack that matters, in chips: the smaller of hero's and the biggest that can still play against him."""
    hero, start = seen.hero, seen.start
    rivals = [i for i in range(hero + 1, seen.n) if not seen.away[i]]
    rivals += [act.idx for act in seen.acts if act.idx != hero]
    if not rivals:
        rivals = [i for i in range(seen.n) if i != hero]
    return min(start[hero], max(start[i] for i in rivals))


def engine_spot(seen: Seen, prizes: Prizes, field_prizes: Prizes, stage: dict, desperate: bool) -> Spot:
    """The spot for ``preflop.advise``.  Seats are named by their label, so engine text reads like the table."""
    return Spot(setup=seen.setup, hero=seen.hero, hand=seen.hand_class, cards=seen.cards,
                names=[seen.label(i) for i in range(seen.n)], types=list(seen.types), away=list(seen.away),
                prizes=prizes, field_prizes=field_prizes, acts=list(seen.acts), stage=stage, desperate=desperate)


def spot_line(seen: Seen) -> str:
    """One line that says where hero is: "AhKd in the cutoff, 21.5bb, folded to you"."""
    hero_label = seen.label(seen.hero)
    cards = seen.hand["hero_cards"]
    if seen.state.phase != "preflop":
        return f"{cards} on {''.join(seen.hand['board'])}, {street_story(seen)}"
    stack = bb_number(seen.bbs(seen.start[seen.hero]))
    return f"{cards} {SEAT_WORDS.get(hero_label, 'in ' + hero_label)}, {stack}bb, {preflop_story(seen)}"


def preflop_story(seen: Seen) -> str:
    """What happened before the flop, in a few words."""
    parts, raised = [], False
    for entry in seen.state.log:
        if entry["street"] != "preflop" or entry["kind"] in ("fold", "check"):
            continue
        index = seen.order.index(entry["seat"])
        who, mine = seen.who(index), entry["seat"] == HERO
        size = bb_number(seen.bbs(entry["to"])) + "bb"
        if entry["kind"] == "call":
            words = "called" if mine else "calls"
            parts.append(f"{who} {words}" + (" all-in" if entry["allin"] else ""))
        elif entry["allin"]:
            parts.append(f"you moved all-in for {size}" if mine else f"{who} is all-in for {size}")
        else:
            word = "re-raise" if raised else "raise"
            parts.append(f"you {word}d to {size}" if mine else f"{who} {word}s to {size}")
        raised = raised or entry["kind"] != "call"
    if not parts:
        return "first to act" if seen.hero == 0 else "folded to you"
    return ", ".join(parts)


def street_story(seen: Seen) -> str:
    """What hero faces after the flop: a bet, or nothing."""
    state = seen.state
    pot = state.pot_total()
    if seen.to_call <= 0:
        checked = any(e["street"] == state.phase and e["kind"] == "check" for e in state.log)
        return f"{'checked to you' if checked else 'you act first'}, pot {bb_number(seen.bbs(pot))}bb"
    bettor = max((s for s in state.live() if s != HERO), key=lambda s: state.in_front[s])
    who = seen.who(seen.order.index(bettor))
    bet = state.in_front[bettor]
    before = pot - sum(state.in_front.values())             # the pot before this street's bets
    if state.stack[bettor] <= 0:
        action = f"is all-in for {bb_number(seen.bbs(bet))}bb"
    elif state.raises >= 2:
        action = f"raises to {bb_number(seen.bbs(bet))}bb"
    else:
        action = f"bets {bb_number(seen.bbs(bet))}bb"
    return f"{who} {action} into {bb_number(seen.bbs(before))}bb"


# ==========================================================================
# 3. The tournament numbers
# ==========================================================================

@dataclass
class Money:
    """What the prizes make of the chips, and how far the money is."""
    state: dict                 # the table as ``poker_coach.state`` wants it
    goal: str                   # itm, balanced or chips
    level: str                  # off, estimated, on, exact: how much the prize maths knows
    prizes: Prizes              # hero's prize model
    field_prizes: Prizes        # what the opponents play for
    stage: dict                 # state.stage(): code, label, remaining, paid, to_money, hero_bb
    clock: dict | None          # state.fold_clock()
    ratio: float | None         # players left per paid place
    in_money: bool
    final_table: bool
    close: bool                 # close to the money: the all-in tables are read at twice the stack
    bubble: bool
    desperate: bool             # too short to wait: the engine judges the hand on chips


def read_money(session) -> Money:
    data = session.data
    state = session.engine_state()
    goal = goal_for(data)
    prizes = S.build_prizes(state, goal)
    # the opponents play for the real prizes, without hero's bonus for cashing
    field_prizes = Prizes() if prizes.chip_ev else Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack)
    stage = S.stage(state)
    clock = S.fold_clock(state)
    remaining, paid = stage.get("remaining"), stage.get("paid")
    ratio = remaining / paid if remaining and paid else None
    in_money = stage["code"] in ("itm", "final_table")
    close_at, bubble_at = CLOSE_TO_MONEY.get(data["structure"].get("ladder"), CLOSE_TO_MONEY_DEFAULT)
    hero_bb, to_money = stage.get("hero_bb"), stage.get("to_money")
    # The command line's rule: 6bb or less with the fold clock short, or 3bb or less far from the money.
    desperate = bool(hero_bb is not None and (
        (clock and clock.get("verdict") == "short" and hero_bb <= 6)
        or (hero_bb <= 3 and (to_money is None or to_money > 3))))
    return Money(state=state, goal=goal, level="off" if prizes.chip_ev else icm_level(data), prizes=prizes,
                 field_prizes=field_prizes, stage=stage, clock=clock, ratio=ratio, in_money=in_money,
                 final_table=stage["code"] == "final_table",
                 close=not in_money and ratio is not None and ratio <= close_at,
                 bubble=not in_money and ratio is not None and ratio < bubble_at, desperate=desperate)


def standing_warnings(data: dict, money: Money, now: float) -> list:
    """Warnings about the tournament numbers: they hold for every hand until the numbers are typed."""
    t = data["tournament"]
    out = []
    if t.get("reentry_open"):
        out.append(warning("reentry_open", "Re-entry is open: chip EV, guard off.", "re-entry open"))
    elif money.level == "off":
        missing = "players left" if not t.get("remaining") else "places paid"
        if not t.get("remaining") and not (t.get("paid") or t.get("entrants")):
            missing = "players left and places paid"
        out.append(warning("icm_off", f"ICM off: chip EV. Enter {missing}.", "ICM off"))
    elif money.level == "estimated":
        text = "ICM estimated: typical prizes, and the field's stacks are taken from this table. " \
               "Enter the average stack."
        if not t.get("paid"):
            text += " Places paid are taken as 15% of the entrants."
        out.append(warning("icm_estimated", text, "ICM estimated"))
    age = players_left_age(data, now)
    limit = STALE_ON_BUBBLE if money.stage["code"] in ("near_bubble", "bubble") else STALE_AFTER_HANDS
    if age is not None and age >= limit and not money.final_table:
        out.append(warning("left_stale", f"Players left is about {age} hands old: update it.",
                           f"players left is {age} hands old"))
    if t.get("bounty"):
        out.append(warning("bounty", "Bounties are not priced: a call can be a little looser than this.",
                           "bounties not priced"))
    return out


def players_left_age(data: dict, now: float) -> int | None:
    """About how many hands ago "players left" was last changed.

    The session keeps the time of every change, not the hand number, so the
    age is the time since then at the table's pace.
    """
    marks = data["tournament"].get("history") or []
    if not marks or not data["tournament"].get("remaining"):
        return None
    per_hand = S.SEC_PER_HAND.get(data["config"].get("pace"), 55)
    return int(max(0.0, now - marks[-1]["t"]) / per_hand)


def context_lines(data: dict, money: Money | None) -> dict:
    """Where the tournament stands: the stage, the gear for this stack, the fold clock."""
    if data["mode"] == "spin":
        return {"stage": "", "fold_clock": "",
                "gear": f"{SPIN_TABLE_BB}bb or less: all-in or fold from the solved table. Deeper: small raises."}
    if money is None:
        return {"stage": "", "gear": "", "fold_clock": ""}
    stage = money.stage
    line = STAGE_LINES.get(stage["code"], STAGE_LINES["unknown"])
    if stage["code"] in ("approach", "near_bubble", "bubble") and stage.get("to_money"):
        line = f"{stage['to_money']} from the money. " + line
    return {"stage": line, "gear": gear_line(data, stage.get("hero_bb")), "fold_clock": fold_clock_line(data, money)}


def gear_line(data: dict, hero_bb) -> str:
    """The gear for the stack, from the tight-aggressive sheet."""
    if hero_bb is None:
        return ""
    if data["config"].get("plan") == "allin":
        return "All-in or fold plan: one decision a hand, from the tables."
    floors = (40, 25, 17, 12, 0)                # the rows of tag.GEARS, deepest first
    for floor, (stack, name, what) in zip(floors, TAG.GEARS):
        if hero_bb >= floor:
            return f"{stack}: {name[0].lower() + name[1:]}. {what}"
    return ""


def fold_clock_line(data: dict, money: Money) -> str:
    """Can hero fold into the money?  Orbits and minutes of blinds against the time the bubble needs."""
    clock = money.clock
    if not clock:
        return ""
    orbits, minutes = clock["orbits"], clock["minutes"]
    lasts = f"{orbits:.1f} orbits of blinds, about {minutes:.0f} minutes"
    verdict, eta = clock.get("verdict"), clock.get("eta")
    needs = f"the bubble needs about {eta:.0f} minutes" if eta is not None else ""
    if verdict == "safe":
        text = f"You can fold into the money: {lasts}; {needs}."
    elif verdict == "tight":
        text = f"Folding into the money is tight: {lasts}; {needs}."
    elif verdict == "short":
        text = f"You cannot fold into the money: {lasts}; {needs}. Find an all-in."
    else:
        text = sentence(lasts)
        if not money.in_money and money.ratio is not None:
            text += " Change players left twice, a minute apart, for the bubble estimate."
    cover = sit_out_cover(data, money)
    if cover is not None:
        text += f" Your stack is {percent(cover)} of the sit-out line."
    after = next_level(data)
    hero_stack = S.hero_stack(money.state)
    if after and hero_stack and hero_stack / after["bb"] < BLINDS_UP_BB:
        text += f" At the next level: {bb_number(hero_stack / after['bb'])}bb."
    return text


def sit_out_cover(data: dict, money: Money) -> float | None:
    """Hero's stack as a share of the sit-out line, when the average stack is known and the money is ahead."""
    remaining, paid = money.stage.get("remaining"), money.stage.get("paid")
    average = average_stack(data)
    stack = S.hero_stack(money.state)
    if not (remaining and paid and average and stack) or remaining <= paid:
        return None
    return LR.zone(stack, average, remaining, paid)[1]


def next_level(data: dict) -> dict | None:
    """The blinds after the ones being played, when the ladder knows them."""
    structure = data["structure"]
    if structure.get("custom"):
        return None
    levels, index = structure["levels"], structure["index"]
    return levels[index + 1] if index + 1 < len(levels) else None


# ==========================================================================
# 4. The play: what each route hands back
# ==========================================================================

@dataclass
class Play:
    """One piece of advice, before it is dressed up as the answer."""
    verb: str                   # FOLD CHECK CALL BET RAISE RE-RAISE ALL-IN "RE-RAISE ALL-IN" WAIT
    kind: str                   # fold check call bet raise allin wait: the action that carries it out
    to: float | None = None     # a bet or a raise: the total in front of hero on this street, in chips
    qualifier: str = ""
    sure: str = "standard"      # clear, standard or close
    reason: str = ""
    tiles: list = field(default_factory=list)
    flip: str = ""              # what would change the answer
    also: str = ""              # the second line
    plans: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    source: str = ""            # where the answer comes from (the prize level is put in front of it)
    guard: str = "none"         # agrees, survival, off or none
    chart: dict | None = None


def choose_play(seen: Seen, money: Money | None) -> Play:
    """The route: which part of the engine answers this spot."""
    if seen.state.phase != "preflop":
        if seen.mode == "aof":
            raise ValueError("All-In or Fold has no decisions after the flop")
        return after_the_flop(seen, money)
    if seen.mode == "aof":
        return aof_play(seen)
    if seen.mode == "spin":
        return spin_play(seen)
    if seen.data["config"].get("plan") == "allin":
        return allin_plan_play(seen, money)
    return full_plan_play(seen, money)


def read_engine_action(action: str, bb: float) -> tuple[str, str, float | None, str]:
    """A preflop action of the engine as (verb, kind, raise-to in chips, qualifier).

    The engine says: FOLD, CHECK, CHECK / take the walk, CALL, CALL (limp behind),
    ALL-IN, RAISE to 2.2bb, RAISE to 2.0bb and call any all-in, 3-BET to 6.9bb (...),
    4-BET to 21bb, RE-RAISE ALL-IN (isolate), RE-RAISE to 38bb (isolate), WAIT.
    """
    text = action.strip()
    note = re.search(r"\(([^)]*)\)\s*$", text)
    qualifier = note.group(1) if note else ""
    qualifier = {"limp behind": "call along", "semi-bluff, fold to a 4-bet": "semi-bluff: fold to another raise",
                 "puts the opener all-in": "puts the raiser all-in"}.get(qualifier, qualifier)
    if text.startswith("FOLD"):
        return "FOLD", "fold", None, ""
    if text.startswith("CHECK"):
        return "CHECK", "check", None, ""
    if text.startswith("CALL"):
        return "CALL", "call", None, qualifier
    if text.startswith("WAIT"):
        return "WAIT", "wait", None, ""
    if "ALL-IN" in text:
        return ("RE-RAISE ALL-IN" if text.startswith("RE-RAISE") else "ALL-IN"), "allin", None, qualifier
    size = re.search(r"to (\d+(?:\.\d+)?)bb", text)
    if size is None:
        raise ValueError(f"cannot read the engine's action {action!r}")
    if "call any all-in" in text:
        qualifier = "and call any all-in"
    verb = "RAISE" if text.startswith("RAISE") else "RE-RAISE"
    return verb, "raise", float(size.group(1)) * bb, qualifier


def engine_facts(adv) -> dict:
    """The numbers of an engine answer, by name.  Some are in ``data``, the rest only in its sentences."""
    facts = dict(adv.data)
    text = " | ".join(adv.numbers)
    patterns = {
        "ev": r"shove EV ([+-]\d+\.\d+)bb",
        "all_fold": r"(?:everyone folds|they fold|both fold) (\d+)%",
        "when_called": r"when called you have (\d+)%",
        "open_range": r"opening range here: (\d+)%",
        "raise_range": r"isolation range: (\d+)%",
        "their_range": r"(?:opening range|3-bet range|3-bettor's range) ~(\d+(?:\.\d+)?)%",
        "my_equity": r"your equity(?: vs it)? (\d+)%",
        "pot_odds": r"pot odds(?: to call)? (\d+)%",
    }
    for name, pattern in patterns.items():
        found = re.search(pattern, text)
        if found:
            facts[name] = float(found.group(1))
    both = re.search(r"equity vs both ranges (\d+)%; need about (\d+)%", text)
    if both:
        facts["equity"], facts["need"] = float(both.group(1)) / 100, float(both.group(2)) / 100
    for name in ("shove_ev_bb", "reshove_ev_bb"):
        if name in facts:
            facts["ev"] = facts[name]
    return facts


def engine_tiles(facts: dict, kind: str, value_note: str) -> list:
    """The key numbers of an engine answer as tiles, the most telling first."""
    tiles = []
    if kind == "call" and "pot_odds" in facts and "my_equity" in facts and "need" not in facts:
        tiles.append(tile("Price / equity", f"{facts['pot_odds']:.0f}% / {facts['my_equity']:.0f}%",
                          "pot odds; your equity against their range"))
    if "ev" in facts:
        tiles.append(tile("All-in against folding", signed_bb(facts["ev"]), value_note, sign_of(facts["ev"])))
    if "need" in facts and "equity" in facts:
        counted = "pot odds alone" if value_note == "chip EV" else "the price and ICM are counted"
        tiles.append(tile("Need / have", f"{percent(facts['need'])} / {percent(facts['equity'])}",
                          "equity: " + counted))
    if "all_fold" in facts:
        called = f"called: you have {facts['when_called']:.0f}%" if "when_called" in facts else ""
        tiles.append(tile("Everybody folds", f"{facts['all_fold']:.0f}%", called))
    if "villain_pct" in facts:
        tiles.append(tile("Their range", f"{facts['villain_pct']:.0f}%", "of hands, from seat, stack and type"))
    elif "their_range" in facts:
        note = f"you have {facts['my_equity']:.0f}% against it" if "my_equity" in facts else ""
        tiles.append(tile("Their range", f"{facts['their_range']:g}%", note))
    if "open_range" in facts:
        tiles.append(tile("Open range here", f"{facts['open_range']:.0f}%", "of hands, from this seat at this depth"))
    if "raise_range" in facts:
        tiles.append(tile("Raise range here", f"{facts['raise_range']:.0f}%", "of hands, over the callers"))
    return tiles[:3]


def plan_lines(seen: Seen, adv) -> list:
    """"If BB (28bb) moves all-in: FOLD": the engine's plan against an all-in over hero's raise."""
    plans = []
    for line in adv.numbers:
        found = re.match(r"if (\S+) \((\d+)bb\) shoves: (CALL|FOLD) \(need (\d+%), have (\d+%)", line)
        if not found:
            continue
        label, stack, verdict, need, have = found.groups()
        who = next((seen.who(i) for i in range(seen.n) if seen.label(i) == label), label)
        plans.append(f"If {who} ({stack}bb) moves all-in: {verdict} (need {need}, have {have})")
    if "call any all-in" in adv.action:
        plans.append("If anybody moves all-in: CALL")
    return plans


def play_from_engine(seen: Seen, adv, value_note: str) -> Play:
    """An answer of ``preflop.advise`` as a play: its action, its first reason, its numbers."""
    verb, kind, to, qualifier = read_engine_action(adv.action, seen.bb)
    facts = engine_facts(adv)
    play = Play(verb=verb, kind=kind, to=to, qualifier=qualifier, sure=adv.confidence,
                reason=sentence(plain(adv.why[0])) if adv.why else "",
                tiles=engine_tiles(facts, kind, value_note),
                also=sentence(plain(adv.alt[0])) if adv.alt else "", plans=plan_lines(seen, adv))
    for text in adv.warnings:
        play.warnings.append(warning("engine", sentence(plain(text))))
    if "need" in facts and "breakeven_pct" in facts:
        play.flip = call_flip(facts, verb)
    return play


def call_flip(facts: dict, verb: str) -> str:
    """Facing an all-in: how wide they must be for a call, and which read would turn the answer."""
    line = facts.get("breakeven_pct")
    if line is None:
        return "No realistic all-in range makes this a call."
    modelled = facts.get("villain_pct") or 0
    text = f"A call whenever they move all-in with {line:g}% of hands or more (modelled: {modelled:.0f}%)."
    # roughly: a nit moves in with 0.6 times this range, a maniac with 1.6 times
    if verb != "FOLD" and modelled * 0.6 < line:
        text += " Fold against a nit."
    elif verb == "FOLD" and modelled * 1.6 >= line:
        text += " A call against a maniac."
    return text


def engine_summary(play: Play) -> str:
    """An engine play in a few words, for a second line: "ALL-IN +0.15bb", "CALL, 60% against 53%"."""
    number = next((t for t in play.tiles if t["label"] in ("All-in against folding", "Need / have")), None)
    if number is None:
        return play.verb
    if number["label"] == "Need / have":
        need, have = number["value"].split(" / ")
        return f"{play.verb}, {have} against {need}"
    return f"{play.verb} {number['value']}"


# ==========================================================================
# 5. Tournament, full plan: the engine, then the survival guard
# ==========================================================================

def full_plan_play(seen: Seen, money: Money) -> Play:
    before = what_happened(seen)
    if before.kind == "called_then_raised" and before.raises[-1].kind != "allin":
        return called_then_raised(seen, before)
    spot = engine_spot(seen, money.prizes, money.field_prizes, money.stage, money.desperate)
    adv = engine_advise(spot)
    play = play_from_engine(seen, adv, value_note(money))
    play.chart = hero_cell_as_played(engine_chart(seen, spot, adv, before), seen.hand_class, play.kind)
    play.source = "the engine decides"
    if not play.flip:
        play.flip = table_limit_line(seen, money, before)
    survival_guard(seen, money, before, play)
    add_spot_warnings(seen, money, before, adv, play)
    return play


def player_notes(seen: Seen) -> list:
    """The user's own notes on the opponents who are in the pot, as warnings: "Kim (CO): calls any ace"."""
    state = seen.state
    entered = {entry["seat"] for entry in state.log if entry["kind"] not in ("fold", "check")}
    notes = []
    for seat in state.live():
        text = (seen.data["table"]["seats"].get(str(seat)) or {}).get("note", "")
        if seat != HERO and text and (seat in entered or state.phase != "preflop"):
            who = seen.who(seen.order.index(seat))
            notes.append(warning("note", f"Your note on {who}: {text}", f"a note on {who}"))
    return notes[:2]


def value_note(money: Money | None) -> str:
    if money is None or money.prizes.chip_ev or money.desperate:
        return "chip EV"
    return "ICM counted"


def called_then_raised(seen: Seen, before: Before) -> Play:
    """Hero only called and a player raised: the sheet's rule, not the engine (which does not price hero's call).

    Fold.  With a pair and 15 times the raise behind, one call for a set is allowed.
    """
    pair = seen.hand_class % 14 == 0            # the pairs sit on the diagonal of the 13 x 13 grid
    behind = seen.state.stack[HERO]
    if pair and seen.to_call > 0 and behind >= 15 * seen.to_call:
        return Play(verb="CALL", kind="call", qualifier="once, for a set", sure="close",
                    reason="You only called and were raised: with a pair and 15 times the raise behind, one call "
                           "for a set is allowed.",
                    flip="Fold the flop without a set or an overpair.", source="the sheet's rule")
    return Play(verb="FOLD", kind="fold", sure="standard",
                reason="You only called and a player raised: fold. Only a pair with 15 times the raise behind may call.",
                source="the sheet's rule")


def add_spot_warnings(seen: Seen, money: Money, before: Before, adv, play: Play) -> None:
    """Warnings about this decision: the engine's weak spots, a close call, blinds about to rise."""
    eff_bb = seen.bbs(effective_stack(seen))
    if seen.n == 2 and before.kind == "first_in" and 10 < eff_bb <= 20:
        play.warnings.append(warning(
            "heads_up", "Heads-up with 10 to 20bb the engine only moves all-in or folds: a small raise with the "
                        "playable hands is normal there.", "heads-up: all-in or fold only"))
    state = seen.state
    shover = seen.order[before.raises[-1].idx] if before.raises else None
    still_in = [s for s in state.live() if s not in (HERO, shover) and state.stack[s] > 0 and state.owe(s) > 0]
    if before.kind == "shoved_on" and still_in:
        # hero raised, somebody called, then came the all-in: the engine prices the all-in player alone
        play.warnings.append(warning(
            "caller_behind", "A player who called your raise is still to act: the engine does not count him.",
            "a caller is still behind"))
    if money.final_table and play.kind in ("call", "allin") and before.raises:
        # the engine decides alone at a final table; say so when the bubble table would not call a bigger stack
        says = table_answer(seen, money, before)
        covered = any(seen.start[r.idx] >= seen.start[seen.hero] for r in before.raises)
        if covered and says is not None and says.action == "FOLD":
            play.warnings.append(warning(
                "covered_call", f"The all-in player covers you: the bubble table folds this hand here "
                                f"(it plays {says.short}).", "the bubble table folds against a bigger stack"))
    if before.hero_called and before.raises:
        play.warnings.append(warning(
            "engine", "You called earlier in this hand: the engine does not count those chips, so the price it "
                      "works with is a little worse than the real one.", "your earlier call is not priced"))
    if adv.confidence == "close" and play.guard != "survival":
        play.warnings.append(close_warning(engine_facts(adv), before, money, play.kind))
    after = pending_level(seen)
    if after and before.kind == "first_in" and seen.bbs(seen.start[seen.hero]) < BLINDS_UP_BB:
        play.warnings.append(blinds_up_warning(seen, money, after))


def close_warning(facts: dict, before: Before, money: Money | None, kind: str = "") -> dict:
    if "need" in facts and "equity" in facts:
        text = f"Close: you need {percent(facts['need'])} and have {percent(facts['equity'])}."
    elif kind == "call":
        text = "Close: the call and the fold are worth about the same."
    elif "ev" in facts:
        wants = "; over a raise the engine wants +0.15bb" if before.kind == "raise" else ""
        text = f"Close: an all-in earns {signed_bb(facts['ev'])} against folding{wants}."
    else:
        text = "Close: the other play is nearly as good."
    if money is not None and not money.in_money and not money.prizes.chip_ev:
        text += " Before the money the lower-variance side leads."
    return warning("close", text, "close")


def pending_level(seen: Seen) -> dict | None:
    """The blinds waiting for the next hand, when the level was moved during this one."""
    now, dealt = session_level(seen.data), seen.hand["level"]
    changed = any(now[key] != dealt[key] for key in ("sb", "bb", "ante", "bb_ante"))
    return now if changed and now["bb"] > dealt["bb"] else None


def blinds_up_warning(seen: Seen, money: Money, after: dict) -> dict:
    """The same hand at the blinds that are coming: a short stack may have to move now."""
    setup = HandSetup(seen.start, after["sb"], after["bb"], after.get("ante") or 0, after.get("bb_ante") or 0)
    spot = engine_spot(seen, money.prizes, money.field_prizes, money.stage, money.desperate)
    spot.setup = setup
    verb = read_engine_action(engine_advise(spot).action, after["bb"])[0]
    stack = bb_number(seen.start[seen.hero] / after["bb"])
    return warning("blinds_up", f"The blinds rise next hand ({stack}bb then). After the rise: {verb}.",
                   f"after the rise: {verb}")


# ---- the survival guard ------------------------------------------------------------

def risks_the_stack(seen: Seen, play: Play) -> bool:
    """Does the play put a third of hero's stack or more in before the flop?"""
    if play.kind == "allin" or "all-in" in play.qualifier:
        return True
    if play.kind == "call":
        total = seen.state.in_front[HERO] + seen.to_call
    elif play.kind == "raise":
        total = play.to or 0
    else:
        return False
    return total >= COMMIT_SHARE * seen.start[seen.hero]


def guard_is_off(seen: Seen, money: Money, before: Before) -> str:
    """Why the guard does not apply, or "" when it does."""
    if seen.data["config"].get("style") == "maxev":
        return "Max EV style"
    if money.goal == "chips":
        return "re-entry open"
    if money.final_table:
        return "final table"
    if money.in_money:
        return "in the money"
    if money.desperate:
        return "too short to wait"
    clock = money.clock or {}
    if money.stage["code"] in ("near_bubble", "bubble") and clock.get("verdict") == "short":
        return "the fold clock says you cannot fold"
    # A read on the player the decision depends on: the engine's range for him is then trusted.
    if before.raises:
        depends_on = [r.idx for r in before.raises]
    else:
        depends_on = [i for i in range(seen.hero + 1, seen.n) if not seen.away[i]]
    if depends_on and all(seen.tags[i] != "unknown" for i in depends_on):
        return "a read on " + ", ".join(seen.label(i) for i in depends_on[:2])
    return ""


def survival_guard(seen: Seen, money: Money, before: Before, play: Play) -> None:
    """Before the money a play that risks the stack needs the all-in or fold table to agree."""
    if not risks_the_stack(seen, play):
        return
    off = guard_is_off(seen, money, before)
    if off:
        play.guard, play.source = "off", f"GUARD OFF ({off})"
        return
    says = table_answer(seen, money, before)
    if says is None:
        play.source = "no table row for this spot: the engine decides alone"
        return
    if says.action not in ("FOLD", "CHECK"):
        play.guard, play.source = "agrees", "the all-in table agrees"
        return
    # The table folds: the headline is the fold, the engine's answer the second line.
    engine = engine_summary(play)
    free = seen.to_call <= 0
    play.also = f"The engine alone: {engine}. The Max EV style plays it."
    play.tiles = [t for t in play.tiles if t["label"] in ("All-in against folding", "Need / have")][:1]
    if play.tiles:
        play.tiles[0]["note"] = "the engine alone"
    play.tiles.append(tile("The table says", "CHECK" if free else "FOLD", says.short))
    play.verb, play.kind, play.to = ("CHECK", "check", None) if free else ("FOLD", "fold", None)
    play.qualifier, play.sure, play.guard = ("survival check" if free else "survival fold"), "standard", "survival"
    play.reason = f"Before the money the all-in table does not risk the stack here ({says.why})."
    play.flip = "The engine's play again once in the money, when the fold clock says you cannot fold, or with a read."
    play.plans = []
    play.source = f"SURVIVAL {'CHECK' if free else 'FOLD'} (engine: {engine})"
    play.chart = says.chart or play.chart


# ---- the all-in or fold tables ---------------------------------------------------------

@dataclass
class TableSays:
    """What the all-in or fold tables (or the sheet built on them) answer for a spot."""
    action: str                 # ALL-IN, CALL, FOLD or CHECK
    why: str                    # the reason, as a sentence without its capital
    short: str = ""             # the same in a few words, for a tile
    chart: dict | None = None
    sure: str = "standard"


def table_players(n: int) -> int:
    """The table size the all-in tables are read at: they exist for 6, 7 and 8 players."""
    return 8 if n >= 8 else 7 if n == 7 else 6


def seat_group(behind: int) -> str | None:
    """A seat's group in the sheet's tables for a player who raised first."""
    if behind >= 6:
        return "early"
    if behind >= 4:
        return "middle"
    if behind >= 2:
        return "late"
    return "sb" if behind == 1 else None


def table_answer(seen: Seen, money: Money, before: Before, bubble_charts: bool = False) -> TableSays | None:
    """The all-in or fold answer for a tournament spot, by the stage rules; ``None`` when no table has a row.

    Far from the money the tables are read as they are.  Close to it the
    column for twice the stack is read.  On the bubble calls come from the
    bubble table; with ``bubble_charts`` (the all-in plan) the first-in and
    raise spots come from the late-registration charts by the sit-out line.
    In the money the "money" tables apply, and at a final table a call
    against a player who covers hero comes from the bubble table again.
    """
    hero, hand, start = seen.hero, seen.hand_class, seen.start
    players = table_players(seen.n)
    behind = min(seen.behind(hero), players - 1)
    eff = seen.bbs(effective_stack(seen))
    stage = "money" if money.in_money else "before"
    column = eff * 2 if money.close else eff                # close to the money: the column for twice the stack
    twice = " (read at twice your stack this close to the money)" if money.close else ""
    if before.kind in ("shoved_on", "reraised", "called_then_raised", "wait"):
        return sheet_answer_after_hero_acted(seen, money, before, players, eff)
    # A raise of a third of the raiser's stack will not be folded: it is read as an all-in.
    all_ins = [r for r in before.raises if r.kind == "allin" or r.amount >= RAISE_IS_ALLIN * start[r.idx]]
    zone = sit_out_zone(seen, money) if bubble_charts and money.bubble else None
    if all_ins:
        if zone and zone[0] in ("safe", "close"):
            return TableSays("FOLD", f"with {percent(zone[1])} of the sit-out line you fold into the money: "
                                     "no calls", "fold into the money")
        # what hero has to match: the biggest all-in, or his own stack if that is smaller
        size = min(start[hero], max(start[r.idx] for r in all_ins)) / seen.bb
        covered = any(start[r.idx] >= start[hero] for r in all_ins)
        bubble = money.bubble or (money.final_table and covered)
        if len(all_ins) >= 2 or len(before.raises) + len(before.callers) >= 2:
            action, why = BN.decide(hand, behind, eff, stage, "allins", None, size, bubble, players)
            row, title = BN.call("two", size, bubble, behind == 0, players), "two all-ins"
        else:
            shover = seen.behind(all_ins[0].idx)
            action, why = BN.decide(hand, behind, eff, stage, "allin", shover, size, bubble, players)
            row = BN.call(BN.shover_kind(shover), size, bubble, behind == 0, players)
            title = f"an all-in from {seen.label(all_ins[0].idx)}"
        chart = range_chart(f"All-in table: calling {title}, {bb_number(size)}bb", seen.hand_name,
                            {"c": parse_range(row)}, legend=(("c", "Call"), ("f", "Fold")))
        why = why.replace(": ", " the table calls with ", 1)
        if money.final_table:                   # the bubble table again: a bust costs a pay jump
            why = why.replace("on the bubble", "at a final table against a player who covers you")
        return TableSays(action, why, row, chart)
    if len(before.raises) >= 2:
        return sheet_answer_two_raises(seen, before, players, eff)
    if before.raises:
        raiser = seen.behind(before.raises[0].idx)
        if zone:
            return bubble_chart_answer(seen, zone, players, "late" if raiser <= 3 else "early", behind)
        action, why = BN.decide(hand, behind, column, stage, "raise", raiser, None, False, players)
        row = BN.reshove(stage, BN.raiser_kind(raiser), column, players)
        chart = range_chart(f"All-in table: over a raise from {seen.label(before.raises[0].idx)}, "
                            f"{bb_number(column)}bb", seen.hand_name, {"r": parse_range(row)},
                            legend=(("r", "All-in"), ("f", "Fold")))
        return TableSays(action, why.replace(": ", " the table moves all-in with ", 1) + twice, row, chart)
    # Nobody has raised.  Behind callers the range of the seat before applies; the big blind reads the
    # small blind's range and checks with the rest (binary.decide would answer CHECK before reading any range).
    seat = behind
    if before.limpers:
        seat = 1 if behind == 0 else min(players - 1, behind + 1)
    if seat == 0:
        return TableSays("CHECK", "nobody raised: the big blind sees the flop for free", "a free flop")
    if zone:
        return bubble_chart_answer(seen, zone, players, "open", seat, free=behind == 0)
    action, why = BN.decide(hand, seat, column, stage, "", None, None, False, players)
    if behind == 0 and action != "ALL-IN":
        action = "CHECK"
    limit = BN.limit(stage, seat, hand, players) if column <= BN.TOP else 0
    sure = "clear" if abs(limit - column) >= 4 else "close" if abs(limit - column) < 1.5 else "standard"
    short = f"all-in up to {limit}bb" if limit else "never an all-in"
    if before.limpers:
        why = "behind callers the range of the seat before yours applies: " + why
    chart = first_in_table_chart(seen, stage, seat, column, players, bool(before.limpers))
    return TableSays(action, why + twice, short, chart, sure)


def first_in_table_chart(seen: Seen, stage: str, seat: int, column: float, players: int, callers: bool) -> dict:
    """The all-in table's first-in range for a seat and a stack; each cell knows its deepest stack."""
    weights = BN.first_in_range(stage, seat, column, players)
    limits = BN.limits(stage, seat, players)
    numbers = [f"all-in up to {limit}bb" if limit else "never an all-in" for limit in limits]
    title = f"All-in table: {SEAT_TITLES.get(BN.seat_name(seat, players), 'seat').lower()}, first in, {bb_number(column)}bb"
    if callers:
        title += " (behind callers: the seat before yours)"
    return range_chart(title, seen.hand_name, {"r": weights}, numbers, legend=(("r", "All-in"), ("f", "Fold")))


def sheet_answer_after_hero_acted(seen: Seen, money: Money | None, before: Before, players: int, eff: float):
    """Hero raised first and was re-raised or met an all-in: the rows of the tight-aggressive sheet."""
    if not before.hero_raise:
        return None                             # he only called: that is the sheet's own rule, handled elsewhere
    group = seat_group(seen.behind(seen.hero))
    sheet, hand = TAG.table(players), seen.hand_class
    if before.kind == "shoved_on":
        rows = sheet["shoved_on"].get(group)
        if rows is None:
            return None
        shover = before.raises[-1]
        size = min(seen.start[seen.hero], seen.start[shover.idx]) / seen.bb
        row = rows["bubble" if money is not None and money.bubble else "normal"][BN.band(size)]
        ok = in_range(row, hand)
        chart = range_chart(f"Sheet: calling an all-in of {bb_number(size)}bb over your raise", seen.hand_name,
                            {"c": parse_range(row)}, legend=(("c", "Call"), ("f", "Fold")))
        return TableSays("CALL" if ok else "FOLD", f"over your raise the sheet calls an all-in of this size with {row}",
                         row, chart)
    row = sheet["reraised"].get(group)
    if row is None:
        return None
    if eff <= 45:
        ok = in_range(row["allin"], hand)
        chart = range_chart("Sheet: you raised and were re-raised, 45bb or less", seen.hand_name,
                            {"r": parse_range(row["allin"])}, legend=(("r", "All-in"), ("f", "Fold")))
        return TableSays("ALL-IN" if ok else "FOLD", f"re-raised with 45bb or less the sheet moves all-in with "
                                                     f"{row['allin']}", row["allin"], chart)
    chart = range_chart("Sheet: you raised and were re-raised, more than 45bb", seen.hand_name,
                        {"r": parse_range(row["fourbet"]), "c": parse_range(row["call"])},
                        legend=(("r", "Re-raise"), ("c", "Call"), ("f", "Fold")))
    action = "ALL-IN" if in_range(row["fourbet"], hand) else "CALL" if in_range(row["call"], hand) else "FOLD"
    return TableSays(action, f"re-raised with more than 45bb the sheet re-raises {row['fourbet']} and calls "
                             f"{row['call']}", row["fourbet"], chart)


def sheet_answer_two_raises(seen: Seen, before: Before, players: int, eff: float):
    """A raise and a re-raise in front, nobody all-in: the sheet's row by the first raiser's seat."""
    group = seat_group(seen.behind(before.raises[0].idx))
    rows = TAG.table(players)["cold"].get("late" if group == "sb" else group)
    if rows is None:
        return None
    row = rows[0 if eff <= 24 else 1 if eff <= 60 else 2]
    chart = range_chart(f"Sheet: a raise and a re-raise before you, {bb_number(eff)}bb", seen.hand_name,
                        {"r": parse_range(row)}, legend=(("r", "All-in"), ("f", "Fold")))
    return TableSays("ALL-IN" if in_range(row, seen.hand_class) else "FOLD",
                     f"after a raise and a re-raise the sheet plays for stacks with {row} only", row, chart)


def table_limit_line(seen: Seen, money: Money, before: Before) -> str:
    """First in with a short stack: up to which stack the all-in table moves in with this hand."""
    if before.kind != "first_in" or seen.behind(seen.hero) == 0 or seen.bbs(effective_stack(seen)) > 20:
        return ""
    players = table_players(seen.n)
    seat = min(seen.behind(seen.hero), players - 1)
    limit = BN.limit("money" if money.in_money else "before", seat, seen.hand_class, players)
    where = BN.STAGE_NAMES["money" if money.in_money else "before"]
    if not limit:
        return f"The all-in table never moves in with {seen.hand_name} from this seat {where}."
    return f"The all-in table moves in with {seen.hand_name} up to {limit}bb from this seat {where}."


# ---- the bubble charts (late-registration plan) ---------------------------------------------

_SHEETS: dict = {}                              # table size -> the charts, once they are worked out
_SHEETS_BUSY: set = set()
_SHEETS_LOCK = threading.Lock()


def bubble_sheet(players: int, wait: bool = False):
    """The late-registration charts for a table size, or ``None`` while they are being worked out.

    They take 1.5 seconds for 8 players and about 15 for 6 or 7, once.  So the
    first time they are wanted a background thread works them out, and until
    it is done the caller reads the column for twice the stack instead.
    ``wait=True`` works them out here and now (tests, or a warm-up).
    """
    if players in _SHEETS:
        return _SHEETS[players]
    if wait:
        _SHEETS[players] = LR.build_sheet(players)
        return _SHEETS[players]
    with _SHEETS_LOCK:
        if players not in _SHEETS_BUSY:
            _SHEETS_BUSY.add(players)
            threading.Thread(target=bubble_sheet, args=(players, True), daemon=True).start()
    return None


def warm_bubble_charts(players: int = 8) -> None:
    """Work the bubble charts out now, so the first bubble spot of the all-in plan does not wait for them."""
    bubble_sheet(table_players(players), wait=True)


def sit_out_zone(seen: Seen, money: Money) -> tuple | None:
    """(zone name, hero's share of the sit-out line), or ``None`` when the bubble charts cannot be used yet."""
    remaining, paid = money.stage.get("remaining"), money.stage.get("paid")
    average = average_stack(seen.data) or S.avg_stack(money.state)      # not typed: this table's average
    if not (remaining and paid and average) or remaining <= paid:
        return None
    if bubble_sheet(table_players(seen.n)) is None:
        return None
    name, cover, _text = LR.zone(seen.start[seen.hero], average, remaining, paid)
    return name, cover


def bubble_chart_answer(seen: Seen, zone: tuple, players: int, kind: str, seat: int, free: bool = False) -> TableSays:
    """On the bubble in the all-in plan: sit out, aces only, the tight chart or the wide one, by the sit-out line."""
    name, cover = zone
    sheet = bubble_sheet(players)
    chart_name = sheet.pick(cover, seen.bbs(seen.start[seen.hero]))
    out = "CHECK" if free else "FOLD"
    if chart_name is None:
        return TableSays(out, f"sit out: the stack is {percent(cover)} of the sit-out line and lasts until the money",
                         "sit out")
    weights = sheet.weights(chart_name, kind, seat if kind == "open" else 2)
    words = {"wide": "the wide chart", "short": "the short-stack chart", "tight": "the tight chart",
             "aces": "aces only", "premium": "QQ+ and AK only"}[chart_name]
    row = format_range(weights) or "nothing"
    spot = "first in" if kind == "open" else "over a raise"
    chart = range_chart(f"Bubble, {words}: {spot}", seen.hand_name, {"r": weights},
                        legend=(("r", "All-in"), ("f", "Fold")))
    action = "ALL-IN" if weights[seen.hand_class] >= 0.5 else out
    return TableSays(action, f"on the bubble with {percent(cover)} of the sit-out line {words} applies {spot}: {row}",
                     words, chart)


# ==========================================================================
# 6. Tournament, all-in or fold plan
# ==========================================================================

def allin_plan_play(seen: Seen, money: Money) -> Play:
    """One decision a hand, from the tables; the full engine on the real stacks is the second line."""
    before = what_happened(seen)
    if before.kind == "called_then_raised" and before.raises[-1].kind != "allin":
        return called_then_raised(seen, before)
    spot = engine_spot(seen, money.prizes, money.field_prizes, money.stage, money.desperate)
    engine = play_from_engine(seen, engine_advise(spot), value_note(money))
    says = table_answer(seen, money, before, bubble_charts=True)
    if says is None:
        # no row (hero called and then met an all-in, or a seat the sheet does not cover): the engine answers
        engine.source = "no table row for this spot: the engine decides"
        engine.chart = None
        engine.warnings.append(outside_tables("The all-in or fold tables have no row for this spot: "
                                              "this is the full engine's answer."))
        return engine
    kind = {"ALL-IN": "allin", "CALL": "call", "CHECK": "check"}.get(says.action, "fold")
    play = Play(verb=says.action, kind=kind, sure=says.sure, reason=sentence(says.why), chart=says.chart,
                source="all-in or fold table", also=f"The full engine on these stacks: {engine_summary(engine)}.")
    if says.short and before.kind in ("first_in", "limped"):
        play.tiles.append(tile("The table", says.short, f"{seen.hand_name} from this seat"))
    for number in engine.tiles:
        if number["label"] in ("All-in against folding", "Need / have"):
            number["note"] = "the full engine, " + value_note(money)
            play.tiles.append(number)
            break
    eff_bb = seen.bbs(effective_stack(seen))
    if seen.n >= 9:
        play.warnings.append(outside_tables("Nine players: answered from the table for eight."))
    if eff_bb > BN.TOP:
        play.warnings.append(outside_tables(f"Over {BN.TOP}bb the all-in plan only plays aces and kings."))
    if money.bubble and sit_out_zone(seen, money) is None and before.kind in ("first_in", "limped", "raise"):
        if (money.stage.get("remaining") or 0) > (money.stage.get("paid") or 0):
            play.warnings.append(warning("charts_loading", "The bubble charts are still being worked out: this "
                                         "answer reads the column for twice your stack.", "bubble charts loading"))
    return play


def outside_tables(text: str) -> dict:
    return warning("outside_tables", text, "outside the tables")


# ==========================================================================
# 7. Spin: three players, one prize
# ==========================================================================

def spin_play(seen: Seen) -> Play:
    """Chips are money: the solved all-in or fold tables when short, the engine on chip EV when deep."""
    if seen.n not in (2, 3):
        raise ValueError("the spin tables are for 2 or 3 players")
    before = what_happened(seen)
    eff = spin_effective_bb(seen, before)
    row = spin_row(seen, before)
    seat = seen.label(seen.hero)
    first_in = row in ("btn", "sb", "hu_sb")
    late = seen.n == 2 or seat == "SB"
    table_top = SPIN_TABLE_BB_LATE if late else SPIN_TABLE_BB
    if row is None or (first_in and eff > table_top):
        play = spin_engine_play(seen)
        if row is None:
            play.source = "chip-EV engine: the spin tables have no row for this spot"
            play.warnings.append(outside_tables("The spin tables have no row for this spot: answered by the "
                                                "engine on chip EV."))
        else:
            edge = SP.edge(row, eff, seen.hand_class)
            play.source = f"chip-EV engine: over {table_top}bb a small raise beats all-in or fold"
            play.also = f"All-in instead: {signed_bb(edge)} against folding (the spin table)."
        return play
    vs = callers_profile(seen) if first_in else "solid"     # only the first-in ranges change for loose callers
    action, _why = SP.decide(seen.hand_class, row, eff, vs)
    if row in SP.OPENERS and action in ("FOLD", "CHECK") and seat == "BB" and eff > SPIN_TABLE_BB:
        engine = spin_engine_play(seen)                     # deep in the big blind a call may be right
        if engine.kind == "call":
            engine.source = "chip-EV engine: the table folds, the price allows a call"
            return engine
    play = spin_table_play(seen, row, eff, vs, action)
    if len({round(s, 2) for s in seen.start}) > 1:
        play.warnings.append(outside_tables(f"Stacks differ: answered for the effective stack "
                                            f"({bb_number(eff)}bb), an approximation."))
    return play


def spin_effective_bb(seen: Seen, before: Before) -> float:
    """The effective stack in big blinds; against all-ins, their size or hero's stack if smaller."""
    start, hero = seen.start, seen.hero
    all_ins = [r for r in before.raises if r.kind == "allin" or r.amount >= RAISE_IS_ALLIN * start[r.idx]]
    if all_ins:
        return min(start[hero], max(min(r.amount, start[r.idx]) for r in all_ins)) / seen.bb
    return effective_stack(seen) / seen.bb


def spin_row(seen: Seen, before: Before) -> str | None:
    """The row of the spin tables for this spot, or ``None`` when they have none.

    Three players sit BTN, SB, BB; heads-up the button is the small blind.
    """
    if before.hero_raise or before.hero_called:
        return None                             # hero acts a second time: no table
    seats = ["BTN", "SB", "BB"] if seen.n == 3 else ["SB", "BB"]
    me = seats[seen.hero]
    start = seen.start
    all_ins = [r for r in before.raises if r.kind == "allin" or r.amount >= RAISE_IS_ALLIN * start[r.idx]]
    small = [r for r in before.raises if r not in all_ins]
    all_in_seats = tuple(seats[r.idx] for r in all_ins)
    if not before.raises and not before.limpers:
        return {"BTN": "btn", "SB": "sb" if seen.n == 3 else "hu_sb"}.get(me)
    if all_ins and not small and not before.limpers and not before.callers:
        if seen.n == 2:
            return "hu_bb"
        return {("SB", ("BTN",)): "sb_vs_btn", ("BB", ("BTN",)): "bb_vs_btn", ("BB", ("SB",)): "bb_vs_sb",
                ("BB", ("BTN", "SB")): "bb_vs_both"}.get((me, all_in_seats))
    if len(small) == 1 and not all_ins and not before.limpers and not before.callers:
        if seen.n == 2:
            return "hu_bb_vs_raise"
        return {("SB", "BTN"): "sb_vs_btn_raise", ("BB", "BTN"): "bb_vs_btn_raise",
                ("BB", "SB"): "bb_vs_sb_raise"}.get((me, seats[small[0].idx]))
    if not before.raises and len(before.limpers) == 1 and seats[before.limpers[0]] == "SB" and me == "BB":
        return "bb_vs_sb_limp" if seen.n == 3 else "hu_bb_vs_limp"
    return None


def callers_profile(seen: Seen) -> str:
    """Solid, loose or very-loose, for the Spin and All-In or Fold tables.

    The loose tables assume every opponent calls too much, so they are used
    only when every player still to act does: by his own tag, else by the
    table-wide setting.
    """
    setting = seen.data["config"].get("opponents")
    profiles = []
    for index in range(seen.hero + 1, seen.n):
        tag = seen.tags[index]
        if tag == "unknown":
            profiles.append(setting if setting in ("loose", "very-loose") else "solid")
        else:
            profiles.append("loose" if tag in ("loose", "station", "maniac") else "solid")
    if not profiles or "solid" in profiles:
        return "solid"
    return "very-loose" if all(p == "very-loose" for p in profiles) else "loose"


def spin_engine_play(seen: Seen) -> Play:
    """The tight-aggressive engine on chip EV: one prize means a chip won is worth a chip lost."""
    before = what_happened(seen)
    spot = engine_spot(seen, Prizes(), Prizes(), {}, False)
    adv = engine_advise(spot)
    play = play_from_engine(seen, adv, "chip EV")
    play.chart = hero_cell_as_played(engine_chart(seen, spot, adv, before), seen.hand_class, play.kind)
    if adv.confidence == "close":
        play.warnings.append(close_warning(engine_facts(adv), before, None, play.kind))
    return play


def spin_table_play(seen: Seen, row: str, eff: float, vs: str, action: str) -> Play:
    """An answer of the spin tables, with the numbers behind it."""
    hand, name = seen.hand_class, seen.hand_name
    kind = {"ALL-IN": "allin", "CALL": "call", "CHECK": "check"}.get(action, "fold")
    play = Play(verb=action, kind=kind, source="spin table: chip EV, no ICM, no guard")
    if row in SP.AS_ALLIN and eff <= SP.COMMITTED_BB:
        row = SP.AS_ALLIN[row]                  # a raise from a stack this short is an all-in
    if row in SP.SPOTS:
        edge = SP.edge(row, eff, hand, vs)
        width = SP.width(row, eff, vs)
        label = SP.SPOTS[row][2]
        calling = SP.SPOTS[row][3] == "call"
        play.sure = "clear" if abs(edge) >= 0.25 else "close" if abs(edge) < 0.05 else "standard"
        inside = "inside" if action in ("ALL-IN", "CALL") else "outside"
        play.reason = sentence(f"One prize, so chips are money: {name} is {inside} the {percent(width / 100)} of hands "
                               f"that {'call' if calling else 'move all-in'} here ({label}, {bb_number(eff)}bb)")
        profile = {"loose": "loose", "very-loose": "vloose"}.get(vs, "solid")
        note = "close to a coin flip: either play is fine" if abs(edge) < 0.05 else "against " + SP.PROFILE_NAMES[profile]
        play.tiles = [tile(("Calling" if calling else "All-in") + " against folding", signed_bb(edge), note, sign_of(edge)),
                      tile("This seat plays", percent(width / 100), f"table read at {SP.nearest(eff)}bb")]
        if not calling and vs == "solid":
            loose = SP.decide(hand, row, eff, "loose")[0]
            if loose != action:
                play.flip = f"Against players who call too much: {loose}."
        play.chart = spin_chart(seen, row, eff, vs)
        return play
    text = SP.raise_rows()[row][SP.band(eff)]
    label, band = SP.OPENERS[row][5], SP.BANDS[SP.band(eff)][0]
    inside = "is" if action == "ALL-IN" else "is not"
    play.reason = sentence(f"{label}, {band}: {name} {inside} one of the hands that move all-in over it")
    play.tiles = [tile("All-in range here", f"{share_of_hands(parse_range(text))}%", f"{band}, against a wide opener")]
    play.flip = "Against a player who only raises strong hands, use the all-in rows instead."
    play.chart = range_chart(f"Spin: {label}, {band}", name, {"r": parse_range(text)},
                             legend=(("r", "All-in"), ("f", "Check" if action == "CHECK" else "Fold")))
    return play


def spin_chart(seen: Seen, row: str, eff: float, vs: str) -> dict:
    """A solved row as a chart: the range, with the hands worth about nothing drawn as close."""
    weights = SP.play(row, eff, vs)
    edges = [SP.edge(row, eff, hand, vs) for hand in range(169)]
    calling = SP.SPOTS[row][3] == "call"
    code = "c" if calling else "r"
    played = [w if abs(e) >= EV_CLOSE_BB else 0.0 for w, e in zip(weights, edges)]
    close = [1.0 if abs(e) < EV_CLOSE_BB else 0.0 for e in edges]
    chart = range_chart(f"Spin: {SP.SPOTS[row][2]}, {bb_number(eff)}bb", seen.hand_name,
                        {code: played, "x": close}, [signed_bb(e) for e in edges],
                        legend=((code, "Call" if calling else "All-in"), ("x", "Close"), ("f", "Fold")))
    chart["share"] = share_of_hands(weights)
    return chart


# ==========================================================================
# 8. All-In or Fold
# ==========================================================================

def aof_play(seen: Seen) -> Play:
    """GGPoker All-In or Fold: the solved table for the seat and for who has already moved in."""
    n, hero = seen.n, seen.hero
    mask = 0
    for act in seen.acts:                       # every action that is not a fold is an all-in here
        if act.idx < hero:
            mask |= 1 << act.idx
    family = AOF.family_for("cash", callers_profile(seen))
    answer = AOF.decide(seen.hand_class, n, hero, mask, list(seen.start), family)
    calling = mask != 0
    moves_in = answer.action == "ALL-IN"
    verb = ("CALL" if calling else "ALL-IN") if moves_in else "FOLD"
    close = abs(answer.ev) < AOF.CLOSE_EV
    seat_plays = "calls" if calling else "moves all-in"
    play = Play(verb=verb, kind="allin" if moves_in else "fold", sure=answer.confidence,
                source="All-In or Fold table: " + AOF.FAMILY_LABEL.get(answer.family, answer.family))
    play.reason = sentence(f"{answer.hand} is {'inside' if moves_in else 'outside'} the {answer.range_pct:.0f}% of hands "
                           f"this seat {seat_plays} with at {bb_number(answer.stack)}bb effective")
    play.tiles = [tile(("Calling" if calling else "All-in") + " against folding", signed_bb(answer.ev),
                       "a coin flip: either play is fine" if close else "the 0.1bb fee is counted", sign_of(answer.ev)),
                  tile("This seat plays", f"{answer.range_pct:.0f}%", f"{bb_number(answer.stack)}bb effective")]
    if close:
        play.flip = "Under 0.05bb the two plays are worth the same."
    for note in answer.notes:
        if note.startswith("stacks differ") or "outside the solved range" in note:
            play.warnings.append(outside_tables(sentence(note)))
        else:
            play.warnings.append(warning("engine", sentence(note)))
    weights, evs, used = AOF.node_range(answer.family, n, hero, mask, answer.stack)
    code = "c" if calling else "r"
    play.chart = range_chart(f"All-In or Fold: {AOF.describe_point(n, hero, mask)}, {bb_number(used)}bb", answer.hand,
                             {code: [1.0 if w >= 1.0 else 0.0 for w in weights],
                              "x": [1.0 if w == 0.5 else 0.0 for w in weights]},
                             [signed_bb(e) for e in evs],
                             legend=((code, "Call" if calling else "All-in"), ("x", "Close"), ("f", "Fold")))
    play.chart["share"] = round(answer.range_pct)
    return play


# ==========================================================================
# 9. After the flop
# ==========================================================================

STREET_CARDS = {"flop": 3, "turn": 4, "river": 5}
ACTION_WEIGHT = {"check": 0, "call": 1, "bet": 2, "raise": 3, "shove": 4}


def after_the_flop(seen: Seen, money: Money | None) -> Play:
    """Equity against each opponent's range, narrowed by what he did; then the playbook's one-pair check."""
    if seen.cards is None:
        raise ValueError("after the flop the exact cards are needed")
    state = seen.state
    board = parse_cards("".join(seen.hand["board"]))[:STREET_CARDS[state.phase]]
    opponents = [seat for seat in state.live() if seat != HERO]
    if not opponents:
        raise ValueError("nobody else is in the hand")
    roles, opener_behind, last_raiser = preflop_roles(seen)
    lines, aggressor = street_lines(seen)
    main = main_opponent(seen, opponents, aggressor)
    villains, unknown = [], False
    for seat in [main] + [s for s in opponents if s != main]:
        index = seen.order.index(seat)
        role = roles.get(seat)
        if role is None:                        # nothing recorded for him before the flop: read as a caller
            role, unknown = "call", True
        weights, did = range_for(role, seen.behind(index), opener_behind, seen.types[index])
        villains.append(Villain(weights, seen.types[index], lines.get(seat, []), f"{seen.who(index)}: {did}"))
    # After the flop the small blind acts first and the button last: hero is in position when he acts after everybody.
    rank = {seat: k for k, seat in enumerate(postflop_order(seen.order))}
    in_position = all(rank[HERO] > rank[seat] for seat in opponents)
    to_call = seen.to_call
    # The pot hero plays for: chips in front of a player beyond what hero can match are not his to win.
    reach = state.in_front[HERO] + to_call
    pot = state.pot_total() - sum(max(0, state.in_front[s] - reach) for s in state.order if s != HERO)
    facing = None
    if to_call > 0:
        main_line = [e for e in lines.get(main, []) if e[0] == state.phase]
        if state.stack[main] <= 0:
            facing = "shove"
        elif state.in_front[HERO] > 0 or (main_line and main_line[-1][1] == "raise"):
            facing = "raise"                    # hero bet and was raised, or a bet was raised in front of him
    risk = 0.0
    if money is not None and not money.prizes.chip_ev:
        risk = money.prizes.risk_premium(seen.start, seen.hero, seen.order.index(main))
    spot = PostflopSpot(hero=seen.cards, board=board, pot=pot, to_call=to_call, hero_stack=state.stack[HERO],
                        villain_stack=state.stack[main], villains=villains, in_position=in_position,
                        hero_pfr=last_raiser == HERO, facing=facing, bb=seen.bb, risk_premium=risk,
                        iters=POSTFLOP_ITERS)
    adv = advise_postflop(spot)
    made = describe(seen.cards, board)          # what hero holds: top pair, a flush draw, the outs
    play = play_after_flop(seen, adv, made, len(board))
    play.source = "after the flop: equity against an estimated range, a rule-based line"
    if unknown:
        play.warnings.append(warning("preflop_unknown", "No action is recorded for an opponent before the flop: "
                                     "he is read as a caller.", "an opponent read as a caller"))
    main_type = seen.types[seen.order.index(main)]
    bet_share = to_call / max(pot - to_call, 1e-9) if to_call > 0 else 0.0
    playbook_check(play, adv, made, state.phase, facing, bet_share, main_type, seen.who(seen.order.index(main)))
    if seen.mode == "tournament" and seen.data["config"].get("plan") == "allin":
        return free_flop_rule(seen, play, made, pot)
    return play


def preflop_roles(seen: Seen) -> tuple[dict, int | None, int | None]:
    """How each player entered the pot: ({seat: role}, players behind the first raiser, the last raiser's seat).

    Roles: open (the first raise), 3bet (a re-raise), 4bet (a further re-raise), call (called a raise),
    limp (called the big blind), check (the big blind saw a free flop).  A player who raised and then
    called a re-raise stays a raiser; one who limped and then called a raise stays a limper.
    """
    roles: dict = {}
    raisers: list = []
    for entry in seen.state.log:
        if entry["street"] != "preflop":
            continue
        seat, kind = entry["seat"], entry["kind"]
        if kind in ("bet", "raise"):
            raisers.append(seat)
            roles[seat] = ("open", "3bet", "4bet")[min(len(raisers), 3) - 1]
        elif kind == "call":
            roles.setdefault(seat, "call" if raisers else "limp")
        elif kind == "check":
            roles.setdefault(seat, "check")
    for seat in seen.order[-2:]:                # a blind that went all-in by posting holds any two cards
        if seat not in roles and seen.state.stack[seat] <= 0 and seat not in seen.state.folded:
            roles[seat] = "check"
    opener_behind = seen.behind(seen.order.index(raisers[0])) if raisers else None
    return roles, opener_behind, (raisers[-1] if raisers else None)


def range_for(role: str, behind: int, opener_behind: int | None, ptype: str) -> tuple[list, str]:
    """An opponent's range from what he did before the flop, and a word for it."""
    opener = max(1, 3 if opener_behind is None else opener_behind)
    if role == "open":
        return villain_open_range(behind, ptype), "raised first"
    if role == "3bet":
        return threebet_range(opener, ptype), "re-raised"
    if role == "4bet":
        return threebet_range(opener, "nit"), "re-raised again"     # a second re-raise: the top of that range
    if role == "limp":
        return villain_limp_range(behind, ptype), "called the big blind"
    if role == "check":
        return [1.0] * 169, "any two cards"
    # He called a raise: the call, set-mine and deep rows of the chart, and now and then a slow-played big hand.
    chart = vs_open_chart(opener, behind)
    weights = [max(c, s, d) for c, s, d in zip(chart["call"], chart["setmine"], chart["deep"])]
    weights = [max(w, 0.25 * v) for w, v in zip(weights, chart["value"])]
    if range_pct(weights) < 6.0:                # the chart re-raises or folds from that seat; people still call
        position = vs_open_chart(opener, 2)
        weights = [max(w, c, s, d) for w, c, s, d in zip(weights, position["call"], position["setmine"], position["deep"])]
    if norm_type(ptype) in LOOSE_TYPES:         # tables that call too much call with far more
        extra = top_percent(35.0 if behind == 0 else 25.0, list(play_order()))
        weights = [max(w, 0.7 * e) for w, e in zip(weights, extra)]
    return weights, "called a raise"


def street_lines(seen: Seen) -> tuple[dict, int | None]:
    """What every opponent did on each street after the flop, and who bet or raised last in the hand.

    ``{seat: [(street, action, size)]}`` with the strongest action of each
    street: check, call, bet, raise or shove.  A bet's size is the chips put
    in over the pot before it; a call carries the size of the bet it called.
    The street being played is included, so the engine adds nothing itself.
    """
    state = seen.state
    pot = sum(state.ante.values()) + state.dead + sum(state.blind.values())
    front = dict(state.blind)                   # chips in front of each player on the street being walked
    street, standing = "preflop", None          # ``standing``: the size of the bet that is there to be called
    lines: dict = {}
    aggressor = None
    for entry in state.log:
        if entry["street"] != street:
            pot -= uncalled(front)              # the part of a bet nobody matched went back
            front = dict.fromkeys(front, 0)
            street, standing = entry["street"], None
        seat, kind = entry["seat"], entry["kind"]
        added = entry["to"] - front[seat]
        size = None
        if kind in ("bet", "raise"):
            size = added / pot if pot > 0 else None
            standing = size
            aggressor = seat
            action = "shove" if entry["allin"] else kind
        elif kind == "call":
            action, size = "call", standing
        else:
            action = kind                       # check or fold
        pot += added
        front[seat] = entry["to"]
        if street == "preflop" or seat == HERO or action == "fold":
            continue
        line = lines.setdefault(seat, [])
        if line and line[-1][0] == street:
            if ACTION_WEIGHT[action] > ACTION_WEIGHT[line[-1][1]]:
                line[-1] = (street, action, size)
        else:
            line.append((street, action, size))
    return lines, aggressor


def uncalled(front: dict) -> float:
    """The part of the biggest bet of a street that nobody matched."""
    amounts = sorted(front.values(), reverse=True)
    return amounts[0] - amounts[1] if len(amounts) >= 2 else 0


def main_opponent(seen: Seen, opponents: list, aggressor: int | None) -> int:
    """The player the decision is about: whose bet hero faces, else the last to bet or raise, else the biggest stack."""
    state = seen.state
    if seen.to_call > 0:
        return max(opponents, key=lambda seat: (state.in_front[seat], seat == aggressor))
    if aggressor in opponents:
        return aggressor
    return max(opponents, key=lambda seat: state.stack[seat])


def read_postflop_action(action: str, bb: float) -> tuple[str, str, float | None, str]:
    """A postflop action of the engine as (verb, kind, chips hero puts in now, qualifier).

    The engine says: FOLD, CHECK, CALL, RAISE to 5,400 (9.0bb, 120% pot), RAISE ALL-IN (semi-bluff),
    BET 990 (1.6bb, 33% pot) (c-bet), BET ALL-IN; with big blinds as the unit, BET 1.7bb (33% pot).
    """
    text = action.strip()
    note = re.search(r"\((semi-bluff|c-bet)\)\s*$", text)
    qualifier = note.group(1) if note else ""
    for word, kind in (("FOLD", "fold"), ("CHECK", "check"), ("CALL", "call")):
        if text.startswith(word):
            return word, kind, None, ""
    if "ALL-IN" in text:
        return "ALL-IN", "allin", None, qualifier
    size = re.match(r"(BET|RAISE to) ([\d,]+(?:\.\d+)?)(bb)?", text)
    if size is None:
        raise ValueError(f"cannot read the engine's action {action!r}")
    chips = float(size.group(2).replace(",", "")) * (bb if size.group(3) else 1.0)
    return ("BET", "bet", chips, qualifier) if size.group(1) == "BET" else ("RAISE", "raise", chips, qualifier)


def play_after_flop(seen: Seen, adv, made: dict, board_cards: int) -> Play:
    verb, kind, chips, qualifier = read_postflop_action(adv.action, seen.bb)
    # the engine's amount is what hero puts in now; the table wants his total in front on this street
    to = seen.state.in_front[HERO] + chips if chips is not None else None
    play = Play(verb=verb, kind=kind, to=to, qualifier=qualifier, sure=adv.confidence,
                reason=sentence(plain(adv.why[0])) if adv.why else "",
                also=sentence(plain(adv.alt[0])) if adv.alt else "")
    equity = adv.data.get("equity")
    if equity is not None:
        play.tiles.append(tile("Equity", percent(equity), "against their range after this line"))
    price = re.search(r"need (\d+)%, have (\d+)%", " | ".join(adv.numbers))
    if price:
        play.tiles.append(tile("Need / have", f"{price.group(1)}% / {price.group(2)}%", "the price, safety and ICM counted"))
    if made["draws"] and board_cards < 5:
        play.tiles.append(tile("Outs", str(made["outs"]), ", ".join(made["draws"])))
    else:
        play.tiles.append(tile("You hold", made["made"].split(" (")[0], made["texture"]["label"]))
    play.tiles = play.tiles[:3]
    for text in adv.warnings:
        play.warnings.append(warning("engine", sentence(plain(text))))
    if adv.confidence == "close":
        text = f"Close: you need {price.group(1)}% and have {price.group(2)}%." if price else \
            "Close: the other play is nearly as good."
        play.warnings.append(warning("close", text, "close"))
    return play


def playbook_check(play: Play, adv, made: dict, street: str, facing, bet_share: float, ptype: str, who: str) -> None:
    """The playbook's one-pair rule, the only override after the flop.

    One pair facing a big river bet, or a raise on the turn or the river, from
    a player who rarely bluffs (nit, tight, loose, station): fold, unless
    fewer than 1.5 pots are behind.  The engine calls there.
    """
    one_pair = made["category"] == "pair" or "paired board" in made["made"]
    big_river_bet = street == "river" and bet_share >= PLAYBOOK_BIG_BET
    raised = street in ("turn", "river") and facing in ("raise", "shove")
    deep_enough = adv.data.get("spr", 0) >= PLAYBOOK_POTS_BEHIND
    if play.kind != "call" or not one_pair or not (big_river_bet or raised) or ptype not in PASSIVE_TYPES \
            or not deep_enough:
        return
    engine = engine_summary(play)
    what = "a raise" if raised else "a big river bet"
    play.verb, play.kind, play.to = "FOLD", "fold", None
    play.qualifier, play.sure = "playbook check", "standard"
    play.reason = sentence(f"One pair facing {what} from {who}, tagged {ptype}: such players rarely bluff there, "
                           "so the playbook folds")
    play.also = f"The engine alone: {engine}."
    play.flip = "A call against an aggressive player, or with less than 1.5 pots behind."


def free_flop_rule(seen: Seen, engine: Play, made: dict, pot: float) -> Play:
    """The all-in plan after a free flop: all-in with top pair or better, or 12 outs, at 4 pots or less."""
    behind = seen.state.stack[HERO]
    strong = made["strength"] >= 4 or (made["outs"] >= 12 and seen.state.phase != "river")
    second = f"The full engine: {engine.verb}."
    if strong and behind <= 4 * pot:
        return Play(verb="ALL-IN", kind="allin", sure="standard", also=second, source="all-in plan: the playbook's rule",
                    reason="Top pair or better, or a draw with 12 outs, and 4 pots or less behind: move all-in.",
                    tiles=[tile("You hold", made["made"].split(" (")[0], made["texture"]["label"]),
                           tile("Pots behind", f"{behind / pot:.1f}", "all-in at 4 or less")])
    verb, kind = ("CHECK", "check") if seen.to_call <= 0 else ("FOLD", "fold")
    return Play(verb=verb, kind=kind, sure="standard", also=second, source="all-in plan: the playbook's rule",
                reason="No top pair and no 12-out draw (or more than 4 pots behind): check, and fold to a bet.",
                tiles=[tile("You hold", made["made"].split(" (")[0], made["texture"]["label"])])


# ==========================================================================
# 10. The charts
# ==========================================================================

def range_chart(title: str, hero: str, ranges: dict, numbers: list | None = None, legend=()) -> dict:
    """A 13 x 13 chart: rows and columns run from A to 2, suited hands above the diagonal.

    ``ranges`` maps a code (r raise or all-in, c call, x close or mixed) to
    169 weights; a hand takes the first code whose range holds it, else f.
    ``numbers`` are 169 short strings for the cells, or ``None``.
    """
    codes = []
    for hand in range(169):
        codes.append(next((code for code, weights in ranges.items() if weights[hand] >= 0.5), "f"))
    played = [1.0 if code in ("r", "c") else 0.0 for code in codes]
    return {"title": title, "share": share_of_hands(played), "hero": hero,
            "cells": [codes[row * 13:row * 13 + 13] for row in range(13)],
            "numbers": [list(numbers[row * 13:row * 13 + 13]) for row in range(13)] if numbers else None,
            "legend": [{"code": code, "label": label} for code, label in legend]}


def ev_chart(title: str, hero: str, evs: list, needed: float) -> dict:
    """A chart of all-ins by their value: all-in above what is needed, close within 0.05bb of it."""
    moves = [1.0 if ev > needed + EV_CLOSE_BB else 0.0 for ev in evs]
    close = [1.0 if abs(ev - needed) <= EV_CLOSE_BB else 0.0 for ev in evs]
    chart = range_chart(title, hero, {"r": moves, "x": close}, [signed_bb(ev) for ev in evs],
                        legend=(("r", "All-in"), ("x", "Close"), ("f", "Fold")))
    chart["share"] = share_of_hands([1.0 if ev > needed else 0.0 for ev in evs])
    return chart


def engine_chart(seen: Seen, spot: Spot, adv, before: Before) -> dict | None:
    """The chart behind an engine answer.  A chart that cannot be drawn is left out: it never costs the answer.

    Where the engine works from a calculation (a solver, equities, its own
    charts) the chart is that calculation.  For the other spots the row of
    the tournament sheet is drawn, which a Spin does not use.
    """
    try:
        if "need" in adv.data:
            return call_chart(seen, adv)
        if "reshove_ev_bb" in adv.data:
            return reshove_chart(seen, spot, adv, before)
        if before.kind == "first_in":
            return first_in_chart(seen, spot, adv)
        if before.kind == "raise":
            return reraise_chart(seen, before)
        if seen.mode != "tournament":
            return None
        if before.kind == "limped":
            return limped_chart(seen, before)
        if before.kind in ("allins", "raise_allin"):
            size = min(seen.start[seen.hero], max(seen.start[r.idx] for r in before.raises)) / seen.bb
            row = BN.call("two", size, False, seen.behind(seen.hero) == 0, table_players(seen.n))
            return range_chart(f"All-in table: calling two all-ins, {bb_number(size)}bb", seen.hand_name,
                               {"c": parse_range(row)}, legend=(("c", "Call"), ("f", "Fold")))
        says = None
        if before.kind == "raise_reraise":
            says = sheet_answer_two_raises(seen, before, table_players(seen.n), seen.bbs(effective_stack(seen)))
        elif before.kind == "reraised":
            says = sheet_answer_after_hero_acted(seen, None, before, table_players(seen.n),
                                                 seen.bbs(effective_stack(seen)))
        return says.chart if says else None
    except Exception:
        return None


def hero_cell_as_played(chart: dict | None, hand: int, kind: str) -> dict | None:
    """Hero's own cell shows what the engine does with the hand.

    The chart is drawn from the range behind the answer; the engine has a few
    rules on top of it (a big blind that calls at a good price, a hand that
    moves all-in instead of raising).  Where the two differ for hero's hand,
    the cell follows the engine.
    """
    if chart is None:
        return None
    row, column = divmod(hand, 13)
    cell = chart["cells"][row][column]
    if kind == "call" and cell != "c":
        cell = "c"
        if not any(item["code"] == "c" for item in chart["legend"]):
            chart["legend"].insert(-1, {"code": "c", "label": "Call"})
    elif kind in ("raise", "allin") and cell == "f":
        cell = "r"
    elif kind in ("fold", "check") and cell in ("r", "c"):
        cell = "x"
    chart["cells"][row][column] = cell
    return chart


def chart_rounds(callers: int) -> int:
    """Rounds of the solver for a chart: 36 with one player who can call, 24 with two, 12 from the early seats.

    The engine itself runs 40, and its time grows with the players who can
    call.  A chart is a picture of the range, so it is drawn with fewer rounds
    to stay quick (a hand worth about nothing may then land on the wrong side
    of "close"); hero's own cell always carries the engine's number.
    """
    return max(12, min(40, CHART_SOLVER_WORK // (callers + 1)))


def first_in_chart(seen: Seen, spot: Spot, adv) -> dict | None:
    """First in: the solver's all-ins with their value when short, the opening range when deeper."""
    setup, hero = spot.setup, spot.hero
    live = setup.live
    behind = [j for j in range(hero + 1, setup.n) if not spot.away[j] and live[j] > 0]
    if not behind:
        return None
    eff = min(live[hero], max(live[j] for j in behind)) / setup.bb
    heads_up, small_blind = setup.n == 2, spot.nb(hero) == 1
    seat = SEAT_TITLES.get(seen.label(hero), seen.label(hero))
    if eff <= (20 if heads_up or small_blind else 16):
        # the engine's own call: all-in or fold by the solver, with hero's prize model
        prizes = Prizes() if spot.desperate else spot.prizes
        solution = solve_open_shove(setup, hero, prizes, caller_prizes=spot.field_prizes, types=spot.types,
                                    away=spot.away, iters=chart_rounds(len(behind)))
        evs = [solution.ev_bb(hand) for hand in range(169)]
        evs[seen.hand_class] = adv.data.get("shove_ev_bb", evs[seen.hand_class])     # hero's cell: the engine's number
        return ev_chart(f"{seat}, first in, {bb_number(eff)}bb: all-in or fold", seen.hand_name, evs,
                        0.0 if eff <= 10 else 0.05)
    if heads_up:
        opens = wider = parse("80%")
    else:
        shift = _chart_shift(spot, behind)[0]   # notches tighter or looser for ICM and for who sits behind
        opens = rfi_range(len(behind), eff, shift)
        wider = rfi_range(len(behind), eff, shift - 1)
    return range_chart(f"{seat}, first in, {bb_number(eff)}bb", seen.hand_name, {"r": opens, "x": wider},
                       legend=(("r", "Raise"), ("x", "Close"), ("f", "Fold")))


def call_chart(seen: Seen, adv) -> dict | None:
    """Facing an all-in: every hand's equity against the range the engine modelled, against what is needed."""
    found = re.search(r"their range ~[\d.]+% \[(.*?)\]", " | ".join(adv.numbers))
    if not found:
        return None
    equities = all_vs_range(parse_range(found.group(1)))[0]
    need = adv.data["need"]
    calls = [1.0 if eq >= need + 0.02 else 0.0 for eq in equities]
    close = [1.0 if abs(eq - need) < 0.02 else 0.0 for eq in equities]
    chart = range_chart(f"Calling the all-in: {percent(need)} needed", seen.hand_name, {"c": calls, "x": close},
                        [percent(eq) for eq in equities], legend=(("c", "Call"), ("x", "Close"), ("f", "Fold")))
    chart["share"] = share_of_hands([1.0 if eq >= need else 0.0 for eq in equities])
    return chart


def reshove_chart(seen: Seen, spot: Spot, adv, before: Before) -> dict:
    """All-in over a raise with 25bb or less: the solver's value for every hand (the engine wants +0.15bb)."""
    setup, hero = spot.setup, spot.hero
    opener = before.raises[0]
    opener_behind = spot.nb(opener.idx)
    eff = min(setup.live[hero], setup.live[opener.idx]) / setup.bb
    opens = villain_open_range(opener_behind, spot.types[opener.idx], eff)
    flats = {}
    for caller in before.callers:               # a caller's range: the call and set-mine rows of the chart
        chart = vs_open_chart(opener_behind, spot.nb(caller))
        flats[caller] = [max(a, b) for a, b in zip(chart["call"], chart["setmine"])]
    prizes = Prizes() if spot.desperate else spot.prizes
    can_call = sum(1 for j in range(setup.n) if j != hero and not spot.away[j] and (j > hero or j == opener.idx
                                                                                      or j in flats))
    solution = solve_reshove(setup, hero, opener.idx, opener.amount, prizes, opener_range=opens, flat_callers=flats,
                             caller_prizes=spot.field_prizes, types=spot.types, away=spot.away,
                             iters=chart_rounds(can_call))
    evs = [solution.ev_bb(hand) for hand in range(169)]
    evs[seen.hand_class] = adv.data["reshove_ev_bb"]            # hero's cell: the engine's number
    return ev_chart(f"All-in over a raise from {seen.label(opener.idx)}, {bb_number(eff)}bb", seen.hand_name, evs, 0.15)


def reraise_chart(seen: Seen, before: Before) -> dict:
    """A raise in front with more than 25bb: re-raise, call or fold from the chart."""
    opener = before.raises[0]
    chart = vs_open_chart(seen.behind(opener.idx), seen.behind(seen.hero))
    calls = [max(c, s, d) for c, s, d in zip(chart["call"], chart["setmine"], chart["deep"])]
    return range_chart(f"{SEAT_TITLES.get(seen.label(seen.hero), 'Seat')} against a raise from {seen.label(opener.idx)}",
                       seen.hand_name, {"r": list(chart["value"]), "x": list(chart["bluff"]), "c": calls},
                       legend=(("r", "Re-raise"), ("x", "Re-raise as a bluff"), ("c", "Call"), ("f", "Fold")))


def limped_chart(seen: Seen, before: Before) -> dict | None:
    """Players only called: the sheet's row for the seat (raise and call along when deep, all-in when short)."""
    players = table_players(seen.n)
    row = TAG.table(players)["limpers"].get(str(min(seen.behind(seen.hero), players - 1)))
    if row is None:
        return None
    eff = seen.bbs(effective_stack(seen))
    seat = SEAT_TITLES.get(seen.label(seen.hero), "Seat")
    if eff <= 16:
        column = 0 if eff >= 12 else 1 if eff >= 8 else 2          # the sheet's all-in columns: 12-16, 8-11, up to 7bb
        return range_chart(f"Sheet: {seat.lower()} behind callers, {bb_number(eff)}bb", seen.hand_name,
                           {"r": parse_range(row["allin"][column])}, legend=(("r", "All-in"), ("f", "Fold")))
    callers = min(len(before.limpers), 3) - 1
    return range_chart(f"Sheet: {seat.lower()} behind {len(before.limpers)} caller{'s' if callers else ''}",
                       seen.hand_name, {"r": parse_range(row["raise"][callers]), "c": parse_range(row["call"][callers])},
                       legend=(("r", "Raise"), ("c", "Call along"), ("f", "Fold")))


# ==========================================================================
# 11. The answer
# ==========================================================================

def finished_answer(answer: dict, seen: Seen, money: Money | None, play: Play, standing: list) -> dict:
    answer.update(status="ready", headline=headline(seen, play), reason=play.reason, tiles=play.tiles,
                  flip=play.flip, also=play.also, plans=play.plans, chart=play.chart, guard=play.guard,
                  source=source_line(money, play),
                  warnings=shown_warnings(play.warnings + player_notes(seen) + standing))
    return answer


def headline(seen: Seen, play: Play) -> dict:
    """The verb, its size in big blinds and chips, the tone, and the intent that carries the advice out."""
    verb, kind, to = play.verb, play.kind, play.to
    legal, to_call = seen.legal, seen.to_call
    all_in = legal.get("allin")
    # Make the play one the table accepts: nothing to call is a check, a raise is kept inside its limits.
    if kind == "fold" and to_call <= 0:
        verb, kind = "CHECK", "check"
    if kind == "call" and to_call <= 0:
        verb, kind = "CHECK", "check"
    if kind == "check" and to_call > 0:
        verb, kind = "FOLD", "fold"
    if kind in ("raise", "bet"):
        box = legal.get("raise") or legal.get("bet")
        if box is None:                         # the betting is not open for a raise: the call is what is left
            verb, kind = ("CALL", "call") if to_call > 0 else ("CHECK", "check")
        else:
            to = max(box["min"], min(round(to), box["max"]))
            if to >= box["max"]:
                verb, kind = "ALL-IN", "allin"
            else:
                kind = "bet" if legal.get("bet") else "raise"
    if kind == "wait":
        return {"verb": verb, "size_text": "", "qualifier": play.qualifier, "tone": "wait", "sure": "", "follow": None}
    if kind == "call":
        size_text, follow = size_words(seen, to_call), {"kind": "call"}
    elif kind in ("raise", "bet"):
        size_text = ("TO " if kind == "raise" else "") + size_words(seen, to)
        follow = {"kind": kind, "to": to}
    elif kind == "allin":
        size_text, follow = (size_words(seen, all_in) if all_in else ""), {"kind": "allin"}
    else:
        size_text, follow = "", {"kind": kind}
    tone = "passive" if verb in ("CALL", "CHECK") else "fold" if kind == "fold" else "attack"
    return {"verb": verb, "size_text": size_text, "qualifier": play.qualifier, "tone": tone, "sure": play.sure,
            "follow": follow}


def size_words(seen: Seen, chips) -> str:
    """An amount for the headline: 2.2BB and 1,320 chips; in All-In or Fold the table counts big blinds only."""
    big_blinds = bb_number(chips / seen.bb) + "BB"
    return big_blinds if seen.mode == "aof" else big_blinds + DOT + chips_text(chips)


def source_line(money: Money | None, play: Play) -> str:
    """The prize level, then where the answer comes from (and the guard's verdict)."""
    if money is None:
        return play.source[:1].upper() + play.source[1:]
    level = {"off": "ICM off" + DOT + "chip EV", "estimated": "ICM estimated", "on": "ICM",
             "exact": "ICM exact"}[money.level]
    return level + DOT + play.source if play.source else level


def shown_warnings(warnings: list) -> list:
    """Two warnings are shown, the most pressing first; the rest fold into one line that counts them."""
    def rank(item):
        return WARNING_ORDER.index(item["code"]) if item["code"] in WARNING_ORDER else len(WARNING_ORDER)

    ordered, seen_texts = [], set()
    for item in sorted(warnings, key=rank):
        if item["text"] not in seen_texts:
            ordered.append(item)
            seen_texts.add(item["text"])
    shown = [{"code": item["code"], "text": item["text"]} for item in ordered[:2]]
    rest = ordered[2:]
    if rest:
        shown.append({"code": "more", "text": f"{len(rest)} more: " + "; ".join(item["short"] for item in rest) + "."})
    return shown
