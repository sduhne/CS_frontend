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
   known (ICM off, estimated, on, exact), the stage, the fold clock.  In a
   very large field (more than ``PRIZE_PLACES`` paid places still to reach)
   the prize model is thinned so that an answer stays quick.
4. **The route.**  Which part of the engine answers:

       tournament, full plan     preflop.advise, then the survival guard
       tournament, all-in plan   the all-in or fold tables (binary), the engine as a second line
       spin                      the spin tables to 16bb (20bb small blind and heads-up), the engine on chips above
       all-in or fold            aof.decide
       after the flop            postflop.advise_postflop, with roles and lines from the recorded actions,
                                 then the adapter's own rules (below)

5. **The survival guard** (tournament, full plan, before the money).  A play
   that can lose a third or more of the chips hero has left before the flop
   (counted against the players who can still match them) is also put to the
   all-in or fold table, read at the stack really at risk.  The table agrees:
   the engine's play stands.  The table folds: in the style "Cash first" the
   headline is the fold ("survival fold", the engine's play the second line);
   in the default style "Survive, then win" only when the engine's own edge is
   thin (``THIN_EV_BB_*``, ``THIN_EDGE_POINTS_*``), otherwise the play stands
   as a "clear edge".  A good price is never folded, first in with 17bb or more
   the sheet's small raise takes the place of the fold, and the big blind's
   sheet call takes it against a small raise.  A close answer that puts chips
   in gives way to the quieter play.  The guard is off in the money, for a
   desperate stack, near the bubble when the fold clock says "cannot fold",
   with a read that makes the play safer, while re-entry is open and in the
   Max EV style.
6. **After the flop.**  The engine is asked about the opponents who have a
   hand (a player sitting out has none), each with the range of the way he
   came in (``preflop_roles``: first raise, raise over callers, re-raise,
   all-in, called a raise, a re-raise or an all-in ...), narrowed by what he
   really did since (the check of a player who has not acted yet is only an
   assumption: the spot line names it and the answer is provisional).  The
   stack it plays for is the deepest that can still call hero.  Then, in
   this order: no pair and no draw folds to a bet of half the pot from a
   player who did not raise before the flop; the playbook's one-pair rule
   (not against lag and maniac, not with the stack committed when the street
   began); before the money a close call or bluff gives way to the quieter
   play, as before the flop; and in the all-in plan the free-flop rule.
7. **The answer**: headline (verb, size, tone, how sure, the intent that
   carries it out), one sentence of reason, tiles, what flips it, plan lines,
   warnings, the source line, the range chart, the context.  An all-in shows
   the amount that can be matched; a bet after the flop is rounded to the
   table's chips.

Besides the keys of the build spec the answer carries ``icm`` (off,
estimated, on, exact), ``guard`` (agrees, survival, edge, close, off, none)
and ``provisional`` ("if BB and CO check" while players in front of hero have
not acted after the flop, else "").  The user's own notes on the opponents in
the pot are shown among the warnings.

Words.  "Engine", "guard" and "table" (for the all-in or fold lookup) are the
manual's words and stay in the small source line under an answer ("the engine
decides", "the all-in table agrees", "SURVIVAL FOLD (engine: ...)", "GUARD
OFF (...)").  Every other sentence the user reads says "by the numbers" and
"chart"; the table is the poker table.  A NO ADVICE answer never shows a
Python error: ``last_fault`` keeps it, and it is printed when the program
runs with ``--verbose``.

The engine is the baseline, not the last word: everything here is for study
and play money.
"""

from __future__ import annotations

import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field

from .. import aof as AOF
from .. import binary as BN
from .. import latereg as LR
from .. import spin as SP
from .. import state as S
from .. import tag as TAG
from ..cards import COMBO_COUNT, HANDS, format_range, parse_cards, parse_hand, parse_range, range_pct
from ..equity import all_vs_range, allin_order
from ..evaluator import describe
from ..icm import Prizes
from ..postflop import PostflopSpot, Villain, advise_postflop
from ..preflop import Act, Spot, _chart_shift
from ..preflop import advise as engine_advise
try:                                            # the engine's plan against an all-in over hero's raise, and the
    from ..preflop import hero_open_range, reshove_plan as engine_reshove_plan      # opening range it is priced with
except ImportError:                             # renamed there: the sheet's small raise then shows no plan lines
    engine_reshove_plan = hero_open_range = None
from ..preflop import solve_open_shove, solve_reshove      # the solver, with a blind posted all-in put right
from ..pushfold import HandSetup, nash_push_range
from ..ranges import (PLAYER_TYPES, norm_type, parse, play_order, rfi_range, scale_range, threebet_range,
                      top_percent, villain_limp_range, villain_open_range, vs_open_chart)
from .amounts import tidy
from .model import HERO, average_stack, goal_for, icm_level, imply_until, postflop_order, replay, session_level

# --------------------------------------------------------------------------
# Numbers a reader may want to change
# --------------------------------------------------------------------------

COMMIT_SHARE = 1 / 3            # the guard looks at plays that can lose this share of what hero has left before the flop
RAISE_IS_ALLIN = 1 / 3          # a raise of this share of the raiser's stack is read as an all-in in the tables
# The guard in the style "Survive, then win" only folds a thin edge.  Thin is: an all-in (or a raise that
# commits) the engine values below this many big blinds against folding ...
THIN_EV_BB_FAR = 0.20           # ... far from the money
THIN_EV_BB_CLOSE = 0.20         # ... from "close to the money" on (the points for a call are what differs)
# ... and a call of an all-in (or a call that commits) with fewer points of equity than this over what it needs:
THIN_EDGE_POINTS_FAR = 4
THIN_EDGE_POINTS_CLOSE = 7
GOOD_PRICE = 0.25               # the guard never folds a call at 3 to 1 or better (pot odds of 25% or less) ...
CLEAR_EQUITY_POINTS = 15        # ... nor one with this many points of equity over what it needs
SHEET_RAISE_BB = 17             # first in from this stack up, the guard's fold of an all-in becomes the sheet's small raise
PLAN_COMMITS_BB = 45            # up to this stack a re-raise the engine will not fold is judged as the whole stack
SMALL_RAISE_BB = 2.5            # "a small raise": the big blind's sheet calls, and the spin tables' raise rows
BB_CALL_BB = (9, 24)            # the stacks of the sheet's short list of big blind calls against a small raise
                                # (any pair, any suited hand, ...); deeper, the sheet's own row for 25bb or more is
                                # read, and a close call must be on that row and on the short list as well
ENGINE_CLOSE_POINTS = 2         # the engine calls a call "close" within this many points (plan lines use it)
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
PLAYBOOK_POTS_BEHIND = 1.5      # ... which does not apply with fewer pots than this behind when the street began
TINY_CALL = 0.10                # a call of this share of the pot or less is never folded by a rule of this file
NO_PAIR_BIG_BET = 0.50          # no pair and no draw: fold to a bet of this share of the pot from a player who did not raise
DRAW_OUTS = 8                   # "a draw": this many outs or more, with cards to come
FREE_FLOP_POTS = 4              # all-in plan after the flop: all-in with this many pots behind or fewer
FREE_FLOP_OUTS = 12             # ... with top pair or better, or a draw with this many outs
SHORT_ALLIN_BB = 3              # an all-in under this many big blinds (or of less than a full raise) is not "a raise"
CALLER_SHARE, CALLER_WIDEST = 0.75, 50.0    # a player who called an all-in and has chips behind: this share of the
                                # solved calling range, and never more than this many percent of hands (as the engine)
CHIP_STEPS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000)
                                # after the flop a bet is rounded to the biggest of these that the blinds are made of
PRIZE_PLACES = 1000             # the prize maths works on this many paid places at most: a bigger field is thinned
                                # (``thinned_prizes``).  A 5,000-entrant field with 750 paid is not touched
EV_CLOSE_BB = 0.05              # an all-in within this of its threshold is drawn as "close" in a chart
CHART_SOLVER_WORK = 72          # a solver chart may cost about this many (rounds x players who can call)

PASSIVE_TYPES = ("nit", "tight", "loose", "station")        # their big bets and raises are rarely bluffs
AGGRESSIVE_TYPES = ("lag", "maniac")                        # the only players the one-pair rule lets hero call down
LOOSE_TYPES = ("loose", "station", "maniac", "lag")         # they call with far more than the charts
# A read lifts the guard only when it makes the play safer:
FOLDS_TOO_MUCH = ("nit", "tight")                           # ... behind hero, for an all-in when nobody has raised
RAISES_TOO_WIDE = ("lag", "loose", "maniac")                # ... on the player whose raise or all-in hero plays against
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
    ("use the solved table", "use the chart for solid players"),            # an All-In or Fold note
)

# Words for what the user reads.  "Engine" and "guard" are the manual's words for the small source line under an
# answer; every other sentence says "by the numbers", and the all-in or fold lookup is a "chart" (the table is the
# poker table).
NUMBERS_ALONE = "by the numbers alone"          # the note on a tile whose number belongs to the play not made
NUMBERS_AGAIN = "Played by the numbers again once in the money, or with a read that makes it safer."
CHART_SAYS = "The chart says"                   # the tile with the all-in chart's answer

MINUS = "\u2212"                # the real minus sign, for losses
DOT = " \u00b7 "                 # the middle dot between two parts of a line
WARNING_ORDER = ("heads_up", "caller_behind", "covered_call", "engine", "close", "note", "blinds_up",
                 "preflop_unknown", "outside_tables", "charts_loading", "icm_off", "reentry_open", "left_stale",
                 "no_bubble_estimate", "icm_estimated", "bounty")


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


def by_the_numbers(summary: str, max_ev: bool = False) -> str:
    """The second line under an answer that a rule of the coach made: what the numbers alone would play.

    "By the numbers alone: ALL-IN +1.17bb (the Max EV style plays it)."
    """
    return f"By the numbers alone: {summary}" + (" (the Max EV style plays it)." if max_ev else ".")


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
            "context": {"stage": "", "gear": "", "fold_clock": ""}, "icm": "off", "guard": "none",
            "provisional": ""}


VERBOSE: bool | None = None     # print the detail of a NO ADVICE answer on stderr; ``None``: when the program was
                                # started with --verbose (``python -m poker_coach app --verbose``)
last_fault = ""                 # that detail (the Python traceback) of the last NO ADVICE answer, for a log


def keep_fault(err: Exception) -> None:
    """The Python detail of a spot the coach could not answer: for the log, never for the page."""
    global last_fault
    last_fault = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    verbose = "--verbose" in sys.argv[1:] if VERBOSE is None else VERBOSE
    if verbose and sys.stderr is not None:      # the packaged program may have no console
        sys.stderr.write("the coach could not answer a spot:\n" + last_fault)


def no_advice(answer: dict, err: Exception) -> dict:
    """The coach stopped on this spot: say so in plain words, and keep whatever was already known.

    The page never shows the Python error; ``keep_fault`` has it for the log.
    """
    keep_fault(err)
    answer.update(status="ready", reason="The coach cannot read this spot. Play it from the sheet; the next one is "
                                         "advised as usual.",
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
    over = hand is None or hand["needs"] == "next"
    if data["mode"] == "spin" and data["game"]["over"] and over:
        # who won the last hand, then the game: the page shows this one line
        won = result_line(view) if hand is not None and (hand.get("result") or {}).get("text") else ""
        return " ".join(part for part in (won, "The game is over: press N for a new game.") if part)
    # no chips on hero's seat, and no hand of his running: what he can do stays on screen
    out = no_chips_line(data) if over or str(HERO) not in (hand.get("positions") or {}) else ""
    if hand is None:
        return out or "No hand is being played: press N to deal."
    if hand["needs"] == "next":
        return " ".join(part for part in (result_line(view), out or next_hand_line(view)) if part)
    if hand["needs"] == "result":
        return "The betting is over: say who won."
    state = session.hand_state()
    if HERO not in state.order:
        return out or "You are not in this hand."
    if HERO in state.folded:
        return "You have folded: nothing left to decide. Press N for the next hand."
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
        if state.phase == "preflop" and nothing_to_decide_if_they_fold(data["hand"], state):
            # the small blind against a big blind who posted his last chips, and no more than the small blind
            return "Nobody has entered yet, and the big blind is all-in for no more than you have posted: " \
                   "if everybody folds there is nothing to decide. Enter the first call or raise."
        target = hand["target"]
        if target is None:
            return "The betting round is over."
        name = (data["table"]["seats"].get(str(target)) or {}).get("name", "")
        label = state.labels.get(target, f"seat {target}")
        return f"Waiting for {name + ' (' + label + ')' if name else label}: it is not your turn."
    return None


def nothing_to_decide_if_they_fold(hand: dict, state) -> bool:
    """Hero has not acted in this round, and it closes without him when every player in front does the passive
    thing: the only players left are all-in for no more than he has in front of him already.  (The table then
    waits for the first player, not for hero: there is no "if they fold" answer to give.)"""
    if HERO not in state.live() or state.stack[HERO] <= 0 or state.to_act() in (None, HERO):
        return False
    if any(entry["seat"] == HERO for entry in state.log if entry["street"] == state.phase):
        return False
    ahead = replay(hand)
    try:
        imply_until(ahead, HERO)
    except Exception:                           # model._NoTurn: the round closed before his turn
        return True
    return False


def no_chips_line(data: dict) -> str:
    """Hero has no chips on his seat: what he can do, said where it stays on screen.  "" while he has chips."""
    seat = data["table"]["seats"].get(str(HERO)) or {}
    if seat.get("stack", 0) > 0:
        return ""
    if data["mode"] == "tournament":
        return "You have no chips left: type a new stack on your seat to re-enter, or start a new tournament."
    return "You have no chips left: type a new stack on your seat to sit down again."


def result_line(view: dict) -> str:
    """Who won the hand on screen: the model's own line (``view.hand.result.text``) and a full stop.

    "Seat 5 (BB) wins 26,475." or "You (CO) win 3.98bb, seat 3 (BB) wins 3.97bb."  One source, so an
    amount never differs between the hand line and the coach by a rounding (an All-In or Fold pot split
    after the fee is 7.95bb, not 8).
    """
    result = view["hand"].get("result") or {}
    text = str(result.get("text") or "").strip()
    if not text:
        return "The hand is over."
    return text if text[-1] in ".!?" else text + "."


def next_hand_line(view: dict) -> str:
    """One line for the hand to come: where the button is and what hero's seat will be.  The seat names on the
    table are already the next hand's once a hand is settled."""
    table = view["table"]
    hero = next((seat for seat in table["seats"] if seat["is_hero"]), None)
    if not hero or not hero.get("pos") or hero.get("status") == "away":
        return "Press N for the next hand."
    where = SEAT_WORDS.get(hero["pos"], "in " + hero["pos"])
    return f"The button is now on seat {table['button']} and you are {where}: press N for the next hand."


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
    engine_away: list           # the same for the engine's model of the last raiser: see ``read_table``
    acts: list                  # engine actions before the flop, hero's own included
    to_call: float              # what hero must add to stay in
    legal: dict                 # what hero may do, from the view
    known: int = 0              # how many entries of ``state.log`` really happened: the rest are the passive
                                # default of the players in front of hero, who have not acted yet
    pending: list = field(default_factory=list)     # the seats of those players, in the order they will act

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
    known = len(state.log)
    if state.to_act() != HERO:
        imply_until(state, HERO)                # "folded to you": the players in front take the passive default
    # the players that default was taken for (a player sitting out really does check or fold: he is not waited for)
    pending = [entry["seat"] for entry in state.log[known:] if entry["seat"] not in state.away]
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
    engine_away = list(away)
    if any(act.idx == hero for act in acts):
        # Hero acts a second time: the players behind him who folded since are out of the hand.  The engine
        # models the range of the player who raised over hero by who could still call him: a player who folded
        # only after that raise was still to act when it was made, exactly as in the plan line under hero's own
        # raise, so for the engine he is not "away" (the two answers of the hand then use the same range).
        preflop = [entry for entry in state.log if entry["street"] == "preflop"]
        raises = [k for k, entry in enumerate(preflop) if entry["kind"] not in ("fold", "check", "call")
                  and entry["seat"] != HERO]
        last_raise = raises[-1] if raises else len(preflop)
        folded_before = {entry["seat"] for entry in preflop[:last_raise] if entry["kind"] == "fold"}
        for index in range(hero + 1, len(order)):
            away[index] = away[index] or order[index] in state.folded
            engine_away[index] = engine_away[index] or order[index] in folded_before
    return Seen(data=data, mode=data["mode"], hand=hand, state=state, order=order, hero=hero, bb=level["bb"],
                setup=setup, hand_class=hand_class, cards=cards, types=types, tags=tags, away=away,
                engine_away=engine_away, acts=acts, to_call=view["hand"]["to_call"],
                legal=view["hand"]["legal"] or {}, known=known, pending=pending)


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
    # ``sitting_out``: who had no hand when hero raised.  The engine rebuilds hero's opening range from it, so
    # the plan line under his raise and the answer to the all-in that follows are priced with one range.
    return Spot(setup=seen.setup, hero=seen.hero, hand=seen.hand_class, cards=seen.cards,
                names=[seen.label(i) for i in range(seen.n)], types=list(seen.types), away=list(seen.engine_away),
                prizes=prizes, field_prizes=field_prizes, acts=list(seen.acts), stage=stage, desperate=desperate,
                sitting_out=[seat in seen.state.away for seat in seen.order])


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
    """What hero faces after the flop: a bet, or nothing, and what is only assumed of the players in front of him."""
    state = seen.state
    pot = state.pot_total()
    assumed = assumption(seen)
    if seen.to_call <= 0:
        if assumed:
            return f"{assumed}, pot {bb_number(seen.bbs(pot))}bb"
        checked = any(e["street"] == state.phase and e["kind"] == "check" for e in state.log)
        return f"{'checked to you' if checked else 'you act first'}, pot {bb_number(seen.bbs(pot))}bb"
    # the last player who bet or raised on this street, and who has called him since
    street = [e for e in state.log if e["street"] == state.phase]
    made = [k for k, e in enumerate(street) if e["kind"] in ("bet", "raise") and e["seat"] != HERO]
    if made:
        last = street[made[-1]]
        bettor, all_in, raised = last["seat"], last["allin"], last["kind"] == "raise"
        callers = [e["seat"] for e in street[made[-1] + 1:]
                   if e["kind"] == "call" and e["seat"] != HERO and e["seat"] not in state.folded]
    else:                                       # no bet on record: the player with the most chips in front
        bettor = max((s for s in state.live() if s != HERO), key=lambda s: state.in_front[s])
        all_in, raised, callers = state.stack[bettor] <= 0, state.raises >= 2, []
    bet = state.in_front[bettor]
    before = pot - sum(state.in_front.values())             # the pot before this street's bets
    if all_in:
        action = f"is all-in for {bb_number(seen.bbs(bet))}bb"
    elif raised:
        action = f"raises to {bb_number(seen.bbs(bet))}bb"
    else:
        action = f"bets {bb_number(seen.bbs(bet))}bb"
    text = f"{seen.who(seen.order.index(bettor))} {action} into {bb_number(seen.bbs(before))}bb"
    if callers:
        text += f", {listed([seen.who(seen.order.index(s)) for s in callers])} call{'s' if len(callers) == 1 else ''}"
    return text + (", " + assumed if assumed else "")


def listed(names: list) -> str:
    """"BB", "BB and CO", "BB, CO and BTN"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def assumption(seen: Seen, short: bool = False) -> str:
    """After the flop: what is assumed of the players in front of hero who have not acted yet, or "".

    "if BB and CO check", "if BTN folds".  The answer is for the spot as it
    will be if they do the passive thing; ``short`` names them by seat only.
    """
    state = seen.state
    if state.phase == "preflop" or not seen.pending:
        return ""

    def name(seat):
        index = seen.order.index(seat)
        return seen.label(index) if short else seen.who(index)

    parts = []
    for word, seats in (("check", [s for s in seen.pending if s not in state.folded]),
                        ("fold", [s for s in seen.pending if s in state.folded])):
        if seats:
            parts.append(f"{listed([name(s) for s in seats])} {word}{'s' if len(seats) == 1 else ''}")
    return "if " + " and ".join(parts)


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


def thinned_prizes(prizes: Prizes, table: int, places: int | None = None) -> Prizes:
    """The prize model, made affordable in a very large field.

    The time an ICM value takes grows with the paid places that can still be
    reached, a little faster than in step with them: with 22,000 of them one
    answer took 12 seconds.  A player's value depends on his share of the
    chips and on the share of the field that is paid, not on the head count.
    So above ``PRIZE_PLACES`` the rest of the field is thinned: every ``c``
    players become one with the same stack, and every ``c`` places of the
    ladder one place that pays their average.  The players at the table stay
    as they are.  What is kept exactly: whether the money has been reached
    (nobody is paid who would not be, and at least one place stays unpaid
    before the money), the prize of a place as a share of the field, and the
    bonus for cashing.

    ``table`` is the number of players at hero's table (they are not part of
    ``prizes.field_n``).  A field of 5,000 with 750 paid is under the cap and
    comes back untouched; late in a huge field, when fewer players are left
    than the cap, the exact ladder is used again.
    """
    cap = PRIZE_PLACES if places is None else places
    pays = prizes.raw_payouts
    left = table + prizes.field_n
    reachable = min(len(pays), left)            # the paid places somebody can still finish in
    if prizes.chip_ev or reachable <= cap:
        return prizes
    c = -(-reachable // cap)                    # players of the field that become one
    field = max(1, round(prizes.field_n / c))
    unpaid = left - len(pays)                   # places from the money, before it
    unpaid_thin = max(1, round(unpaid / c)) if unpaid > 0 else 0
    paid_thin = max(1, table + field - unpaid_thin)
    ratio = reachable / paid_thin               # places of the real ladder behind one place of the thin one
    total = [0.0]
    for prize in pays[:reachable]:
        total.append(total[-1] + prize)

    def paid_to(place: float) -> float:
        """The prizes of the first ``place`` places together (a part of a place counts as that part of its prize)."""
        whole = min(int(place), reachable)
        return total[whole] + ((place - whole) * pays[whole] if whole < reachable else 0.0)

    banded = []
    for j in range(paid_thin):
        first, end = j * ratio, (j + 1) * ratio
        low, high = min(int(first), reachable - 1), min(reachable - 1, max(int(first), -int(-end // 1) - 1))
        if pays[low] == pays[high]:             # the whole band pays one prize: that prize, to the last digit
            prize = pays[low]                   # (a rounding difference would count as one more pay jump)
        else:
            prize = (paid_to(end) - paid_to(first)) / ratio
        banded.append(min(prize, banded[-1]) if banded else prize)
    return Prizes(banded, field_n=field, field_stack=prizes.field_stack, itm_bonus=prizes.itm_bonus,
                  label=prizes.label)


def read_money(session) -> Money:
    data = session.data
    state = session.engine_state()
    goal = goal_for(data)
    prizes = thinned_prizes(S.build_prizes(state, goal), len(S.occupied(state)))
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
    # (Not while the fold clock, near the bubble, says the stack lasts into the money: that screen would say
    # "you can fold into the money" beside "too short to wait".)
    lasts = bool(clock and clock.get("verdict") == "safe" and stage["code"] in ("near_bubble", "bubble"))
    desperate = bool(hero_bb is not None and (
        (clock and clock.get("verdict") == "short" and hero_bb <= 6)
        or (hero_bb <= 3 and (to_money is None or to_money > 3) and not lasts)))
    # The bubble: by players left per paid place, and in a small field also when the engine's own stage says
    # so (two places or fewer from the money: 4 left of 3 paid is 1.33 a place, and one bust from the money).
    bubble = not in_money and ((ratio is not None and ratio < bubble_at) or stage["code"] == "bubble")
    close = not in_money and (bubble or (ratio is not None and ratio <= close_at))
    return Money(state=state, goal=goal, level="off" if prizes.chip_ev else icm_level(data), prizes=prizes,
                 field_prizes=field_prizes, stage=stage, clock=clock, ratio=ratio, in_money=in_money,
                 final_table=stage["code"] == "final_table", close=close, bubble=bubble, desperate=desperate)


def standing_warnings(data: dict, money: Money, now: float) -> list:
    """Warnings about the tournament numbers: they hold for every hand until the numbers are typed."""
    t = data["tournament"]
    out = []
    if t.get("reentry_open"):
        out.append(warning("reentry_open", "Re-entry is open: only chips are counted, and nothing is folded for "
                                           "survival.", "re-entry open"))
    elif money.level == "off":
        missing = "players left" if not t.get("remaining") else "places paid"
        if not t.get("remaining") and not (t.get("paid") or t.get("entrants")):
            missing = "players left and places paid"
        out.append(warning("icm_off", f"Only chips are counted, not prize money: enter {missing}.",
                           "prize money not counted"))
    elif money.level == "estimated":
        text = "Prize money is counted from typical prizes, and the other tables' stacks are guessed from this " \
               "one: enter the average stack."
        if not t.get("paid"):
            text += " Places paid are taken as 15% of the entrants."
        out.append(warning("icm_estimated", text, "prizes estimated"))
    age = players_left_age(data, now)
    limit = STALE_ON_BUBBLE if money.stage["code"] in ("near_bubble", "bubble") else STALE_AFTER_HANDS
    if age is not None and age >= limit and not money.final_table:
        out.append(warning("left_stale", f"Players left is about {age} hands old: update it.",
                           f"players left is {age} hands old"))
    if no_bubble_estimate(money):
        out.append(warning("no_bubble_estimate", "For the fold clock, change players left twice, a minute apart: "
                           "then it can say whether you can fold into the money.", "no bubble estimate yet"))
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
                "gear": f"{SPIN_TABLE_BB}bb or less: all-in or fold from the solved chart. Deeper: small raises."}
    if money is None:
        return {"stage": "", "gear": "", "fold_clock": ""}
    stage = money.stage
    line = STAGE_LINES.get(stage["code"], STAGE_LINES["unknown"])
    if stage.get("to_money") is None:           # players left or places paid are missing: the engine's code is a guess
        line = STAGE_LINES["unknown"]
    if stage["code"] in ("approach", "near_bubble", "bubble") and stage.get("to_money"):
        line = f"{stage['to_money']} from the money. " + line
    return {"stage": line, "gear": gear_line(data, stage.get("hero_bb")), "fold_clock": fold_clock_line(data, money)}


def gear_line(data: dict, hero_bb) -> str:
    """The gear for the stack, from the tight-aggressive sheet."""
    if hero_bb is None:
        return ""
    if data["config"].get("plan") == "allin":
        return "All-in or fold plan: one decision a hand, from the charts."
    floors = (40, 25, 17, 12, 0)                # the rows of tag.GEARS, deepest first
    for floor, (stack, name, what) in zip(floors, TAG.GEARS):
        if hero_bb >= floor:
            return f"{stack}: {name[0].lower() + name[1:]}. {what}"
    return ""


def clock_gives_a_verdict(money: Money) -> bool:
    """The fold clock judges (can fold, tight, cannot fold) only near the bubble and on it.

    Further out the bubble is hours away for every short stack, so "cannot
    fold into the money" would be on screen all the time; there the clock
    gives its numbers and the tables decide.
    """
    return money.stage["code"] in ("near_bubble", "bubble")


def fold_clock_line(data: dict, money: Money) -> str:
    """Can hero fold into the money?  The time the blinds take to eat his stack against the time the bubble needs.

    Near the bubble and on it: the verdict and the two times, in minutes.  Further out: the facts only.  With
    no estimate for the bubble yet: the one time that is known (``no_bubble_estimate`` asks for the rest).
    """
    clock = money.clock
    if not clock:
        return ""
    orbits, minutes = clock["orbits"], clock["minutes"]
    lasts = f"the blinds take {minutes:.0f} minutes to eat your stack"
    verdict, eta = clock.get("verdict"), clock.get("eta")
    needs = f"the bubble needs about {eta:.0f}" if eta is not None else ""
    if verdict in ("safe", "tight", "short") and not clock_gives_a_verdict(money):
        # far from the bubble: the facts only, no verdict (and never "find an all-in" beside a fold)
        text = f"The blinds give you about {orbits:.1f} orbits, about {minutes:.0f} minutes"
        text += f"; the bubble is about {eta:.0f} minutes away." if eta is not None else "."
    elif verdict == "safe":
        text = f"You can fold into the money: {lasts}, {needs}."
    elif verdict == "tight":
        text = f"Folding into the money is tight: {lasts}, {needs}."
    elif verdict == "short":
        text = f"You cannot fold into the money: {lasts}, {needs}. Find an all-in."
    else:
        text = sentence(lasts)
    cover = sit_out_cover(data, money)
    if cover is not None:
        text += f" You hold {percent(cover)} of what it takes to fold into the money (the sit-out line)."
    after = next_level(data)
    hero_stack = S.hero_stack(money.state)
    if after and hero_stack and hero_stack / after["bb"] < BLINDS_UP_BB:
        text += f" At the next level: {bb_number(hero_stack / after['bb'])}bb."
    return text


def no_bubble_estimate(money: Money) -> bool:
    """Near the bubble, where the fold clock would give a verdict, but with nothing to time the bubble by yet."""
    clock = money.clock
    return bool(clock) and clock.get("eta") is None and clock_gives_a_verdict(money) and not money.in_money


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
    guard: str = "none"         # agrees, survival, edge, close, off or none
    chart: dict | None = None
    facts: dict = field(default_factory=dict)       # the engine's numbers by name (``engine_facts``)


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
    # A raise or an all-in the engine makes by rule (aces and kings after a raise and a re-raise) while its own
    # all-in number is a loss: that number, and the fold share that goes with it, would contradict the headline.
    by_rule = kind in ("raise", "allin") and facts.get("ev", 0.0) < 0
    if "ev" in facts and not by_rule:
        tiles.append(tile("All-in against folding", signed_bb(facts["ev"]), value_note, sign_of(facts["ev"])))
    if "need" in facts and "equity" in facts:
        counted = "pot odds alone" if value_note == "chip EV" else "the price and ICM are counted"
        tiles.append(tile("Need / have", f"{percent(facts['need'])} / {percent(facts['equity'])}",
                          "equity: " + counted))
    if "all_fold" in facts and not by_rule:
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


PLAN_LINE = re.compile(r"If (.+) \((\d+)bb\) moves all-in: (CALL|FOLD) \(need (\d+)%, have (\d+)%\)")
NEVER_FOLDS = re.compile(r"\b(do not|never) fold\b", re.IGNORECASE)      # "do not fold to a 4-bet at this depth"


def plan_numbers(seen: Seen, plan) -> dict:
    """The engine's plan under a raise as ``{the player as the plan line names him: (need, have)}``, unrounded.

    The answer to the all-in itself is made from these two numbers, so what the plan line promises ("close",
    a fold of a thin call) is worked out from them and not from the rounded percentages of its text.
    """
    numbers = {}
    for entry in plan or ():
        index = entry.get("idx")
        if isinstance(index, int) and 0 <= index < seen.n and index != seen.hero:
            numbers[seen.who(index)] = (entry["need"], entry["eq"])
    return numbers


def all_in_plan_lines(seen: Seen, numbers: list) -> list:
    """The engine's "if BB (28bb) shoves: FOLD (need 47%, have 44% ..." sentences as plan lines."""
    plans = []
    for line in numbers:
        found = re.match(r"if (\S+) \((\d+)bb\) shoves: (CALL|FOLD) \(need (\d+%), have (\d+%)", line)
        if not found:
            continue
        label, stack, verdict, need, have = found.groups()
        who = next((seen.who(i) for i in range(seen.n) if seen.label(i) == label), label)
        plans.append(f"If {who} ({stack}bb) moves all-in: {verdict} (need {need}, have {have})")
    return plans


def plan_lines(seen: Seen, adv) -> list:
    """"If BB (28bb) moves all-in: FOLD": the engine's plan against an all-in over hero's raise."""
    plans = all_in_plan_lines(seen, adv.numbers)
    if "call any all-in" in adv.action:
        plans.append("If anybody moves all-in: CALL")
    elif will_not_fold(adv):
        plans.append("If anybody re-raises: do not fold, the chips go in at this depth")
    return plans


def will_not_fold(adv) -> bool:
    """A raise over a raise that the engine does not fold to another raise ("do not fold to a 4-bet at this depth")."""
    action = adv.action.strip()
    sized = re.search(r"to \d+(?:\.\d+)?bb", action) and "ALL-IN" not in action
    return bool(sized) and not action.startswith("RAISE") and any(NEVER_FOLDS.search(text) for text in adv.why)


def play_from_engine(seen: Seen, adv, value_note: str) -> Play:
    """An answer of ``preflop.advise`` as a play: its action, its first reason, its numbers."""
    verb, kind, to, qualifier = read_engine_action(adv.action, seen.bb)
    facts = engine_facts(adv)
    play = Play(verb=verb, kind=kind, to=to, qualifier=qualifier, sure=adv.confidence,
                reason=sentence(plain(adv.why[0])) if adv.why else "",
                tiles=engine_tiles(facts, kind, value_note),
                also=sentence(plain(adv.alt[0])) if adv.alt else "", plans=plan_lines(seen, adv), facts=facts)
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
    """An engine play in a few words, for a second line: "ALL-IN +0.15bb", "CALL, 60% against 53%".

    The all-in's value is added to an all-in only (and to a raise that puts
    the chips in): beside a CHECK or a FOLD it would read as that play's value.
    """
    moves_in = play.kind == "allin" or "all-in" in play.qualifier
    labels = ("All-in against folding",) if moves_in else ()
    number = next((t for t in play.tiles if t["label"] in labels + ("Need / have", "Price / equity")), None)
    if number is None:
        return play.verb
    if number["label"] == "All-in against folding":
        return f"{play.verb} {number['value']}"
    need, have = number["value"].split(" / ")
    return f"{play.verb}, {have} against {need}"


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
    survival_guard(seen, money, before, adv, play)
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
            "heads_up", "Heads-up with 10 to 20bb the coach only moves all-in or folds: a small raise with the "
                        "playable hands is normal there.", "heads-up: all-in or fold only"))
    state = seen.state
    shover = seen.order[before.raises[-1].idx] if before.raises else None
    still_in = [s for s in state.live() if s not in (HERO, shover) and state.stack[s] > 0 and state.owe(s) > 0]
    if before.kind == "shoved_on" and still_in:
        # hero raised, somebody called, then came the all-in: the engine prices the all-in player alone
        play.warnings.append(warning(
            "caller_behind", "A player who called your raise is still to act: these numbers do not count him.",
            "a caller is still behind"))
    if money.final_table and play.kind in ("call", "allin") and before.raises:
        # the engine decides alone at a final table; say so when the bubble table would not call a bigger stack
        says = table_answer(seen, money, before)
        covered = any(seen.start[r.idx] >= seen.start[seen.hero] for r in before.raises)
        if covered and says is not None and says.action == "FOLD":
            play.warnings.append(warning(
                "covered_call", f"The all-in player covers you: the bubble chart folds this hand here "
                                f"(it plays {says.short}).", "the bubble chart folds against a bigger stack"))
    if before.hero_called and before.raises:
        play.warnings.append(warning(
            "engine", "You called earlier in this hand: those chips are not counted here, so the real price is "
                      "a little better than the one shown.", "your earlier call is not priced"))
    if adv.confidence == "close" and play.guard not in ("survival", "close"):     # those two say it in the reason
        play.warnings.append(close_warning(engine_facts(adv), before, money, play))
    after = pending_level(seen)
    if after and before.kind == "first_in" and seen.bbs(seen.start[seen.hero]) < BLINDS_UP_BB:
        play.warnings.append(blinds_up_warning(seen, money, after))


def close_warning(facts: dict, before: Before, money: Money | None, play: Play) -> dict:
    """The engine calls its answer close.  The last sentence says why the headline is what it is."""
    if "need" in facts and "equity" in facts:
        text = f"Close: you need {percent(facts['need'])} and have {percent(facts['equity'])}."
    elif play.kind == "call":
        text = "Close: the call and the fold are worth about the same."
    elif "ev" in facts:
        wants = "; over a raise it takes +0.15bb" if before.kind == "raise" else ""
        text = f"Close: an all-in earns {signed_bb(facts['ev'])} against folding{wants}."
    else:
        text = "Close: the other play is nearly as good."
    if money is not None and not money.in_money and not money.prizes.chip_ev:
        if play.kind in ("fold", "check"):
            text += " Before the money the lower-variance side leads."
        elif play.guard == "agrees":
            text += " The all-in chart plays it too."
        elif play.source.endswith("the sheet's big blind list"):
            text += " The sheet calls this hand in the big blind."
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
#
# Two strengths, by style:
#
#   cash ("Cash first")            strict: before the money a play that risks the stack needs the
#                                  all-in or fold table to agree.
#   survive ("Survive, then win")  thin edge: the table can only fold a play whose own edge is thin
#                                  (THIN_EV_BB_*, THIN_EDGE_POINTS_*).  A clear edge is played.
#   maxev                          no guard.
#
# In both strengths: a play is judged by the chips it can lose against the players who can still put
# them at risk; a good price is never folded; a read lifts the guard only when it makes the play safer;
# and a close answer that puts chips in gives way to the quieter play.

@dataclass
class Risk:
    """What a play can cost hero before the flop."""
    chips: float = 0.0          # chips he still has to add and can lose with this play
    share: float = 0.0          # ... as a share of the chips he has left
    stack_bb: float = 0.0       # the stack actually at risk, in big blinds: where the all-in tables are read
    whole: bool = False         # an all-in, or a raise he will not fold: all the chips anybody can match


def stack_at_risk(seen: Seen, adv, play: Play) -> Risk:
    """The chips this play can lose before the flop, against the players who can still put them at risk.

    Only chips hero still has to add count, against what he has left: a blind
    already posted is no new risk.  An all-in is worth what the biggest stack
    still in the hand can match, so a re-raise that only puts a 10bb raiser
    all-in from a 60bb stack risks a sixth of it, not the stack.
    """
    state = seen.state
    left, mine = state.stack[HERO], state.in_front[HERO]
    if play.kind not in ("call", "raise", "allin") or left <= 0:
        return Risk()
    eff_bb = seen.bbs(effective_stack(seen))
    if play.kind == "call":
        chips = min(seen.to_call, left)
        return Risk(chips, chips / left, eff_bb)
    rivals = [s for s in state.live() if s != HERO and s not in state.away]
    if not rivals:
        return Risk()
    reach = max(state.in_front[s] + state.stack[s] for s in rivals)     # the biggest total anybody can match
    whole = play.kind == "allin" or "call any all-in" in play.qualifier \
        or (will_not_fold(adv) and eff_bb <= PLAN_COMMITS_BB)
    total = min(mine + left, reach) if whole else min(play.to or 0, mine + left, reach)
    chips = max(0.0, total - mine)
    return Risk(chips, chips / left, eff_bb if whole else min(eff_bb, seen.bbs(total)), whole)


def call_price(seen: Seen) -> float | None:
    """The pot odds of the call hero faces, on chips alone: what he adds against the pot he can win."""
    state = seen.state
    call = min(seen.to_call, state.stack[HERO])
    if call <= 0:
        return None
    reach = state.in_front[HERO] + call
    pot = state.pot_total() - sum(max(0, state.in_front[s] - reach) for s in state.order if s != HERO)
    return call / (pot + call)


def edge_points(facts: dict) -> tuple[int, int] | None:
    """(need, have) of a call in whole points, as the tile shows them; ``None`` when the engine gave none."""
    if "need" not in facts or "equity" not in facts:
        return None
    return round(100 * facts["need"]), round(100 * facts["equity"])


def good_price(price: float | None, points: tuple | None) -> str:
    """Why the guard never folds this call, or "": 3 to 1 or better, or 15 points over what it needs."""
    if price is not None and price <= GOOD_PRICE + 1e-9:
        return f"a good price: {bb_number((1 - price) / price)} to 1"
    if points is not None and points[1] - points[0] >= CLEAR_EQUITY_POINTS:
        return f"a clear call: {points[1]}% against {points[0]}%"
    return ""


def thin_call(points: tuple | None, near: bool) -> bool:
    """A call whose equity is fewer points over the need than the style asks for (no number: thin)."""
    if points is None:
        return True
    return points[1] - points[0] < (THIN_EDGE_POINTS_CLOSE if near else THIN_EDGE_POINTS_FAR)


def engine_edge(play: Play, near: bool) -> tuple[bool, str]:
    """(is the engine's own edge thin, the edge in words): "engine +0.85bb", or "56% against 47%" for a call.

    An all-in, or a raise that commits, is measured by the engine's "all-in
    against folding"; a call by its equity over what it needs.  A play with
    no usable number counts as thin.
    """
    facts, points = play.facts, edge_points(play.facts)
    if play.kind != "call" and "ev" in facts:
        value = round(facts["ev"], 2)                       # the number as the tile shows it
        return value < (THIN_EV_BB_CLOSE if near else THIN_EV_BB_FAR), "engine " + signed_bb(value)
    if points is not None:
        return thin_call(points, near), f"{points[1]}% against {points[0]}%"
    return True, ""


def guard_is_off(seen: Seen, money: Money) -> str:
    """Why the guard does not apply to this hand at all, or "" when it does."""
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
    if clock_gives_a_verdict(money) and clock.get("verdict") == "short":
        return "the fold clock says you cannot fold"
    return ""


def safer_read(seen: Seen, depends_on: list, safe: tuple) -> str:
    """A read that makes the play safer, in words, or "".

    Every player the play depends on must carry it: his own tag, else the
    table-wide opponents setting, which counts as that tag on every untagged
    seat (for the guard as for the engine).
    """
    if not depends_on or not all(seen.types[i] in safe for i in depends_on):
        return ""
    tagged = [i for i in depends_on if seen.tags[i] != "unknown"]
    if len(tagged) < len(depends_on):
        return f"the table is set to {seen.data['config'].get('opponents')}"
    return "a read on " + ", ".join(seen.label(i) for i in depends_on[:2])


def read_for_the_play(seen: Seen, before: Before) -> str:
    """The read that lifts the guard for the play in front of hero, or "".

    Nobody has raised: every player who can still call (behind hero, and the
    callers in front) folds too much: nit or tight.  Against a raise or an
    all-in: that player raises too wide: lag, loose or maniac.  A station, a
    loose player or a maniac behind hero calls more, which makes an all-in
    worse, so those tags do not lift it.
    """
    if before.raises:
        return safer_read(seen, [r.idx for r in before.raises], RAISES_TOO_WIDE)
    behind = [i for i in range(seen.hero + 1, seen.n) if not seen.away[i]]
    return safer_read(seen, behind + list(before.limpers), FOLDS_TOO_MUCH)


PREMIUMS = parse_range("QQ+, AKs, AKo")         # the engine raises these small with 12bb or more and calls any all-in


def sheet_row_over_my_raise(seen: Seen, money: Money, size_bb: float) -> str | None:
    """The sheet's row "you raised and met an all-in" for hero's seat, the stage and the size of the all-in."""
    rows = TAG.table(table_players(seen.n))["shoved_on"].get(seat_group(seen.behind(seen.hero)))
    if rows is None:
        return None
    return rows["bubble" if money.bubble else "normal"][BN.band(size_bb)]


def premium_plan(seen: Seen, money: Money, small_raise: bool) -> str:
    """The plan for a premium hand first in with a short stack: "call", "decide" or "" (no such plan).

    ``small_raise``: the engine said (or hero made) the small raise that
    calls any all-in.  The decision is taken at the raise, so the answer
    after an all-in is CALL ("call").  On the bubble the sheet folds some of
    these hands to an all-in (AK from the first seats); a raise that then
    folds is the worst of both, so there the first answer has to be all-in
    or fold ("decide").
    """
    if not small_raise or PREMIUMS[seen.hand_class] < 0.5:
        return ""
    if money.bubble:
        row = sheet_row_over_my_raise(seen, money, seen.bbs(start_effective(seen)))
        if row is not None and not in_range(row, seen.hand_class):
            return "decide"
    return "call"


def start_effective(seen: Seen) -> float:
    """The effective stack when hero acted first in, as the engine counts it (after the antes): his, or the
    biggest behind him that is not sitting out."""
    live = seen.setup.live
    behind = [live[i] for i in range(seen.hero + 1, seen.n) if seen.order[i] not in seen.state.away]
    return min(live[seen.hero], max(behind)) if behind else live[seen.hero]


def raised_to_call(seen: Seen, before: Before) -> bool:
    """Did hero's raise come from "raise small and call any all-in"?

    The adapter keeps nothing between two answers, so the engine's rule is
    read again from the table: a premium hand, first in with a small raise,
    12bb to the top of the engine's all-in or raise zone (16bb, 20bb from
    the small blind and heads-up).
    """
    if before.kind != "shoved_on" or not seen.acts or PREMIUMS[seen.hand_class] < 0.5:
        return False
    first = seen.acts[0]
    if first.idx != seen.hero or first.kind != "raise" or first.amount > SMALL_RAISE_BB * seen.bb + 1e-9:
        return False
    late = seen.n == 2 or seen.behind(seen.hero) == 1
    return 12 <= seen.bbs(start_effective(seen)) <= (20 if late else 16)


def survival_guard(seen: Seen, money: Money, before: Before, adv, play: Play) -> None:
    """Before the money: the guard's say on the engine's play.  It rewrites ``play`` in place."""
    off = guard_is_off(seen, money)
    near = money.close or money.bubble
    strict = seen.data["config"].get("style") == "cash"
    if raised_to_call(seen, before) and (off or premium_plan(seen, money, True) == "call"):
        keep_the_plan(seen, play, off)
        return
    if not off:
        if premium_plan(seen, money, "call any all-in" in adv.action) == "decide":
            decide_now(play)
        if play.kind == "raise":            # the next answer is guarded too: the plan lines say what it will say
            exact = plan_numbers(seen, play.facts.get("plan"))
            play.plans = [plan_after_guard(seen, money, play.to or 0, line, strict, near, exact)
                          for line in play.plans]
    risk = stack_at_risk(seen, adv, play)
    at_stake = risk.share >= COMMIT_SHARE
    off = off or read_for_the_play(seen, before)
    if off:
        if at_stake:
            play.guard, play.source = "off", f"GUARD OFF ({off})"
        return
    says = None
    if at_stake:
        says = table_answer(seen, money, before, at_risk=risk.stack_bb, sized=play.kind == "raise" and risk.whole,
                            calling=play.kind == "call")
        if says is None:
            play.source = "no table row for this spot: the engine decides alone"
    if says is None:
        lower_variance_side(seen, before, adv, play)
        return
    if says.action not in ("FOLD", "CHECK"):
        play.guard, play.source = "agrees", "the all-in table agrees"
        return
    if play.kind == "call" or risk.chips <= seen.to_call + 1e-9:        # a call, or an all-in that is no more than one
        price = good_price(call_price(seen), edge_points(play.facts))
        if price:
            play.guard, play.source = "off", f"GUARD OFF ({price})"
            if not play.flip:
                play.flip = f"The all-in chart folds here ({says.short}), but a price like this is never folded."
            return
    thin, edge = engine_edge(play, near)
    thin = thin or adv.confidence == "close"        # what the engine itself calls close is no clear edge
    if not strict and not thin:
        # a clear edge: the engine's play stands although the table would fold
        play.guard, play.source = "edge", f"CLEAR EDGE ({edge}): played although the all-in table folds"
        play.tiles = play.tiles[:2] + [tile(CHART_SAYS, "CHECK" if seen.to_call <= 0 else "FOLD", says.short)]
        if not play.flip:
            play.flip = "The all-in chart folds here; the Cash first style follows it."
        return
    survival_play(seen, money, before, play, says, risk, strict, edge)


def survival_play(seen: Seen, money: Money, before: Before, play: Play, says, risk: Risk, strict: bool,
                  edge: str) -> None:
    """The table folds and the guard follows it: the quietest play the sheet allows becomes the headline.

    That is a fold (a check when it is free), with two exceptions from the
    tight-aggressive sheet: first in with 17bb or more a hand on the sheet's
    raise list raises small instead of moving all-in, and the big blind may
    call a small raise with the sheet's list instead of folding.
    """
    engine = engine_summary(play)
    free = seen.to_call <= 0
    thin_edge = "" if strict else edge.replace("engine ", "")       # the strict guard does not ask how big the edge is
    commits = "A re-raise at this depth commits the stack. " if play.kind == "raise" and risk.whole else ""

    def reason_for(lead: str) -> str:
        """ "Fold before the money: KQs from the button is an all-in only up to 28bb, and this close ..." """
        why = says.why.replace(" before the money", "", 1)      # the lead says it already
        if thin_edge:
            return f"{commits}A thin edge ({thin_edge}): {lead[0].lower() + lead[1:]} before the money. {sentence(why)}"
        return f"{commits}{lead} before the money: {why}."

    play.also = by_the_numbers(engine, max_ev=True)
    play.tiles = [t for t in play.tiles if t["label"] in ("All-in against folding", "Need / have")][:1]
    if play.tiles:
        play.tiles[0]["note"] = NUMBERS_ALONE
    play.tiles.append(tile(CHART_SAYS, "CHECK" if free else "FOLD", says.short))
    again = ["once in the money", "with a read that makes it safer"]
    if clock_gives_a_verdict(money) and money.clock:
        again.insert(1, "when the fold clock says you cannot fold")
    if thin_edge:
        again.insert(0, "with a clear edge")
    play.flip = "Played by the numbers again " + ", ".join(again[:-1]) + ", or " + again[-1] + "."
    play.sure, play.guard, play.plans = "standard", "survival", []
    play.warnings = [w for w in play.warnings if w["code"] != "engine"]     # they were about the engine's play
    small = sheet_small_raise(seen, before, play, risk)
    if small is not None:
        row, size = small
        play.verb, play.kind, play.to, play.qualifier = "RAISE", "raise", size, "survival raise"
        play.plans = small_raise_plans(seen, money, size, strict)
        folds = bool(play.plans) and all(": FOLD" in line for line in play.plans)
        play.reason = reason_for("No all-in") + " The sheet raises this hand small from this seat instead" \
                                              + (": raise, and fold to an all-in." if folds else ".")
        play.tiles.append(tile("The sheet says", "RAISE", "a small raise from this seat"))
        play.source = f"SURVIVAL RAISE (engine: {engine}): the sheet's small raise"
        play.chart = range_chart(f"Sheet: {SEAT_TITLES.get(seen.label(seen.hero), 'seat').lower()}, first in, "
                                 f"{bb_number(risk.stack_bb)}bb", seen.hand_name, {"r": parse_range(row)},
                                 legend=(("r", "Raise"), ("f", "Fold")))
        return
    if not free and play.kind != "call" and big_blind_sheet_call(seen, before):
        play.verb, play.kind, play.to, play.qualifier = "CALL", "call", None, "survival call"
        play.reason = reason_for("No all-in") + " The sheet lets the big blind call a small raise with this hand " \
                                                "instead of folding."
        play.tiles.append(tile("The sheet says", "CALL", big_blind_sheet_list(seen, before)[1]))
        play.warnings.append(warning("engine", "Play fit-or-fold after the flop: continue with top pair or better, "
                                               "or a strong draw."))
        play.source = f"SURVIVAL CALL (engine: {engine}): the sheet's big blind call"
        play.chart = big_blind_call_chart(seen, before)
        return
    play.verb, play.kind, play.to = ("CHECK", "check", None) if free else ("FOLD", "fold", None)
    play.qualifier = "survival check" if free else "survival fold"
    play.reason = reason_for("Check" if free else "Fold")
    play.source = f"SURVIVAL {'CHECK' if free else 'FOLD'} (engine: {engine})"
    play.chart = says.chart or play.chart


def sheet_small_raise(seen: Seen, before: Before, play: Play, risk: Risk) -> tuple[str, float] | None:
    """First in with 17bb or more, an all-in the guard folds: the sheet's small raise when the hand is on its list.

    ``(the sheet's raise list for the seat, the raise in chips)``, or
    ``None`` when the sheet does not raise the hand either.
    """
    if before.kind != "first_in" or play.kind != "allin" or risk.stack_bb < SHEET_RAISE_BB:
        return None
    players = table_players(seen.n)
    sheet = TAG.table(players)["first_in"].get(str(min(seen.behind(seen.hero), players - 1)))
    if sheet is None:
        return None
    stack = risk.stack_bb
    row = sheet["raise"][0 if stack >= 25 else 1]
    if not in_range(row, seen.hand_class):
        return None
    return row, float(sheet["size"][0 if stack >= 40 else 1 if stack >= 25 else 2]) * seen.bb


def small_raise_plans(seen: Seen, money: Money, size: float, strict: bool) -> list:
    """The plan lines under the sheet's small raise: what the next answer will say to an all-in.

    The engine proposed an all-in, so it gave no plan for a raise.  Its own
    plan is asked for here (the work an ordinary raise answer does anyway),
    and the guard has its say on it, exactly as under a raise of the
    engine's: the two answers of the hand then agree.
    """
    if engine_reshove_plan is None:
        return []
    try:
        spot = engine_spot(seen, money.prizes, money.field_prizes, money.stage, money.desperate)
        plan = engine_reshove_plan(spot, size, hero_open_range(spot))       # the range the next answer uses too
        lines = all_in_plan_lines(seen, [
            f"if {entry['pos']} ({entry['stack_bb']:.0f}bb) shoves: {'CALL' if entry['call'] else 'FOLD'} "
            f"(need {percent(entry['need'])}, have {percent(entry['eq'])}" for entry in plan])
    except Exception:                           # a plan that cannot be worked out never costs the answer
        return []
    near = money.close or money.bubble
    exact = plan_numbers(seen, plan)
    return [plan_after_guard(seen, money, size, line, strict, near, exact) for line in lines]


def big_blind_sheet_list(seen: Seen, before: Before) -> tuple[str, str] | None:
    """(the hands the sheet lets the big blind continue with against one raise, the same in words).

    With 9 to 24bb, against a raise of 2.5bb or less, that is the sheet's
    short list (any pair, any suited hand, any ace, K9o+, Q9o+, J9o+, T9o).
    With 25bb or more it is the sheet's row for the big blind against a
    raise from that seat.  ``None`` in any other seat, against two raises,
    when the call costs a third of the stack, under 9bb, and with 9 to 24bb
    against a bigger raise.
    """
    if before.kind != "raise" or seen.behind(seen.hero) != 0 \
            or seen.to_call >= COMMIT_SHARE * seen.state.stack[HERO]:
        return None
    eff = seen.bbs(effective_stack(seen))
    if eff >= BB_CALL_BB[1] + 1:
        group = seat_group(seen.behind(before.raises[0].idx))
        row = TAG.table(table_players(seen.n))["vs_raise"].get(f"{group}|bb")
        if row is not None:
            hands = ", ".join(row[key] for key in ("value", "bluff", "call", "setmine") if row.get(key))
            return hands, ("its list for the big blind with 25bb or more against a raise from "
                           + seen.label(before.raises[0].idx))
    small = before.raises[0].amount <= SMALL_RAISE_BB * seen.bb + 1e-9
    if eff >= BB_CALL_BB[0] and small:
        return TAG.BB_CALL_SHORT, TAG.BB_CALL_WORDS
    return None


def big_blind_kept_calls(rows: tuple | None) -> list:
    """The hands of the sheet's big blind list that keep their call before the money, as 169 weights.

    A hand must be on the sheet's row for that depth AND on the short list
    of hands that make top pair or a real draw (``tag.BB_CALL_SHORT``: any
    pair, any suited hand, any ace, K9o+, Q9o+, J9o+, T9o).  With 9 to 24bb
    the row is that short list; with 25bb or more the row is wider (K3o+
    against a button raise), and K5o is not a hand to call out of position
    with before the money.
    """
    if rows is None:
        return [0.0] * 169
    return [min(a, b) for a, b in zip(parse_range(rows[0]), parse_range(TAG.BB_CALL_SHORT))]


def big_blind_sheet_call(seen: Seen, before: Before) -> bool:
    """Is the hand one the big blind keeps calling a raise with before the money?"""
    return big_blind_kept_calls(big_blind_sheet_list(seen, before))[seen.hand_class] >= 0.5


def big_blind_call_chart(seen: Seen, before: Before) -> dict:
    rows = big_blind_sheet_list(seen, before) or (TAG.BB_CALL_SHORT, "")
    return range_chart("Sheet: the big blind against a raise", seen.hand_name, {"c": big_blind_kept_calls(rows)},
                       legend=(("c", "Play"), ("f", "Fold")))


def lower_variance_side(seen: Seen, before: Before, adv, play: Play) -> None:
    """A close answer before the money that puts chips in: the quieter play leads.

    The headline is FOLD (CHECK when it is free) and the engine's play the
    second line.  Two exceptions.  The big blind keeps the call for the
    hands that are on the sheet's list (``big_blind_sheet_list``: the short
    list against a small raise with 9 to 24bb, the sheet's own row with 25bb
    or more) and on the short list as well (``big_blind_kept_calls``), and a
    close re-raise there gives way to that call, not to a fold: a stronger
    hand never folds where a weaker one calls.  And a call of an all-in at a
    good price is never folded.
    """
    if adv.confidence != "close" or play.kind not in ("call", "raise", "allin"):
        return
    if play.kind == "call" and "need" in play.facts and good_price(call_price(seen), edge_points(play.facts)):
        return
    sheet = None
    rows = big_blind_sheet_list(seen, before)
    kept = big_blind_sheet_call(seen, before)
    if play.kind == "raise" and kept:
        # A close re-raise in the big blind (a bluff with a small suited ace): the quieter play is the call the
        # big blind makes with weaker hands of the sheet's list, not a fold.
        engine = engine_summary(play)
        play.also = by_the_numbers(engine, max_ev=True)
        play.tiles = play.tiles[:2]
        play.warnings = [w for w in play.warnings if w["code"] != "engine"]
        play.warnings.append(warning("engine", "Play fit-or-fold after the flop: continue with top pair or better, "
                                               "or a strong draw."))
        play.verb, play.kind, play.to = "CALL", "call", None
        play.qualifier, play.sure, play.guard, play.plans = "close: lower variance", "close", "close", []
        play.reason = "Close: the re-raise and the call are worth about the same. Before the money the " \
                      "lower-variance side leads: call, as the sheet has the big blind do with this hand."
        play.flip = NUMBERS_AGAIN
        play.source = f"CLOSE: before the money the lower-variance side leads (engine: {engine})"
        play.chart = hero_cell_as_played(play.chart, seen.hand_class, play.kind)
        return
    if play.kind == "call" and rows is not None:
        if kept:
            play.source = "the engine's close call is on the sheet's big blind list"
            return
        short_list = rows[0] == TAG.BB_CALL_SHORT
        if not short_list and in_range(rows[0], seen.hand_class):
            # on the sheet's row for 25bb or more, but not a hand that makes top pair or a real draw
            sheet = tile("Before the money", "FOLD", "the call is kept for " + TAG.BB_CALL_WORDS)
            reason = f"Close, and not a hand that makes top pair or a real draw ({TAG.BB_CALL_WORDS}): before " \
                     "the money, fold."
        else:
            sheet = tile("The sheet says", "FOLD", ("it calls " if short_list else "not on ") + rows[1])
            reason = f"Close, and not a hand the sheet calls a {'small ' if short_list else ''}raise with in the " \
                     f"big blind ({rows[1]}): before the money, fold."
    else:
        what = {"call": "call", "allin": "all-in"}.get(play.kind, "raise")
        quiet = "check" if seen.to_call <= 0 else "fold"
        reason = f"Close: the {what} and the {quiet} are worth about the same. Before the money the lower-variance " \
                 f"side leads: {quiet}."
    engine = engine_summary(play)
    free = seen.to_call <= 0
    play.also = by_the_numbers(engine, max_ev=True)
    play.tiles = play.tiles[:1 if sheet else 2]
    if play.tiles:
        play.tiles[0]["note"] = NUMBERS_ALONE
    if sheet:
        play.tiles.append(sheet)
    play.warnings = [w for w in play.warnings if w["code"] != "engine"]     # they were about the engine's play
    play.verb, play.kind, play.to = ("CHECK", "check", None) if free else ("FOLD", "fold", None)
    play.qualifier, play.sure, play.guard = "close: lower variance", "close", "close"
    play.reason, play.plans = reason, []
    play.flip = NUMBERS_AGAIN
    play.source = f"CLOSE: before the money the lower-variance side leads (engine: {engine})"
    play.chart = hero_cell_as_played(play.chart, seen.hand_class, play.kind)


def keep_the_plan(seen: Seen, play: Play, off: str) -> None:
    """Hero raised small to call any all-in and the all-in came: CALL.  The guard had its say at the raise.

    ``off``: why the guard does not apply to this hand at all ("in the
    money", ...), or "".  The plan holds there too: the raise was made to
    call, so the engine's second thoughts become the second line.
    """
    if play.kind == "fold":
        play.also = f"By the numbers alone now: {engine_summary(play)}."
        play.verb, play.kind, play.to, play.sure = "CALL", "call", None, "standard"
        play.reason = "You raised to call any all-in, and here it is: call. Folding now gives up the chips you raised."
        play.flip = ""
        play.chart = hero_cell_as_played(play.chart, seen.hand_class, "call")
    play.guard, play.source = "off", f"GUARD OFF ({off or 'decided at your raise: call any all-in'})"


def decide_now(play: Play) -> None:
    """A premium hand that could not call an all-in over its small raise on the bubble: all-in or fold, now."""
    play.verb, play.kind, play.to, play.qualifier = "ALL-IN", "allin", None, ""
    play.reason = "A premium hand, but on the bubble the sheet folds it to an all-in over a small raise. Do not " \
                  "raise and then fold: move all-in now."
    play.also, play.plans = "", []


def plan_after_guard(seen: Seen, money: Money, raise_to: float, line: str, strict: bool, near: bool,
                     exact: dict | None = None) -> str:
    """A plan line under hero's raise, with the guard's say.

    "If BB (28bb) moves all-in: CALL" is the engine's plan; the next answer
    goes through the guard.  So the same rules are applied here, with the
    numbers of the line, and a call the guard would fold reads FOLD.
    ``exact``: the engine's unrounded (need, have) by player (``plan_numbers``).
    """
    found = PLAN_LINE.fullmatch(line)
    if not found or found.group(3) != "CALL":
        return line
    who, stack, _verdict, need, have = found.groups()
    shover = next((i for i in range(seen.n) if i != seen.hero and seen.who(i) == who), None)
    if shover is None:
        return line
    why = call_after_my_raise_folds(seen, money, shover, raise_to, (int(need), int(have)), strict, near,
                                    (exact or {}).get(who))
    return line if not why else f"If {who} ({stack}bb) moves all-in: FOLD (need {need}%, have {have}%: {why})"


def call_after_my_raise_folds(seen: Seen, money: Money, shover: int, raise_to: float, points: tuple,
                              strict: bool, near: bool, exact: tuple | None = None) -> str:
    """Hero raises to ``raise_to`` and this player moves all-in: why the guard folds the engine's call, or "".

    ``points`` are (need, have) in whole points, as the line shows them; ``exact`` the same two unrounded.
    The engine marks its answer to the all-in "close" by the unrounded pair, so "close" is judged by it here.
    """
    if seen.types[shover] in RAISES_TOO_WIDE:
        return ""                                           # a read on him lifts the guard
    setup, hero = seen.setup, seen.hero
    matched = min(setup.live[hero], setup.live[shover])     # what the two can put in against each other
    call, left = matched - raise_to, setup.live[hero] - raise_to
    if call <= 0 or left <= 0:
        return ""
    others = sum(blind for i, blind in enumerate(setup.blinds) if i not in (hero, shover))
    pot = sum(setup.antes) + others + raise_to + matched
    if good_price(call / (pot + call), points):
        return ""                                           # a good price is never folded
    if call < COMMIT_SHARE * left:
        edge = 100 * (exact[1] - exact[0]) if exact else points[1] - points[0]
        return "close" if abs(edge) < ENGINE_CLOSE_POINTS else ""
    row = sheet_row_over_my_raise(seen, money, seen.bbs(min(seen.start[hero], seen.start[shover])))
    if row is None or in_range(row, seen.hand_class):
        return ""
    if strict or thin_call(points, near):
        return "too thin before the money" if not strict else "the sheet folds it before the money"
    return ""


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


def table_answer(seen: Seen, money: Money, before: Before, bubble_charts: bool = False,
                 at_risk: float | None = None, sized: bool = False, calling: bool = False) -> TableSays | None:
    """The all-in or fold answer for a tournament spot, by the stage rules; ``None`` when no table has a row.

    Far from the money the tables are read as they are.  Close to it the
    column for twice the stack is read.  On the bubble calls come from the
    bubble table; with ``bubble_charts`` (the all-in plan) the first-in and
    raise spots come from the late-registration charts by the sit-out line.
    In the money the "money" tables apply, and at a final table a call
    against a player who covers hero comes from the bubble table again.

    ``at_risk`` is the stack the play really risks, in big blinds (the
    guard passes it); without it the effective stack is read.  ``sized``:
    the play is a re-raise that is not an all-in, which the "aces and kings
    only" rule for moving all-in with more than 40bb is not meant for: it is
    read from the deepest row at most.

    ``calling``: the play asked about is a call (the guard says so).  It
    matters for one all-in and a player who called it.  A caller who is
    all-in himself makes that "two all-ins".  A caller who still has chips
    does not when hero only calls: the engine's CALL there is a call of the
    short all-in with a caller in the pot (``preflop.vs_shove(callers=...)``),
    so the row for that one all-in is read.  A re-raise over the two of them
    plays for the caller's chips as well, and the all-in plan has one
    decision for the whole hand: both keep the "two all-ins" row.
    """
    hero, hand, start = seen.hero, seen.hand_class, seen.start
    players = table_players(seen.n)
    behind = min(seen.behind(hero), players - 1)
    eff = seen.bbs(effective_stack(seen)) if at_risk is None else at_risk
    stage = "money" if money.in_money else "before"
    column = eff * 2 if money.close else eff                # close to the money: the column for twice the stack
    twice = f", and this close to the money your {bb_number(eff)}bb counts double" if money.close else ""
    if sized or (at_risk is not None and money.close and eff <= BN.TOP):
        # For the guard: "aces and kings only" is the rule for a stack of more than 40bb that moves all-in.  A
        # stack of 21bb read at twice its size, and a re-raise that is not an all-in, read the deepest column
        # the table has.  (The all-in plan keeps its own rule: a hand must be good for twice the stack.)
        column = min(column, float(BN.TOP))
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
        with_chips = [i for i in before.callers if seen.state.stack[seen.order[i]] > 0]
        caller_in_pot = calling and bool(with_chips)
        callers = len(before.callers) - (len(with_chips) if calling else 0)
        if len(all_ins) >= 2 or len(before.raises) + callers >= 2:
            action, why = BN.decide(hand, behind, eff, stage, "allins", None, size, bubble, players)
            row, title = BN.call("two", size, bubble, behind == 0, players), "two all-ins"
        else:
            shover = seen.behind(all_ins[0].idx)
            action, why = BN.decide(hand, behind, eff, stage, "allin", shover, size, bubble, players)
            row = BN.call(BN.shover_kind(shover), size, bubble, behind == 0, players)
            title = f"an all-in from {seen.label(all_ins[0].idx)}" + (" with a caller in the pot" if caller_in_pot else "")
        chart = range_chart(f"All-in chart: calling {title}, {bb_number(size)}bb", seen.hand_name,
                            {"c": parse_range(row)}, legend=(("c", "Call"), ("f", "Fold")))
        why = why.replace(": ", " the chart calls with ", 1)
        if caller_in_pot:                       # the caller still has chips: hero's call is of the all-in only
            why += " (a caller is in the pot; the call is of the all-in only)"
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
        chart = range_chart(f"All-in chart: over a raise from {seen.label(before.raises[0].idx)}, "
                            f"{bb_number(column)}bb", seen.hand_name, {"r": parse_range(row)},
                            legend=(("r", "All-in"), ("f", "Fold")))
        return TableSays(action, why.replace(": ", " the chart moves all-in with ", 1) + twice, row, chart)
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
    why = own_seat_in_words(why)
    if before.limpers:
        why = "behind callers the range of the seat before yours applies: " + why
    chart = first_in_table_chart(seen, stage, seat, column, players, bool(before.limpers))
    return TableSays(action, why + twice, short, chart, sure)


SEAT_FROM = {"UTG": "under the gun", "UTG+1": "UTG+1", "LJ": "the lojack", "HJ": "the hijack", "CO": "the cutoff",
             "BTN": "the button", "SB": "the small blind", "BB": "the big blind"}


def own_seat_in_words(why: str) -> str:
    """ "KQs from BTN is an all-in only up to 28bb" with the seat said in words: "KQs from the button is ..." """
    found = re.match(r"(\S+) from (\S+) is ", why)
    if not found or found.group(2) not in SEAT_FROM:
        return why
    return f"{found.group(1)} from {SEAT_FROM[found.group(2)]} is " + why[found.end():]


def first_in_table_chart(seen: Seen, stage: str, seat: int, column: float, players: int, callers: bool) -> dict:
    """The all-in table's first-in range for a seat and a stack; each cell knows its deepest stack."""
    weights = BN.first_in_range(stage, seat, column, players)
    limits = BN.limits(stage, seat, players)
    numbers = [f"all-in up to {limit}bb" if limit else "never an all-in" for limit in limits]
    title = f"All-in chart: {SEAT_TITLES.get(BN.seat_name(seat, players), 'seat').lower()}, first in, {bb_number(column)}bb"
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
        return f"The all-in chart never moves in with {seen.hand_name} from this seat {where}."
    return f"The all-in chart moves in with {seen.hand_name} up to {limit}bb from this seat {where}."


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
        engine.warnings.append(outside_tables("The all-in or fold charts have no row for this spot: "
                                              "this is the answer with all moves."))
        return engine
    action, reason = says.action, sentence(says.why)
    if action == "CALL" and any(r.kind != "allin" for r in before.raises) and seen.state.stack[HERO] > seen.to_call:
        # The table calls a raise it reads as an all-in (a third of the raiser's stack), but that player still
        # has chips: a call would leave a decision on the flop, and this plan has one decision a hand.
        action = "ALL-IN"
        reason += " The raiser is not all-in yet, so move all-in yourself: this plan never just calls."
    kind = {"ALL-IN": "allin", "CALL": "call", "CHECK": "check"}.get(action, "fold")
    play = Play(verb=action, kind=kind, sure=says.sure, reason=reason, chart=says.chart,
                source="all-in or fold table", also=f"With all moves, on these stacks: {engine_summary(engine)}.")
    if says.short and before.kind in ("first_in", "limped"):
        play.tiles.append(tile("The chart", says.short, f"{seen.hand_name} from this seat"))
    for number in engine.tiles:
        if number["label"] in ("All-in against folding", "Need / have"):
            number["note"] = "with all moves, " + value_note(money)
            play.tiles.append(number)
            break
    eff_bb = seen.bbs(effective_stack(seen))
    if seen.n >= 9:
        play.warnings.append(outside_tables("Nine players: answered from the chart for eight."))
    facing_all_in = [r for r in before.raises if r.kind == "allin" or r.amount >= RAISE_IS_ALLIN * seen.start[r.idx]]
    if facing_all_in:
        size = min(seen.start[seen.hero], max(seen.start[r.idx] for r in facing_all_in)) / seen.bb
        if size > BN.TOP:
            play.warnings.append(outside_tables(f"An all-in of more than {BN.TOP}bb: the call is read from the "
                                                f"chart's {BN.BANDS[-1][0]} column."))
    elif eff_bb > BN.TOP:
        play.warnings.append(outside_tables(f"Over {BN.TOP}bb the all-in plan only moves all-in with aces and kings."))
    if money.bubble and sit_out_zone(seen, money) is None and before.kind in ("first_in", "limped", "raise"):
        if (money.stage.get("remaining") or 0) > (money.stage.get("paid") or 0):
            play.warnings.append(warning("charts_loading", "The bubble charts are still being worked out: this "
                                         "answer reads the column for twice your stack.", "bubble charts loading"))
    return play


def outside_tables(text: str) -> dict:
    return warning("outside_tables", text, "outside the charts")


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
            play.warnings.append(outside_tables("The spin charts have no row for this spot: answered with all "
                                                "moves, on chips."))
        else:
            edge = SP.edge(row, eff, seen.hand_class)
            play.source = f"chip-EV engine: over {table_top}bb a small raise beats all-in or fold"
            play.also = f"All-in instead: {signed_bb(edge)} against folding (the spin chart)."
        return play
    vs = callers_profile(seen) if first_in else "solid"     # only the first-in ranges change for loose callers
    action, _why = SP.decide(seen.hand_class, row, eff, vs)
    if row in SP.OPENERS and action in ("FOLD", "CHECK") and seat == "BB" and eff > SPIN_TABLE_BB:
        engine = spin_engine_play(seen)                     # deep in the big blind a call may be right
        if engine.kind == "call":
            engine.source = "chip-EV engine: the table folds, the price allows a call"
            return engine
    # A raise read as an all-in comes back as CALL.  The raiser still has chips, and the spin tables never
    # just call a raise: the play is ALL-IN.
    raised_not_all_in = any(r.kind != "allin" for r in before.raises)
    if action == "CALL" and raised_not_all_in and seen.state.stack[HERO] > seen.to_call:
        action = "ALL-IN"
    play = spin_table_play(seen, row, eff, vs, action, raised_not_all_in)
    if len({round(s, 2) for s in seen.start}) > 1:
        play.warnings.append(outside_tables(f"Stacks differ: answered for the effective stack "
                                            f"({bb_number(eff)}bb), an approximation."))
    return play


def spin_all_ins(seen: Seen, before: Before) -> tuple[list, list]:
    """(the raises the spin tables read as all-ins, the players who called all-in), by index.

    An all-in is one.  So is a raise bigger than a small one that puts in a
    third of the raiser's stack: he will not fold.  A small raise (2.5bb or
    less) has its own rows, and ``spin.decide`` reads those as an all-in by
    itself when the stack is 5.5bb or less.
    """
    start = seen.start
    raises = [r for r in before.raises if r.kind == "allin"
              or (r.amount > SMALL_RAISE_BB * seen.bb and r.amount >= RAISE_IS_ALLIN * start[r.idx])]
    callers = [i for i in before.callers if seen.state.stack[seen.order[i]] <= 0]
    return raises, callers


def spin_effective_bb(seen: Seen, before: Before) -> float:
    """The effective stack in big blinds; against all-ins, the biggest of them or hero's stack if smaller."""
    start, hero = seen.start, seen.hero
    all_ins, callers = spin_all_ins(seen, before)
    if all_ins:
        # an all-in is worth what is in front of the player; a raiser who is not all-in yet is worth his stack
        sizes = [r.amount if r.kind == "allin" else start[r.idx] for r in all_ins] + [start[i] for i in callers]
        return min(start[hero], max(sizes)) / seen.bb
    return effective_stack(seen) / seen.bb


def spin_row(seen: Seen, before: Before) -> str | None:
    """The row of the spin tables for this spot, or ``None`` when they have none.

    Three players sit BTN, SB, BB; heads-up the button is the small blind.
    """
    if before.hero_raise or before.hero_called:
        return None                             # hero acts a second time: no table
    seats = ["BTN", "SB", "BB"] if seen.n == 3 else ["SB", "BB"]
    me = seats[seen.hero]
    all_ins, all_in_callers = spin_all_ins(seen, before)
    small = [r for r in before.raises if r not in all_ins]
    # a player who called an all-in with all his chips is all-in too: "both are all-in"
    all_in_seats = tuple(seats[i] for i in sorted([r.idx for r in all_ins] + all_in_callers))
    live_callers = [i for i in before.callers if i not in all_in_callers]
    if not before.raises and not before.limpers:
        return {"BTN": "btn", "SB": "sb" if seen.n == 3 else "hu_sb"}.get(me)
    if all_ins and not small and not before.limpers and not live_callers:
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


def callers_profile(seen: Seen, moved_in: tuple = ()) -> str:
    """Solid, loose or very-loose, for the Spin and All-In or Fold tables.

    The loose tables assume every opponent calls too much, so they are used
    only when every player still to act does: by his own tag, else by the
    table-wide setting.  When nobody acts after hero (the big blind) the
    table is judged by the players who have already moved all-in
    (``moved_in``): the second of them called the first.
    """
    setting = seen.data["config"].get("opponents")
    profiles = []
    for index in list(range(seen.hero + 1, seen.n)) or list(moved_in):
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
        play.warnings.append(close_warning(engine_facts(adv), before, None, play))
    return play


def spin_table_play(seen: Seen, row: str, eff: float, vs: str, action: str, raised_not_all_in: bool = False) -> Play:
    """An answer of the spin tables, with the numbers behind it.

    ``raised_not_all_in``: a raise in front is read as an all-in although
    that player still has chips, so a hand that plays moves all-in.
    """
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
        if calling and raised_not_all_in:
            # the row is "... is all-in": say that the raise is read as one, and what to do about the chips behind
            does = " He still has chips, so move all-in yourself" if action == "ALL-IN" else ""
            play.reason = sentence(f"One prize, so chips are money. A raise this big for the stack will not be folded, "
                                   f"so it is read as an all-in: {name} is {inside} the {percent(width / 100)} of hands "
                                   f"that play against it ({bb_number(eff)}bb).{does}")
        else:
            play.reason = sentence(f"One prize, so chips are money: {name} is {inside} the {percent(width / 100)} of "
                                   f"hands that {'call' if calling else 'move all-in'} here ({label}, {bb_number(eff)}bb)")
        profile = {"loose": "loose", "very-loose": "vloose"}.get(vs, "solid")
        note = "close to a coin flip: either play is fine" if abs(edge) < 0.05 else "against " + SP.PROFILE_NAMES[profile]
        what = "Calling" if calling and not raised_not_all_in else "All-in"
        play.tiles = [tile(what + " against folding", signed_bb(edge), note, sign_of(edge)),
                      tile("This seat plays", percent(width / 100), f"chart read at {SP.nearest(eff)}bb")]
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
    mask, moved_in = 0, []
    for act in seen.acts:                       # every action that is not a fold is an all-in here
        if act.idx < hero:
            mask |= 1 << act.idx
            moved_in.append(act.idx)
    family = AOF.family_for("cash", callers_profile(seen, tuple(moved_in)))
    answer = AOF.decide(seen.hand_class, n, hero, mask, list(seen.start), family)
    calling = mask != 0
    moves_in = answer.action == "ALL-IN"
    verb = ("CALL" if calling else "ALL-IN") if moves_in else "FOLD"
    close = abs(answer.ev) < AOF.CLOSE_EV
    seat_plays = "calls" if calling else "moves all-in"
    # Against an all-in the play is a call: the headline shows what is still to pay, and Follow says "call".
    kind = ("call" if calling and seen.to_call > 0 else "allin") if moves_in else "fold"
    play = Play(verb=verb, kind=kind, sure=answer.confidence,
                source="All-In or Fold table: " + AOF.FAMILY_LABEL.get(answer.family, answer.family))
    still_to_act = [i for i in range(hero + 1, n) if not seen.away[i] and seen.state.stack[seen.order[i]] > 0]
    if kind == "call" and still_to_act and seen.state.stack[HERO] > seen.to_call:
        play.qualifier = "all your chips go in"         # in this game a call is an all-in, and a player behind can call it
    play.reason = sentence(f"{answer.hand} is {'inside' if moves_in else 'outside'} the {answer.range_pct:.0f}% of hands "
                           f"this seat {seat_plays} with at {bb_number(answer.stack)}bb effective")
    play.tiles = [tile(("Calling" if calling else "All-in") + " against folding", signed_bb(answer.ev),
                       "a coin flip: either play is fine" if close else "the 0.1bb fee is counted", sign_of(answer.ev)),
                  tile("This seat plays", f"{answer.range_pct:.0f}%", f"{bb_number(answer.stack)}bb effective")]
    if close:
        play.flip = "Under 0.05bb the two plays are worth the same."
    for note in answer.notes:
        if note.startswith("stacks differ") or "outside the solved range" in note:
            play.warnings.append(outside_tables(sentence(plain(note))))
        else:
            play.warnings.append(warning("engine", sentence(plain(note))))
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
    """Equity against each opponent's range, narrowed by what he did; then the adapter's own rules.

    The engine answers first.  Then, in this order: no pair and no draw folds
    to a real bet from a player who did not raise before the flop; the
    playbook's one-pair rule; before the money a close call or bluff gives way
    to the quieter play; and in the all-in plan the free-flop rule.
    """
    if seen.cards is None:
        raise ValueError("after the flop the exact cards are needed")
    state = seen.state
    board = parse_cards("".join(seen.hand["board"]))[:STREET_CARDS[state.phase]]
    everyone = [seat for seat in state.live() if seat != HERO]
    if not everyone:
        raise ValueError("nobody else is in the hand")
    made = describe(seen.cards, board)          # what hero holds: top pair, a flush draw, the outs
    # A player who is sitting out checks when it is free and folds to any bet: he has no hand to play against.
    # (One who is all-in, from posting a blind, cannot fold: he stays an opponent, with any two cards.)
    absent = [seat for seat in everyone if seat in state.away and state.stack[seat] > 0]
    opponents = [seat for seat in everyone if seat not in absent]
    if absent and not any(state.stack[seat] > 0 for seat in opponents) and seen.to_call <= 0 and seen.legal.get("bet"):
        return bet_into_absent_players(seen, made, absent)
    if not opponents:
        opponents = everyone
    entered = preflop_roles(seen)
    lines, aggressor = street_lines(seen)
    main = main_opponent(seen, opponents, aggressor)
    villains, unknown = [], False
    for seat in [main] + [s for s in opponents if s != main]:
        index = seen.order.index(seat)
        if seat not in entered.roles:           # nothing recorded for him before the flop: read as a caller
            unknown = True
        weights, did = range_for(seen, seat, entered)
        villains.append(Villain(weights, seen.types[index], lines.get(seat, []), f"{seen.who(index)}: {did}",
                                pfr=seat == entered.last_raiser))
    # After the flop the small blind acts first and the button last: hero is in position when he acts after
    # everybody who can still act.
    rank = {seat: k for k, seat in enumerate(postflop_order(seen.order))}
    acting = [seat for seat in opponents if state.stack[seat] > 0] or opponents
    in_position = all(rank[HERO] > rank[seat] for seat in acting)
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
    # The stack that matters is the deepest one that can still call hero, not the main opponent's: with three
    # players a short or all-in bettor leaves a deeper player to play against.
    can_lose = matchable(seen, opponents)
    spot = PostflopSpot(hero=seen.cards, board=board, pot=pot, to_call=to_call, hero_stack=state.stack[HERO],
                        villain_stack=chips_beyond_the_call(seen, opponents), villains=villains, in_position=in_position,
                        hero_pfr=entered.last_raiser == HERO, facing=facing, bb=seen.bb, risk_premium=risk,
                        iters=POSTFLOP_ITERS)
    adv = advise_postflop(spot)
    main_index = seen.order.index(main)
    told = Told(street=state.phase, facing=facing, raised=to_call > 0 and state.raises >= 2,
                bet_share=to_call / max(pot - to_call, 1e-9) if to_call > 0 else 0.0,
                ptype=seen.types[main_index], who=seen.who(main_index), tagged=seen.tags[main_index] != "unknown",
                bettor_raised_preflop=main == entered.last_raiser, hero_bet=hero_bet_this_street(seen),
                pots_behind=pots_behind_at_street_start(seen, main), can_lose=can_lose,
                least_pots_behind=min(pots_behind_at_street_start(seen, seat) for seat in acting),
                aggressive_behind=any(seen.types[seen.order.index(seat)] in AGGRESSIVE_TYPES for seat in acting),
                pots_after_call=0.0 if len(everyone) > 1 else
                min(state.stack[HERO] - to_call, state.stack[main]) / max(state.pot_total() + to_call, 1e-9))
    play = play_after_flop(seen, adv, made, len(board), told, opponents)
    play.source = "after the flop: equity against an estimated range, a rule-based line"
    if unknown:
        play.warnings.append(warning("preflop_unknown", "No action is recorded for an opponent before the flop: "
                                     "he is read as a caller.", "an opponent read as a caller"))
    no_pair_no_draw(play, made, told)
    playbook_check(play, made, told)
    close_after_the_flop(seen, money, adv, play, told)
    if seen.mode == "tournament" and seen.data["config"].get("plan") == "allin":
        return free_flop_rule(seen, play, made, pot, can_lose, told)
    return play


@dataclass
class Told:
    """What the adapter's own rules after the flop need to know about the spot."""
    street: str                 # flop, turn or river
    facing: str | None          # None, "raise" or "shove", as the engine was told
    raised: bool                # hero faces a raise: a bet and a raise were made on this street
    bet_share: float            # what hero must call, as a share of the pot before his call
    ptype: str                  # the type of the player the decision is about (his tag, else the table's setting)
    who: str                    # that player, for a sentence
    tagged: bool                # the type is the user's own tag on that seat
    bettor_raised_preflop: bool     # he was the last to raise before the flop: his flop bet is a continuation bet
    hero_bet: bool              # hero's own bet on this street is what was raised
    pots_behind: float          # hero's chips against that player when the street began, in pots of that moment
    can_lose: float             # the chips hero can still put in and have matched
    least_pots_behind: float = 0.0      # the same against the shortest opponent who can still act ...
    aggressive_behind: bool = False     # ... and whether one of them is tagged lag or maniac
    pots_after_call: float = 0.0        # heads-up: the pots behind with which the next street begins if hero calls

    @property
    def draw_street(self) -> bool:
        return self.street != "river"


def bet_into_absent_players(seen: Seen, made: dict, absent: list) -> Play:
    """Every player who could still act is sitting out: the smallest bet wins the pot."""
    who = "The player" if len(absent) == 1 else "Every player"
    return Play(verb="BET", kind="bet", to=seen.legal["bet"]["min"], sure="clear",
                reason=f"{who} left in the hand is sitting out and folds to any bet: bet the minimum and take the pot.",
                tiles=[tile("You hold", made["made"].split(" (")[0], made["texture"]["label"])],
                source="after the flop: nobody is there to call")


def chips_beyond_the_call(seen: Seen, opponents: list) -> float:
    """What the deepest opponent who still has chips could put in beyond hero's call: the engine's "villain stack".

    Not capped by hero's own stack (the engine does that): a player who bet
    and has chips left is not all-in because hero is the short one.  Zero
    when nobody has chips left.
    """
    state = seen.state
    with_chips = [seat for seat in opponents if state.stack[seat] > 0]
    if not with_chips:
        return 0
    deepest = max(state.in_front[seat] + state.stack[seat] for seat in with_chips)
    return max(0, deepest - state.in_front[HERO] - seen.to_call)


def matchable(seen: Seen, opponents: list) -> float:
    """The chips hero can still put in on this street and have matched: the smaller of his stack and what the
    deepest opponent who still has chips can reach.  When nobody has chips left it is what hero must call."""
    return min(seen.state.stack[HERO], seen.to_call + chips_beyond_the_call(seen, opponents))


def pots_behind_at_street_start(seen: Seen, main: int) -> float:
    """Hero's chips against the main opponent when this street began, in pots of that moment.

    The playbook decides commitment before betting, not after: this number
    is the same for every answer of one street, whatever was bet since.
    """
    state = seen.state
    started = state.pot_total() - sum(state.in_front.values())
    mine = state.stack[HERO] + state.in_front[HERO]
    theirs = state.stack[main] + state.in_front[main]
    return min(mine, theirs) / max(started, 1e-9)


def hero_bet_this_street(seen: Seen) -> bool:
    """Hero's last action on this street was a bet (not a call, not a raise)."""
    mine = [entry for entry in seen.state.log if entry["street"] == seen.state.phase and entry["seat"] == HERO]
    return bool(mine) and mine[-1]["kind"] == "bet"


@dataclass
class Entered:
    """How the players came into the pot before the flop."""
    roles: dict = field(default_factory=dict)       # {seat: role}, see ``preflop_roles``
    opener_behind: int | None = None                # players behind the first raiser
    last_raiser: int | None = None                  # the seat of the last raise (a short all-in is not one)
    callers_in_front: dict = field(default_factory=dict)    # {seat: the callers in the pot when he raised over them}
    answered: dict = field(default_factory=dict)    # {seat: (seat, total)}: the raise or all-in he called or raised over


def preflop_roles(seen: Seen) -> Entered:
    """How each player entered the pot, the players behind the first raiser, the last raiser.

    Roles:

        open        the first raise                     iso         a raise over players who only called
        3bet        a re-raise                          4bet        a further re-raise
        push        an all-in when nobody had raised    reshove     an all-in over a raise
        iso_short   a raise over a short all-in         iso_push    a raise over a real all-in
        call        called a raise                      call3       called a re-raise
        callpush    called an all-in                    limp        called the big blind
        check       the big blind saw a free flop

    An all-in of less than a full raise, or under ``SHORT_ALLIN_BB`` big
    blinds, is not "a raise": the next player's ordinary raise is still the
    first one.  A player who raised and then called a re-raise or an all-in is
    read by that call; one who limped and then called a raise stays a limper.
    """
    state = seen.state
    entered = Entered()
    roles = entered.roles
    level, full_raise = state.bb, state.bb      # the bet to match, and the size of a full raise over it
    raises: list = []                           # (seat, total, all-in) of every real raise, hero's included
    short_pushes, limpers = [], []
    for entry in state.log:
        if entry["street"] != "preflop":
            continue
        seat, kind, to = entry["seat"], entry["kind"], entry["to"]
        if kind in ("bet", "raise"):
            is_full = to - level >= full_raise - 1e-9
            if entry["allin"] and (not is_full or to < SHORT_ALLIN_BB * state.bb):
                roles[seat] = "push"            # a short stack's last chips: any raise after it is still the first
                short_pushes.append(seat)
            else:
                small = [r for r in raises if not r[2]]         # the raises that were not all-in
                if not raises:
                    roles[seat] = "push" if entry["allin"] else "iso" if limpers else \
                        "iso_short" if short_pushes else "open"
                    entered.callers_in_front[seat] = list(limpers)
                elif not small:                 # only all-ins so far: he plays against the all-in player's range
                    roles[seat] = "callpush" if entry["allin"] else "iso_push"
                    entered.answered[seat] = raises[-1][:2]
                elif len(small) == 1:
                    roles[seat] = "reshove" if entry["allin"] else "3bet"
                    entered.answered[seat] = small[0][:2]
                else:
                    roles[seat] = "4bet"        # over a re-raise, all-in or not: the top of the range
                raises.append((seat, to, entry["allin"]))
            if is_full:
                full_raise = to - level
            level = max(level, to)
        elif kind == "call":
            small = [r for r in raises if not r[2]]
            if raises and raises[-1][2]:
                roles[seat] = "callpush"        # he called an all-in, whatever he had done before
                entered.answered[seat] = raises[-1][:2]
            elif len(small) >= 2:
                roles[seat] = "call3"           # he called a re-raise: cold, or after his own raise
            elif small:
                roles.setdefault(seat, "call")
            else:
                roles.setdefault(seat, "limp")
                limpers.append(seat)
        elif kind == "check":
            roles.setdefault(seat, "check")
    for seat in seen.order[-2:]:                # a blind that went all-in by posting holds any two cards
        if seat not in roles and state.stack[seat] <= 0 and seat not in state.folded:
            roles[seat] = "check"
    if raises:
        entered.opener_behind = seen.behind(seen.order.index(raises[0][0]))
        entered.last_raiser = raises[-1][0]
    return entered


CONTINUE_VS_RERAISE = {         # the hands that call a re-raise, by how tight the caller is
    "tight": "QQ-JJ, AKs, TT:0.5, AQs:0.5, AKo:0.5, AA:0.25, KK:0.25",
    "usual": "QQ-TT, AQs+, AKo, KQs, 99:0.5, AJs:0.5, KJs:0.5, QJs:0.5, JTs:0.5, AQo:0.5, AA:0.25, KK:0.25",
    "loose": "QQ-66, ATs+, A5s-A4s, KTs+, QTs+, JTs, T9s, 98s, AQo+, AJo:0.5, KQo:0.5, AA:0.5, KK:0.5",
}
ISOLATE_ALWAYS = "99+, AJs+, AQo+, KQs"         # raised over callers from any seat (the engine's own list)
CALLS_ANY_ALLIN = "TT+, AQs+, AKo"              # the least a player calls an all-in with, when nothing is solved


def range_for(seen: Seen, seat: int, entered: Entered) -> tuple[list, str]:
    """An opponent's range from what he did before the flop, and a word for it."""
    index = seen.order.index(seat)
    behind, ptype = seen.behind(index), seen.types[index]
    role = entered.roles.get(seat, "call")
    opener = max(1, 3 if entered.opener_behind is None else entered.opener_behind)
    kind = norm_type(ptype)
    if role == "open":
        return villain_open_range(behind, ptype), "raised first"
    if role == "iso_short":
        return villain_open_range(behind, ptype), "raised over a short all-in"
    if role == "iso":
        callers = entered.callers_in_front.get(seat) or [None]
        if behind == 0 and callers == [seen.order[-2]]:
            # blind against blind (heads-up too): the big blind raises the small blind's call with a wide range
            return villain_open_range(1, ptype), "raised over the small blind's call"
        return isolation_range(behind, ptype, len(callers)), "raised over the callers"
    if role == "push":
        return push_range(seen, index), "moved all-in"
    if role == "reshove":
        return reshove_range(seen, index, entered.answered.get(seat), opener), "moved all-in over a raise"
    if role == "iso_push":
        return call_all_in_range(seen, index, entered.answered.get(seat), True), "raised over an all-in"
    if role == "callpush":
        deep = seen.state.stack[seat] > 0       # chips behind: he could have folded, and others were still in
        return call_all_in_range(seen, index, entered.answered.get(seat), deep), "called an all-in"
    if role == "3bet":
        return threebet_range(opener, ptype), "re-raised"
    if role == "4bet":
        return threebet_range(opener, "nit"), "re-raised again"     # a second re-raise: the top of that range
    if role == "call3":
        how = "tight" if kind in ("nit", "tight") else "loose" if kind in LOOSE_TYPES else "usual"
        return parse_range(CONTINUE_VS_RERAISE[how]), "called a re-raise"
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
    if kind in LOOSE_TYPES:                     # tables that call too much call with far more
        extra = top_percent(35.0 if behind == 0 else 25.0, list(play_order()))
        weights = [max(w, 0.7 * e) for w, e in zip(weights, extra)]
    return weights, "called a raise"


def isolation_range(behind: int, ptype: str, callers: int) -> list:
    """A raise over players who only called, by seat: the engine's own isolation range.

    The opening range of the seat (the cutoff's, from the blinds), one line
    tighter for every caller, and always the strong hands.
    """
    seat = max(1, behind) if behind >= 2 else 3
    shift = PLAYER_TYPES[norm_type(ptype)]["open_shift"] + max(1, callers)
    return [max(a, b) for a, b in zip(rfi_range(seat, 100.0, shift), parse_range(ISOLATE_ALWAYS))]


def dealt_away(seen: Seen) -> list:
    """By index: sitting out when the hand was dealt."""
    away = set(seen.hand.get("away", ()))
    return [seat in away for seat in seen.order]


def widened(solution, ptype: str) -> list:
    """A solved all-in range, wider or narrower by the player's type (as the engine reads an all-in)."""
    share = range_pct(solution.shove_range) * PLAYER_TYPES[norm_type(ptype)]["shove_mult"]
    return scale_range(solution.ev, min(100.0, max(1.5, share)))


def push_range(seen: Seen, index: int) -> list:
    """An all-in when nobody had raised: the push range for that stack and seat."""
    try:
        solution = solve_open_shove(seen.setup, index, Prizes(), types=seen.types, away=dealt_away(seen),
                                    use_types=False)
        weights = widened(solution, seen.types[index])
    except Exception:                           # the chart for equal stacks is the next best thing
        weights = None
    if not weights or range_pct(weights) <= 0:
        weights = nash_push_range(seen.behind(index), seen.bbs(seen.setup.live[index]), bool(max(seen.setup.antes)))
    return weights


def reshove_range(seen: Seen, index: int, over, opener_behind: int) -> list:
    """An all-in over a raise: solved against the raiser's opening range, else the re-raising range."""
    try:
        raiser = seen.order.index(over[0])
        opens = villain_open_range(seen.behind(raiser), seen.types[raiser])
        solution = solve_reshove(seen.setup, index, raiser, over[1], Prizes(), opener_range=opens,
                                 types=seen.types, away=dealt_away(seen), use_types=False)
        weights = widened(solution, seen.types[index])
        if range_pct(weights) > 0:
            return weights
    except Exception:
        pass
    return threebet_range(opener_behind, seen.types[index])


def call_all_in_range(seen: Seen, index: int, called, deep: bool) -> list:
    """The hands that call an all-in: the preflop engine's calling range for that stack and seat.

    ``called`` is (the all-in player's seat, his total).  ``deep``: the
    caller had chips behind and players still in the hand, so he is read as
    tighter than the pot odds alone, the way the engine reads him.
    """
    weights, size_bb = None, 12.0
    try:
        shover = seen.order.index(called[0])
        size_bb = seen.bbs(called[1])
        if index > shover:                      # he acted after the all-in: the solved calling range
            solution = solve_open_shove(seen.setup, shover, Prizes(), types=seen.types, away=dealt_away(seen),
                                        use_types=False)
        else:                                   # he had raised (or called) and the all-in came over it
            mine = next((act.amount for act in seen.acts if act.idx == index), seen.bb)
            solution = solve_reshove(seen.setup, shover, index, mine, Prizes(),
                                     opener_range=villain_open_range(seen.behind(index), seen.types[index]),
                                     types=seen.types, away=dealt_away(seen), use_types=False)
        caller = solution.caller(index)
        if caller is not None and range_pct(caller.call_range) > 0:
            weights = list(caller.call_range)
    except Exception:
        weights = None
    if weights is None:                         # nothing solved: wider against a small all-in, QQ+ and AK against a big one
        weights = top_percent(min(45.0, max(3.0, 130.0 / max(size_bb, 1.0))), list(allin_order()))
    if deep:
        weights = top_percent(min(CALLER_WIDEST, CALLER_SHARE * range_pct(weights)), list(allin_order()))
    return [max(a, b) for a, b in zip(weights, parse_range(CALLS_ANY_ALLIN))]


def street_lines(seen: Seen) -> tuple[dict, int | None]:
    """What every opponent did on each street after the flop, and who bet or raised last in the hand.

    ``{seat: [(street, action, size)]}`` with the strongest action of each
    street: check, call, bet, raise or shove.  A bet's size is the chips put
    in over the pot before it; a call carries the size of the bet it called.
    The street being played is included, so the engine adds nothing itself.
    The check a player in front of hero has not made yet is left out: his
    range is not narrowed by it.
    """
    state = seen.state
    pot = sum(state.ante.values()) + state.dead + sum(state.blind.values())
    front = dict(state.blind)                   # chips in front of each player on the street being walked
    street, standing = "preflop", None          # ``standing``: the size of the bet that is there to be called
    lines: dict = {}
    aggressor = None
    for number, entry in enumerate(state.log):
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
        if number >= seen.known and seat in seen.pending:
            continue                            # he has not acted yet: the default was only assumed for him
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
    """The player the decision is about.

    Facing a bet: the player whose bet it is.  Nothing to call: among the
    players who still have chips, the last to bet or raise, else the biggest
    stack (a player who is all-in cannot be bet into).
    """
    state = seen.state
    if seen.to_call > 0:
        return max(opponents, key=lambda seat: (state.in_front[seat], seat == aggressor))
    with_chips = [seat for seat in opponents if state.stack[seat] > 0] or opponents
    if aggressor in with_chips:
        return aggressor
    return max(with_chips, key=lambda seat: state.stack[seat])


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


NOTHING_TO_BET = ("nothing strong", "No value and no good bluff")       # the engine's reasons for a check with air
FOLD_TO_A_RAISE = "fold to a raise unless"      # the engine's warning under a thin value bet with top pair
BLUFF_CATCHER = "a bluff-catcher"               # ... and under a call with a weak made hand: "fold to a big bet on
                                                # the next street unless you improve"


def play_after_flop(seen: Seen, adv, made: dict, board_cards: int, told: Told, opponents: list) -> Play:
    verb, kind, chips, qualifier = read_postflop_action(adv.action, seen.bb)
    state = seen.state
    # the engine's amount is what hero puts in now; the table wants his total in front on this street
    to = state.in_front[HERO] + chips if chips is not None else None
    if kind == "allin":
        # The engine's all-in is for the chips that can be matched.  While a deeper opponent is still in the
        # hand, hero's own all-in would risk more than that: then it is a bet or a raise of that amount.
        meant = state.in_front[HERO] + min(state.stack[HERO], told.can_lose)
        deeper = any(state.in_front[seat] + state.stack[seat] > meant + 1e-9 for seat in opponents)
        if meant < state.in_front[HERO] + state.stack[HERO] - 1e-9 and deeper:
            verb, kind, to = ("RAISE", "raise", meant) if seen.to_call > 0 else ("BET", "bet", meant)
    play = Play(verb=verb, kind=kind, to=to, qualifier=qualifier, sure=adv.confidence,
                reason=sentence(plain(adv.why[0])) if adv.why else "",
                also=sentence(plain(adv.alt[0])) if adv.alt else "")
    if kind == "check" and made["strength"] >= 5 and any(words in play.reason for words in NOTHING_TO_BET):
        # the engine's sentence for a check is written for a weak hand: beside "You hold: overpair" it reads wrong
        play.reason = "A good hand, but not one to bet for value here: keep the pot small and call one reasonable bet."
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
        if FOLD_TO_A_RAISE in text and not folds_to_a_raise(made, told):
            continue                            # the next answer would not fold: do not announce it
        if BLUFF_CATCHER in text:
            text = bluff_catcher_line(told)     # the same: only the fold that will really follow is announced
        play.warnings.append(warning("engine", sentence(plain(text))))
    if adv.confidence == "close":
        text = f"Close: you need {price.group(1)}% and have {price.group(2)}%." if price else \
            "Close: the other play is nearly as good."
        play.warnings.append(warning("close", text, "close"))
    return play


def engine_alone(play: Play) -> str:
    """A rule of this file takes the place of the engine's play: its summary for the second line, its numbers
    marked as the engine's own, and its warnings (they were about that play) dropped."""
    summary = engine_summary(play)
    for one in play.tiles:
        if one["label"] in ("Equity", "Need / have"):
            one["note"] = NUMBERS_ALONE
    play.warnings = [w for w in play.warnings if w["code"] not in ("engine", "close")]
    play.facts["by_rule"] = True
    return summary


def has_a_draw(made: dict, told: Told) -> bool:
    return told.draw_street and made["outs"] >= DRAW_OUTS


def folds_to_a_raise(made: dict, told: Told) -> bool:
    """Will a raise over hero's thin value bet be folded to, whoever makes it?

    The warning under the bet is shown only then, so the answer to the raise
    (``playbook_check``) never contradicts it: no draw to continue with,
    nobody who can raise is tagged lag or maniac, and 1.5 pots or more behind
    against every one of them.
    """
    return not told.aggressive_behind and not has_a_draw(made, told) \
        and told.least_pots_behind >= PLAYBOOK_POTS_BEHIND


def bluff_catcher_line(told: Told) -> str:
    """The warning under a call with a weak made hand, said so that the next answer keeps it.

    The engine says "fold to a big bet on the next street unless you
    improve", and then may well call that bet.  What this file does fold is
    one pair facing a big river bet (``playbook_check``), so that is what a
    call on the turn announces, heads-up, when the rule will apply on the
    river: not against a player tagged lag or maniac, and with 1.5 pots or
    more behind once the call is made.  Otherwise the line makes no promise.
    """
    if told.street == "turn" and told.ptype not in AGGRESSIVE_TYPES and told.pots_after_call >= PLAYBOOK_POTS_BEHIND:
        return f"A bluff-catcher: fold the river to a bet of {percent(PLAYBOOK_BIG_BET)} of the pot or more " \
               "unless you improve"
    return "A bluff-catcher: it beats a bluff and nothing else"


def no_pair_no_draw(play: Play, made: dict, told: Told) -> None:
    """No pair and no draw facing a real bet from a player who did not raise before the flop: fold.

    Only the raiser's flop bet is a continuation bet, made with any two
    cards.  A bet of half the pot from anybody else means a hand.
    """
    nothing = made["category"] == "high card" or (made["strength"] <= 1 and made["category"] in ("pair", "two pair"))
    if play.kind != "call" or not nothing or has_a_draw(made, told) or told.bettor_raised_preflop \
            or told.bet_share < NO_PAIR_BIG_BET:
        return
    engine = engine_alone(play)
    play.verb, play.kind, play.to = "FOLD", "fold", None
    play.qualifier, play.sure = "", "standard"
    play.reason = sentence(f"No pair and no draw against a bet of {percent(told.bet_share)} of the pot from "
                           f"{told.who}, who did not raise before the flop: that bet is a hand, fold")
    play.also = by_the_numbers(engine)
    play.flip = "A call with a pair or a draw of 8 outs, or against a small bet."


def playbook_check(play: Play, made: dict, told: Told) -> None:
    """The playbook's one-pair rule.  The engine alone would continue there.

    One pair and no draw, facing a big river bet or a raise on the turn or
    the river: fold.  And top pair with a medium or weak kicker folds to a
    raise over its own bet on any street: the plan the coach gave with that
    bet.  (Weaker hands are folded with them, so that a stronger hand never
    folds where a weaker one plays on.)  The engine's play stays against a
    player tagged lag or maniac, with fewer than 1.5 pots behind when the
    street began (the hand is committed), with a draw of 8 outs or more, and
    at a tiny price.
    """
    if play.kind not in ("call", "raise", "allin") or has_a_draw(made, told):
        return
    if told.ptype in AGGRESSIVE_TYPES or told.pots_behind < PLAYBOOK_POTS_BEHIND or told.bet_share <= TINY_CALL:
        return
    # one pair, or less: a hand without a draw that is weaker than one pair never plays on where one pair folds
    one_pair = made["category"] in ("high card", "pair") or \
        (made["category"] == "two pair" and made["made"] not in ("two pair", "top two pair"))
    big_river_bet = told.street == "river" and told.bet_share >= PLAYBOOK_BIG_BET
    raised = told.street in ("turn", "river") and told.raised
    thin_bet_raised = made["strength"] <= 4 and told.raised and told.hero_bet
    if not (one_pair and (big_river_bet or raised)) and not thin_bet_raised:
        return
    engine = engine_alone(play)
    passive = told.ptype in PASSIVE_TYPES
    whose = f"{told.who}, {'tagged' if told.tagged else 'read as'} {told.ptype}" if passive else told.who
    holding = "One pair" if made["category"] != "high card" else "No pair"
    if one_pair and (big_river_bet or raised):
        what = "a raise" if raised else "a big river bet"
        why = "such players rarely bluff there" if passive else "that is rarely a bluff"
        reason = f"{holding} facing {what} from {whose}: {why}, so the playbook folds"
    elif made["strength"] == 4:
        reason = f"You bet top pair without a strong kicker and {whose} raised: fold, as planned with the bet"
    else:
        reason = f"You bet a hand weaker than top pair and {whose} raised: fold"
    play.verb, play.kind, play.to = "FOLD", "fold", None
    play.qualifier, play.sure = "playbook check", "standard"
    play.reason = sentence(reason)
    play.also = by_the_numbers(engine)
    play.flip = "A call against a player tagged lag or maniac, or with less than 1.5 pots behind."


COMMITTED = "you are committed"                 # the engine's own close call with a strong pair and a short stack


def close_after_the_flop(seen: Seen, money: Money | None, adv, play: Play, told: Told) -> None:
    """A close call or bluff before the money: the quieter play leads, as before the flop.

    The headline is FOLD (CHECK when it is free) and the engine's play the
    second line.  Not in the money, at a final table, in the Max EV style,
    while re-entry is open, for a stack too short to wait, in Spin, against a
    player tagged lag or maniac, at a tiny price, and not where the engine
    says the hand is committed (the playbook takes that hand to showdown).
    """
    if money is None or adv.confidence != "close" or guard_is_off(seen, money):
        return
    bluff = play.kind in ("bet", "raise", "allin") and play.qualifier in ("semi-bluff", "c-bet")
    if play.kind != "call" and not bluff:
        return
    if play.kind == "call" and (told.bet_share <= TINY_CALL or told.ptype in AGGRESSIVE_TYPES
                                or any(COMMITTED in text for text in adv.why)):
        return
    what = "call" if play.kind == "call" else "bet" if seen.to_call <= 0 else "raise"
    quiet = "check" if seen.to_call <= 0 else "fold"
    engine = engine_alone(play)
    play.also = by_the_numbers(engine, max_ev=True)
    play.verb, play.kind, play.to = ("CHECK", "check", None) if quiet == "check" else ("FOLD", "fold", None)
    play.qualifier, play.sure, play.guard = "close: lower variance", "close", "close"
    play.reason = f"Close: the {what} and the {quiet} are worth about the same. Before the money the " \
                  f"lower-variance side leads: {quiet}."
    play.flip = NUMBERS_AGAIN
    play.source = f"CLOSE: before the money the lower-variance side leads (engine: {engine})"


def free_flop_rule(seen: Seen, engine: Play, made: dict, pot: float, can_lose: float, told: Told) -> Play:
    """The all-in plan after a free flop: all-in with top pair or better, or 12 outs, at 4 pots or less.

    "Behind" is what an opponent can still call, not hero's whole stack.  A
    hand that passes the strength test is never checked or folded by this
    rule: with more than 4 pots behind the full engine's play is the answer.
    When all the chips that can go in are in the bet hero faces, the all-in
    is a call and the headline says so.  And a weak hand is not folded at a
    tiny price (a tenth of the pot or less) when the engine calls.
    """
    strong = made["strength"] >= 4 or (made["outs"] >= FREE_FLOP_OUTS and seen.state.phase != "river")
    # what the plan "All moves" answers here: the engine's play with its numbers, or the rule that replaced it
    second = f"With all moves: {engine.verb}." if engine.facts.get("by_rule") else \
        f"With all moves: {engine_summary(engine)}."
    holds = tile("You hold", made["made"].split(" (")[0], made["texture"]["label"])
    source = "all-in plan: the playbook's rule"
    if not strong:
        if 0 < told.bet_share <= TINY_CALL and engine.kind == "call":
            engine.source = "all-in plan: a tiny price, the full engine's play"
            return engine
        verb, kind = ("CHECK", "check") if seen.to_call <= 0 else ("FOLD", "fold")
        return Play(verb=verb, kind=kind, sure="standard", also=second, source=source, tiles=[holds],
                    reason="No top pair and no 12-out draw: check, and fold to a bet.")
    if can_lose > FREE_FLOP_POTS * pot:
        engine.source = "all-in plan: more than 4 pots behind, the full engine's play"
        engine.flip = engine.flip or "All-in with 4 pots or less behind."
        return engine
    pots = tile("Pots behind", f"{can_lose / pot:.1f}", "all-in at 4 or less")
    if seen.to_call > 0 and not (seen.legal.get("raise") or seen.legal.get("bet")):
        return Play(verb="CALL", kind="call", sure="standard", also=second, source=source, tiles=[holds, pots],
                    reason="Top pair or better, or a draw with 12 outs, and 4 pots or less behind: call. "
                           "Every chip that can go in is in that bet.")
    return Play(verb="ALL-IN", kind="allin", sure="standard", also=second, source=source, tiles=[holds, pots],
                reason="Top pair or better, or a draw with 12 outs, and 4 pots or less behind: move all-in.")


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
            return range_chart(f"All-in chart: calling two all-ins, {bb_number(size)}bb", seen.hand_name,
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
    head = headline(seen, play)
    assumed = assumption(seen, short=True)
    if assumed and head["tone"] != "wait":
        # players in front of hero have not acted: the answer holds if they do the passive thing, and says so
        head["qualifier"] = f"{head['qualifier']}, {assumed}" if head["qualifier"] else assumed
        answer["provisional"] = assumption(seen)
    if play.kind == "allin" and head["follow"] == {"kind": "call"}:
        # the all-in came out as a call (``all_in_is_a_call``): the reason speaks of an all-in, so say why
        play.reason = (play.reason + " " if play.reason else "") + \
            "Nobody left can match more than the call, so the all-in is that call."
    answer.update(status="ready", headline=head, reason=play.reason, tiles=play.tiles,
                  flip=play.flip, also=play.also, plans=play.plans, chart=play.chart, guard=play.guard,
                  source=source_line(money, play),
                  warnings=shown_warnings(play.warnings + player_notes(seen) + standing))
    return answer


def headline(seen: Seen, play: Play) -> dict:
    """The verb, its size in big blinds and chips, the tone, and the intent that carries the advice out."""
    verb, kind, to, qualifier = play.verb, play.kind, play.to, play.qualifier
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
            if to < box["max"]:                 # (all the chips are all the chips: nothing to round)
                to = on_the_chips(seen, to)
            to = max(box["min"], min(to, box["max"]))
            if to >= box["max"]:
                verb, kind = "ALL-IN", "allin"
            else:
                kind = "bet" if legal.get("bet") else "raise"
    if kind == "allin" and all_in_is_a_call(seen, all_in):
        # Nobody still in the hand can match more than the call: the all-in is that call, and is said so
        # (the big blind is all-in from posting, and hero in the small blind only has to complete).
        verb, kind, qualifier = "CALL", "call", "all they can match"    # (the play's own pill was about the all-in)
    if kind == "wait":
        return {"verb": verb, "size_text": "", "qualifier": qualifier, "tone": "wait", "sure": "", "follow": None}
    if kind == "call":
        size_text, follow = size_words(seen, to_call), {"kind": "call"}
    elif kind in ("raise", "bet"):
        size_text = ("TO " if kind == "raise" else "") + size_words(seen, to)
        follow = {"kind": kind, "to": to}
    elif kind == "allin":
        # The move as the All-in button records it: hero's whole stack.  When nobody still in the hand can
        # match all of it, the pill says what is really at risk; the rest comes back.
        size_text, follow = (size_words(seen, all_in) if all_in else ""), {"kind": "allin"}
        at_risk = matched_words(seen, all_in) if all_in else ""
        if at_risk:
            qualifier = f"{qualifier}, {at_risk}" if qualifier else at_risk
    else:
        size_text, follow = "", {"kind": kind}
    tone = "passive" if verb in ("CALL", "CHECK") else "fold" if kind == "fold" else "attack"
    return {"verb": verb, "size_text": size_text, "qualifier": qualifier, "tone": tone, "sure": play.sure,
            "follow": follow}


def chip_step(seen: Seen):
    """The smallest chip the blinds of this hand are made of: 25 at 300/600 with an ante of 75."""
    level = seen.hand["level"]
    amounts = [level.get(key) or 0 for key in ("sb", "bb", "ante")]
    amounts = [amount for amount in amounts if amount]
    if not amounts or any(amount != int(amount) for amount in amounts):
        return 0.1 if seen.mode == "aof" else 1         # the table's own step (model.Session._step)
    return max(step for step in CHIP_STEPS if all(amount % step == 0 for amount in amounts))


def on_the_chips(seen: Seen, to):
    """A bet or a raise as an amount the table's chips can make.

    Before the flop sizes are tenths of a big blind and stay whole chips.
    After the flop they are a share of the pot: rounded to the table's chip
    (``chip_step``), so 1,155 becomes 1,150.  The caller keeps it legal.
    """
    step = chip_step(seen) if seen.state.phase != "preflop" else (0.1 if seen.mode == "aof" else 1)
    if step <= 1:
        return tidy(to, step)
    return step * tidy(to / step)


def matched_all_in(seen: Seen, all_in):
    """Hero's all-in as the amount that can be matched: the smaller of his all-in and the biggest total a
    player still in the hand can reach (a player sitting out folds, so his chips do not count)."""
    state = seen.state
    live = [seat for seat in state.live() if seat != HERO]
    rivals = [seat for seat in live if not (seat in state.away and state.stack[seat] > 0)] or live
    if not rivals:
        return all_in
    reach = max(state.in_front[seat] + state.stack[seat] for seat in rivals)
    return min(all_in, max(reach, state.in_front[HERO] + seen.to_call))


def matched_words(seen: Seen, all_in) -> str:
    """ "5.5bb of your 8bb can be matched" when hero's all-in is for more than any player still in the hand can
    match, else "".  The headline shows the all-in as the button records it (the whole stack), so the smaller
    number never stands on the screen without these words."""
    matched = matched_all_in(seen, all_in)
    if matched >= all_in - 1e-9:
        return ""
    return f"{bb_number(matched / seen.bb)}bb of your {bb_number(all_in / seen.bb)}bb can be matched"


def all_in_is_a_call(seen: Seen, all_in) -> bool:
    """Hero faces a bet, may not raise, and nobody still in the hand can match more than the call: his all-in
    would be recorded as that call.  (Not in All-In or Fold, where the first all-in has no call beside it.)"""
    if not all_in or seen.to_call <= 0 or seen.legal.get("call") is None or seen.legal.get("raise") or seen.legal.get("bet"):
        return False
    return matched_all_in(seen, all_in) <= seen.state.in_front[HERO] + seen.to_call + 1e-9


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
