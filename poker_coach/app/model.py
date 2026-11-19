"""The table model: what the browser shows and what the user can change.

Three layers, top to bottom of this file:

1. **Seats and positions.**  Hero always sits in seat 1; seats are numbered
   clockwise from him.  Seat names (UTG ... BB) come from the one table in
   ``poker_coach.ranges``.

2. **The hand machine.**  A hand is stored as its frozen start (who was dealt
   in, their stacks, the blinds, the button) plus a list of events.  One pure
   function, ``replay(hand)``, turns that into everything else: stacks, pot,
   who acts next, what it costs, side pots, the result.  ``replay`` is strict:
   an event that breaks the rules raises ``ModelError``.

3. **The session.**  ``Session.apply({"op": ...})`` is the single way in.  It
   is friendly where the machine is strict: players who were skipped take the
   passive default (check when free, fold otherwise), a bet above the stack
   becomes an all-in, a call with nothing to call becomes a check, a raise
   below the minimum is lifted to it.  Every accepted change is saved and can
   be undone.  ``Session.view()`` is the JSON the browser renders.

Each mode (tournament, spin, aof) has its own session file; the folder also
holds ``app.json`` with what is shared (the mode on screen, chips or big
blinds, the deck).

Intents and their arguments (text is always parsed here, never in the browser):

    new_session   mode, size, start_stack, hero_stack, level, ladder, button, and any tournament field or setting
    set_mode      mode
    set_tournament  remaining, paid, entrants, payouts, avg_stack, start_stack, buyin, name  (or field + text)
    remaining     delta (-1, +1, -10, +10) or value
    set_config    style, plan, opponents, pace, reentry_open, bounty, button_rule (dead, forward), short_post,
                  unit, deck, notice_seen, tally
    level_up, level_down
    set_level     text ("300/600/75" or "600"), or sb, bb, ante
    set_ante_kind kind (none, player, bb); without it the kind cycles
    set_ladder    name (a preset), or text (one level per line), or levels
    set_size      size, or delta; clear (true: the players above a smaller size moved away)
    new_table     size, button                     (a table move: hero and the tournament stay)
    set_button    seat (an empty seat too: a dead button)       button_step   step (+1, -1)
    seat_player   seat, name, stack, type          clear_seat  seat          bust  seat
    set_stack     seat, text                       set_stacks  values (one per seat; "" keeps, "-" empties)
    set_status    seat, status (active, away); without it the status flips
    rename        seat, name      set_type  seat, type      note  seat, text
    deal          hero_cards (optional)
    set_cards     hero, board, shown; or slot (hero, flop, turn, river, board) + text; replace (see below)
    act           seat (default: the target), kind (fold check call bet raise allin), amount, force, advice
    close_round   callers (seats that call; everybody else left to act takes the default)
    edit_event    index (the "i" of the hand line), kind, amount, seat
    remove_event  index
    award         ranking [[seats], [seats]] best hand first; or winner, winners, hero (won, lost, split)
    skip_hand     hero_in       discard_hand       new_game  start_stack (Spin)
    undo, redo

Every intent may also carry ``rev``, the revision of the view it was made on.  When the table has
changed since, nothing is done and the refusal has the code ``stale``.

The view is the shape in the build spec, with a few additions the screens
need: ``first_run``, ``hero_out`` (hero has no chips and no hand of his is running), ``unsaved``
(why the files do not hold the last change, else ""), ``settings`` (ladders, the levels, the
notice flag, the key map, ``button_rule``), ``strip.name``, ``strip.payouts``,
``strip.prizes_typed``, ``strip.pace``, ``strip.button_rule``, ``strip.game`` (Spin),
``hand.street_bet``, ``hand.shown``, ``hand.before_target``, ``hand.positions`` and ``hand.button``
(the seat names and the button of the hand on screen, also after its result, when the table's own
are the next hand's), ``hand.want_suits`` (``{"hand": "AKs", "options": [["Ah", "Kh"], ...]}`` while
the exact cards of a class hand are wanted), on a hand-line item ``street``, ``event``, ``allin``,
``inferred``; a seat's ``status`` can also read ``busted`` or ``empty``; ``toast.redo`` (the button
beside "Undone" is Redo).  Refusals the page reacts to carry a code: ``side_pot``, ``stale``,
``class_mismatch``, ``seats_taken``, ``unreadable``.

For the advice adapter: ``Session.engine_state()`` (the dict
``poker_coach.state`` works on), ``Session.hand_state()`` (``replay`` of the
hand on screen: order, labels, start stacks, posts, the log of actions) and
``Session.record_advice(rev, verb, follow)`` (keeps what the coach showed, for
the hand history; an ``act`` intent may carry ``advice`` instead).

Choices worth knowing:

- A stack is always a number.  One that was never typed, or that an
  unrecorded hand may have changed, is marked ``stale`` (drawn as ``~``).
- The button moves when a hand ends (result or skip), so between hands the
  table already shows the next deal; ``deal`` uses the button as it stands.
  Where it goes is ``next_button``: with the "dead" rule the big blind moves
  on by exactly one player whoever went out, and the button may rest on an
  empty seat.  A player marked as out after the hand moves it the same way.
  A hand always has a small blind: a dead small blind cannot be entered.
- Once a hand has an action the button cannot be moved (undo, or discard).
- ``deal`` on a hand still open closes it like ``skip_hand``.
- A hand that is settled is read-only: undo reopens it.
- Undo stops at the first table of a session; a new tournament over an old
  one can be undone.
- Hero's cards as a class (AKs) are enough before the flop.  While a class is
  on record ``set_cards`` takes only that hand's own exact cards for hero
  (code ``class_mismatch`` otherwise; ``replace`` changes the hand itself),
  and cards sent without a slot go to the board unless they are that hand.
- An action for a player who was passed by: see the comment above
  ``_late_action``.  While the hand waits for a street's cards or a result,
  such an action reopens the betting round that just closed; while it waits
  for a street's cards only a call or a check does, and a bet, raise or
  all-in is refused ("Type the flop first ..., then record the bet").
- Hero with no chips keeps his seat.  After a bust, a stack typed there is a
  re-entry: players left and entrants go up by one.
- Files: every accepted change is saved (the file before it is kept as
  ``<mode>.json.bak``).  A change that cannot be saved stays made and is saved
  with the next one (``view.unsaved``).  A file with bad content is set aside
  as ``<name>.unreadable-<date-time>`` and the user is told in the first view;
  a file that cannot be opened stops the start (``StorageError``).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time

from .. import state as S
from ..cards import HANDS, card_str, parse_cards, parse_hand
from ..evaluator import evaluate
from ..ranges import PLAYER_TYPES, norm_type, position_name
from . import defaults as D
from .amounts import (BLINDS_FIX, MAX_AMOUNT, MAX_COUNT, AmountError, fmt, fmt_bb, parse_amount, parse_blinds,
                      parse_count, parse_ladder, parse_payouts, tidy)

HERO = 1                                                    # hero's seat, always
BETTING = ("preflop", "flop", "turn", "river")              # the phases in which players act
MARKERS = ("away", "back")                                  # events that are not actions: a player stood up, or came back
BOARD_CARDS = {"preflop": 0, "flop": 3, "turn": 4, "river": 5, "showdown": 5, "done": 5}
STREET_OF_CARD = ("flop", "flop", "flop", "turn", "river")  # which street a board card belongs to
SUIT_ORDER = "shdc"                                         # the order suits are offered in, as on the card keys
STREET_WORDS = {"preflop": "before the flop", "flop": "on the flop", "turn": "on the turn", "river": "on the river"}
BOARD_EXAMPLE = {"flop": "K S 7 D 2 C", "turn": "5 H", "river": "9 C"}     # a street's cards as they are typed

# What to type instead, said when a field's text cannot be read: each field has its own sentence.
COUNT_FIELDS = {"remaining": ("Players left", 96), "paid": ("Places paid", 75), "entrants": ("Entrants", 500)}
FIELD_FIX = {
    "stack": "Type it like 12500, 12.5k or 25bb; +3k and -1500 change it.",
    "stack_bb": "Type it in big blinds, like 8 or 5.5.",
    "avg_stack": "Type the average stack like 52000, 52k or 26bb.",
    "start_stack": "Type the starting stack like 10000 or 10k.",
    "buyin": "Type the buy-in like 11 or 27.60.",
    "prize_pool": "Type the prize pool like 5000 or 5k.",
}

KINDS = {"fold": "fold", "f": "fold", "check": "check", "x": "check", "call": "call", "c": "call",
         "limp": "call", "bet": "bet", "b": "bet", "raise": "raise", "r": "raise", "allin": "allin",
         "all-in": "allin", "all_in": "allin", "a": "allin", "shove": "allin", "jam": "allin"}
TYPE_KEYS = {"n": "nit", "t": "tight", "g": "tag", "l": "lag", "o": "loose", "s": "station",
             "m": "maniac", "u": "unknown"}
PLAN_NAMES = {"full": "full", "allin": "allin", "all-in": "allin", "aof": "allin", "binary": "allin",
              "allin_or_fold": "allin", "all-in or fold": "allin"}


class ModelError(Exception):
    """An intent that cannot be carried out.  ``message`` says why, ``fix`` what to do instead.

    ``code`` is a word for the page where it has to react to one refusal in
    particular ("side_pot": a pot still needs a winner); most have none.
    """

    def __init__(self, message: str, fix: str = "", code: str = ""):
        super().__init__(message)
        self.message = message
        self.fix = fix
        self.code = code


class _NoTurn(Exception):
    """The seat has no turn coming in this betting round."""


class StorageError(OSError):
    """A session file is there and cannot be opened: another program holds it.  Nothing was renamed."""


READ_TRIES, READ_WAIT = 10, 0.1         # a file another program holds for a moment: tried for about a second
WRITE_TRIES, WRITE_WAIT = 10, 0.05      # the same when saving (antivirus, a sync client, a backup)
STALE_TEMPORARY_SECONDS = 60            # a half-written file older than this was left by a program that died


def _n(x):
    """A clean number: whole chips stay ints, tenths of a big blind lose their float dust."""
    x = round(x, 6)
    return int(x) if float(x).is_integer() else x


# ==========================================================================
# 1. Seats and positions
# ==========================================================================

def preflop_order(dealt, button: int) -> list[int]:
    """Seats in the order they act before the flop: first to act ... small blind, big blind.

    ``button`` may be an empty seat (its player busted): the last player
    before it then acts as the button.
    """
    dealt = sorted(dealt)
    clockwise = [s for s in dealt if s > button] + [s for s in dealt if s <= button]   # from the button's left
    if len(dealt) < 2:
        return clockwise
    if len(dealt) == 2:
        # heads-up the button posts the small blind and acts first before the flop
        return [clockwise[1], clockwise[0]]
    return clockwise[2:] + clockwise[:2]            # the first two after the button are the blinds: they act last


def postflop_order(order: list[int]) -> list[int]:
    """After the flop the small blind acts first and the button last; heads-up the big blind acts first."""
    if len(order) == 2:
        return order[::-1]
    return order[-2:] + order[:-2]


def next_button(button: int, sb: int, bb: int, dealt, rule: str = "dead") -> int:
    """The button's seat for the next hand, after a hand with the button, small blind and big blind on these seats.

    ``dealt`` are the seats that get cards next.  The blinds are always the two players after
    the button (``preflop_order``), so placing the button places them.

    ``forward``: the next player after the old button.

    ``dead``: the big blind moves on by exactly one player.  The button goes to the seat the
    small blind had, also when that player is out (a dead button on an empty seat), as long as
    that puts the big blind where it belongs; otherwise (the big blind's player went out) it is
    the player before the new small blind.  Heads-up the button is the small blind.
    """
    dealt = sorted(dealt)

    def after(seat):
        return next((s for s in dealt if s > seat), dealt[0])

    def before(seat):
        return next((s for s in reversed(dealt) if s < seat), dealt[-1])

    if len(dealt) < 2:
        return dealt[0] if dealt else button
    if rule == "forward":
        return after(button)
    new_bb = after(bb)
    if len(dealt) == 2:
        return before(new_bb)                       # the other player: button and small blind in one
    if after(after(sb)) == new_bb:
        return sb
    return before(before(new_bb))


def seat_labels(order: list[int]) -> dict[int, str]:
    """{seat: "UTG" ... "BB"} for seats listed in preflop order."""
    n = len(order)
    if n < 2:
        return {}
    return {seat: position_name(n - 1 - i, n) for i, seat in enumerate(order)}


# ==========================================================================
# 2. The hand machine
# ==========================================================================

class HandState:
    """Where a hand stands after its recorded events.  Build it with ``replay(hand)``.

    Amounts follow the poker client: a bet or raise is the total a player has
    in front of him on this street ("to"), never the chips he adds.
    """

    def __init__(self, hand: dict):
        level, rules = hand["level"], hand.get("rules", {})
        self.order = list(hand["order"])                # preflop order: first to act ... SB, BB
        self.n = len(self.order)
        self.button = hand["button"]
        self.labels = seat_labels(self.order)
        self.sb, self.bb = level["sb"], level["bb"]
        self.aof = bool(rules.get("allin_or_fold"))     # All-In or Fold: the only moves are all-in and fold
        self.fee = rules.get("fee") or 0                # ... and the house takes a fee from the first pot
        self.away = set(hand.get("away", ()))           # these seats take the passive default at their turn
        self.start = {s: hand["start"][str(s)] for s in self.order}
        self.stack = dict(self.start)                   # chips behind, now
        self.ante = dict.fromkeys(self.order, 0)        # the ante each player paid
        self.blind = dict.fromkeys(self.order, 0)       # the blind each player posted
        self.dead = 0                                   # the big-blind ante: dead money in the first pot
        self.put_in = dict.fromkeys(self.order, 0)      # live chips put in over the whole hand (blinds and bets)
        self.in_front = dict.fromkeys(self.order, 0)    # chips in front on this street
        self.folded: set[int] = set()
        self.returned: dict[int, float] = {}            # uncalled chips given back
        self.log: list[dict] = []                       # every action in order, implied ones included
        self.result = None                              # set when the hand is over
        self.phase = "preflop"                          # preflop, flop, turn, river, showdown, done
        self._post_forced_bets(level, rules.get("short_post", "ante_first"))
        # Opening: the bet to match is the full big blind, even when the big blind posted less.
        self.bet_to = self.bb
        self.last_raise = self.bb                       # the size of the last full raise
        self.raises = 0                                 # bets and raises made on this street
        self.acted_at = dict.fromkeys(self.order, None)  # the bet each player last answered on this street
        self.last = None                                # who acted last on this street
        self._advance()

    # ---- forced bets ------------------------------------------------------

    def _post_forced_bets(self, level: dict, short_post: str) -> None:
        """Antes first (players sitting out pay too), then the big-blind ante and the blinds.

        Every post is capped by the stack; a player left with nothing is all-in.
        """
        sb_seat, bb_seat = self.order[-2], self.order[-1]
        for seat in self.order:
            paid = min(level.get("ante") or 0, self.stack[seat])
            self.stack[seat] -= paid
            self.ante[seat] = paid
        if short_post == "blind_first":                 # a short big blind posts his blind before the table's ante
            self._post_blind(sb_seat, self.sb)
            self._post_blind(bb_seat, self.bb)
            self._pay_dead(bb_seat, level.get("bb_ante") or 0)
        else:
            self._pay_dead(bb_seat, level.get("bb_ante") or 0)
            self._post_blind(sb_seat, self.sb)
            self._post_blind(bb_seat, self.bb)

    def _pay_dead(self, seat: int, amount) -> None:
        paid = min(amount, self.stack[seat])
        self.stack[seat] -= paid
        self.dead += paid

    def _post_blind(self, seat: int, amount) -> None:
        paid = min(amount, self.stack[seat])
        self.blind[seat] = paid
        self._put(seat, paid)

    def _put(self, seat: int, amount) -> None:
        self.stack[seat] = _n(self.stack[seat] - amount)
        self.put_in[seat] = _n(self.put_in[seat] + amount)
        self.in_front[seat] = _n(self.in_front[seat] + amount)

    # ---- who is where -----------------------------------------------------

    def live(self) -> list[int]:
        """Players who have not folded."""
        return [s for s in self.order if s not in self.folded]

    def with_chips(self) -> list[int]:
        """Live players who still have chips behind."""
        return [s for s in self.live() if self.stack[s] > 0]

    def street_order(self) -> list[int]:
        return self.order if self.phase == "preflop" else postflop_order(self.order)

    def max_to(self, seat: int):
        """The biggest total this player can make on this street: all-in."""
        return _n(self.in_front[seat] + self.stack[seat])

    def owe(self, seat: int):
        """Chips this player must add to stay in.

        Never more than his stack, and never more than the biggest total a
        live opponent can reach: nobody pays for chips that cannot be matched.
        """
        reach = [self.in_front[o] + self.stack[o] for o in self.live() if o != seat]
        matchable = max(reach) - self.in_front[seat] if reach else 0
        return _n(max(0, min(self.stack[seat], self.bet_to - self.in_front[seat], matchable)))

    def may_raise(self, seat: int) -> bool:
        """Can this player raise (or bet) now?"""
        if self.stack[seat] <= self.bet_to - self.in_front[seat]:
            return False                                # all his chips are no more than a call
        if not any(o != seat and self.stack[o] > 0 for o in self.live()):
            return False                                # nobody left who could call a raise
        # He has not acted yet, or the bet has risen by a full raise since he did
        # (one raise, or short all-ins that add up to one).
        return self.acted_at[seat] is None or self.bet_to - self.acted_at[seat] >= self.last_raise

    def min_raise_to(self, seat: int):
        """The smallest legal raise (a total), or his all-in if that is less."""
        return _n(min(self.bet_to + self.last_raise, self.max_to(seat)))

    def _needs_to_act(self, seat: int) -> bool:
        if seat in self.folded or self.stack[seat] <= 0:
            return False
        if self.acted_at[seat] is None:
            return self.owe(seat) > 0 or self.may_raise(seat)
        return self.in_front[seat] < self.bet_to and self.owe(seat) > 0

    def to_act(self):
        """The seat that acts next, or ``None`` when the betting round (or the hand) is closed."""
        if self.phase not in BETTING:
            return None
        order = self.street_order()
        first = 0 if self.last is None else order.index(self.last) + 1
        for k in range(len(order)):
            seat = order[(first + k) % len(order)]
            if self._needs_to_act(seat):
                return seat
        return None

    def implied_kind(self, seat: int) -> str:
        """What a player does when nobody says otherwise: check when it is free, fold when it is not."""
        return "fold" if self.owe(seat) > 0 else "check"

    def anyone_all_in(self) -> bool:
        return any(self.stack[s] <= 0 for s in self.live())

    # ---- pots ---------------------------------------------------------------

    def pot_total(self):
        """Every chip in the middle, bets in front included."""
        return _n(sum(self.ante.values()) + self.dead + sum(self.put_in.values()))

    def pots(self, settled: bool | None = None) -> list[dict]:
        """Main pot and side pots: ``[{"amount": chips, "eligible": [seats]}]``.

        A player can win from each opponent no more than he put in himself, so
        the chips are cut into layers at every live player's total.  A player's
        own ante counts towards his total; the big-blind ante does not (it is
        dead money in the first pot).

        While bets are still being answered (``settled`` false) only an all-in
        cuts a layer: a player with chips behind can still match the rest.
        """
        if settled is None:
            settled = self.phase not in BETTING
        total = {s: self.ante[s] + self.put_in[s] for s in self.order}
        live = self.live()
        if settled:
            levels = sorted({total[s] for s in live})
        else:
            levels = sorted({total[s] for s in live if self.stack[s] <= 0})
            top = max(total.values())
            if not levels or top > levels[-1]:
                levels.append(top)
        layers, below = [], 0
        for level in levels:
            amount = sum(min(total[s], level) - min(total[s], below) for s in self.order)
            if level == 0 or amount > 0:        # level 0: a big blind all-in for the table's ante plays for it alone
                eligible = [s for s in live if total[s] >= level or (not settled and self.stack[s] > 0)]
                layers.append({"amount": amount, "eligible": eligible})
            below = level
        if layers:
            # chips a folded player put in above the top live total stay with the last pot
            layers[-1]["amount"] += sum(max(0, total[s] - below) for s in self.order)
            layers[0]["amount"] += self.dead
        merged: list[dict] = []
        for pot in layers:
            if pot["amount"] <= 0:
                continue
            if merged and merged[-1]["eligible"] == pot["eligible"]:
                merged[-1]["amount"] += pot["amount"]       # the same players: one pot
            else:
                merged.append(pot)
        for pot in merged:
            pot["amount"] = _n(pot["amount"])
        return merged

    # ---- actions ------------------------------------------------------------

    def apply(self, event: dict, index=None) -> None:
        """One recorded action, by the rules.  Raises ``ModelError`` when it is not legal here."""
        seat, kind = event["seat"], event["kind"]
        if kind in MARKERS:
            # not an action: from here on the player takes the passive default (or stops doing so)
            if kind == "away":
                self.away.add(seat)
            else:
                self.away.discard(seat)
            if self.phase in BETTING:
                self._advance()
            return
        if self.phase not in BETTING:
            raise ModelError("The betting is over.", "Say who won the pot.")
        if event.get("street", self.phase) != self.phase:
            raise ModelError(f"That action was on the {event['street']}; the hand is on the {self.phase}.",
                             "Undo, or edit the earlier action.")
        actor = self.to_act()
        if seat != actor:
            raise ModelError(f"It is not seat {seat}'s turn: seat {actor} acts first.",
                             "Enter the actions in order.")
        owe = self.owe(seat)
        if self.aof:
            if kind == "call" and self.anyone_all_in():
                kind = "allin"                          # calling an all-in is moving all-in
            if kind not in ("fold", "allin"):
                raise ModelError("In All-In or Fold the only moves are all-in and fold.", "Choose all-in or fold.")
        if kind == "fold":
            self.folded.add(seat)
        elif kind == "check":
            if owe > 0:
                raise ModelError(f"Seat {seat} cannot check: {fmt(owe)} to call.", "Call, raise or fold.")
        elif kind == "call":
            if owe <= 0:
                raise ModelError("There is nothing to call.", "Check instead.")
            self._put(seat, owe)
        elif kind in ("bet", "raise", "allin"):
            kind = self._bet_or_raise(seat, kind, event.get("to"), owe, bool(event.get("forced")))
        else:
            raise ModelError(f"Unknown action {kind!r}.", "Use fold, check, call, bet, raise or allin.")
        self._record(seat, kind, bool(event.get("auto")), index)
        self._advance()

    def _bet_or_raise(self, seat: int, kind: str, to, owe, forced: bool) -> str:
        """Put a bet, a raise or an all-in on the table; returns what it was (bet, raise or call)."""
        if kind == "allin":
            to = self.max_to(seat)
            if owe > 0 and not self.may_raise(seat):
                self._put(seat, owe)                    # he covers everybody left: his all-in is a call
                return "call"
        if to is None:
            raise ModelError("A bet or raise needs an amount.", "Type the total, such as 1300 or 2.2bb.")
        add = _n(to - self.in_front[seat])
        if add > self.stack[seat]:
            raise ModelError(f"Seat {seat} has only {fmt(self.max_to(seat))}.", "Make it an all-in.")
        all_in = add == self.stack[seat]
        if to <= self.bet_to:
            if not all_in:
                raise ModelError(f"A raise must be above the bet of {fmt(self.bet_to)}.",
                                 f"Raise to {fmt(self.min_raise_to(seat))} or more, or call.")
            self._put(seat, add)                        # all-in for less than the bet: a call
            return "call"
        if not self.may_raise(seat):
            raise ModelError("The betting is not open for a raise.", "Call or fold.")
        opening = self.bet_to == 0
        full = to - self.bet_to >= self.last_raise
        if not full and not all_in and not forced:
            raise ModelError(f"The smallest raise is to {fmt(self.min_raise_to(seat))}.",
                             f"Raise to {fmt(self.min_raise_to(seat))} or more.")
        if full:
            self.last_raise = _n(to - self.bet_to)      # a short all-in lifts the bet but not the raise size
        self._put(seat, add)
        self.bet_to = to
        self.raises += 1
        return "bet" if opening else "raise"

    def _record(self, seat: int, kind: str, auto: bool, index) -> None:
        self.acted_at[seat] = self.bet_to
        self.last = seat
        self.log.append({"street": self.phase, "seat": seat, "kind": kind, "to": self.in_front[seat],
                         "allin": kind != "fold" and self.stack[seat] <= 0, "auto": auto, "event": index})

    def _advance(self) -> None:
        """After every action: absent players take their default, and a finished round is closed."""
        while True:
            if len(self.live()) == 1:
                self._return_uncalled()
                self._finish([self.live()])             # everybody else folded: no showdown needed
                return
            actor = self.to_act()
            if actor is not None and actor in self.away:
                kind = self.implied_kind(actor)         # sitting out: check when free, otherwise fold
                if kind == "fold":
                    self.folded.add(actor)
                self._record(actor, kind, True, None)
                continue
            if actor is not None:
                return
            # nobody needs to act: the round is over
            self._return_uncalled()
            if len(self.with_chips()) <= 1 or self.phase == "river":
                self.phase = "showdown"                 # nothing left to bet: only the cards and the result remain
                return
            self.phase = BETTING[BETTING.index(self.phase) + 1]
            self.in_front = dict.fromkeys(self.order, 0)
            self.acted_at = dict.fromkeys(self.order, None)
            self.bet_to, self.last_raise, self.raises, self.last = 0, self.bb, 0, None

    def _return_uncalled(self) -> None:
        """The part of the biggest bet that nobody matched goes back to the bettor."""
        ranked = sorted(self.in_front.items(), key=lambda kv: -kv[1])
        if len(ranked) >= 2 and ranked[0][1] > ranked[1][1]:
            seat, extra = ranked[0][0], _n(ranked[0][1] - ranked[1][1])
            self.stack[seat] = _n(self.stack[seat] + extra)
            self.put_in[seat] = _n(self.put_in[seat] - extra)
            self.in_front[seat] = _n(self.in_front[seat] - extra)
            self.returned[seat] = _n(self.returned.get(seat, 0) + extra)

    # ---- the result -----------------------------------------------------------

    def award(self, ranking) -> None:
        """Give out the pots.  ``ranking`` lists the hands best first; players who tie share a tier."""
        if self.phase != "showdown":
            raise ModelError("The hand is not at a showdown.", "Finish the betting first.")
        self._finish(ranking)

    def _finish(self, ranking) -> None:
        pots = self.pots(settled=True)
        fee = min(self.fee, pots[0]["amount"]) if pots else 0
        if fee:
            pots[0]["amount"] = _n(pots[0]["amount"] - fee)
        # Each pot goes to the best hand among the players who can win it.
        for number, pot in enumerate(pots):
            winners = []
            for tier in ranking:
                winners = [s for s in tier if s in pot["eligible"]]
                if winners:
                    break
            if not winners:
                if len(pot["eligible"]) > 1:
                    who = " and ".join(f"{self.labels[s]} (seat {s})" for s in pot["eligible"])
                    name = "main pot" if number == 0 else "side pot"
                    raise ModelError(f"Who wins the {name} of {fmt(pot['amount'])} between {who}?",
                                     "Name the best hand among them as well.", code="side_pot")
                winners = pot["eligible"]               # only one player can win it
            pot["winners"] = winners
        # Split pots: equal shares; odd chips go one each clockwise from the button's left.
        won = dict.fromkeys(self.order, 0)
        clockwise = postflop_order(self.order)
        for pot in pots:
            amount, winners = pot["amount"], pot["winners"]
            if float(amount).is_integer():
                share, odd = divmod(int(amount), len(winners))
            else:
                share, odd = amount / len(winners), 0
            for seat in winners:
                won[seat] += share
            for seat in [s for s in clockwise if s in winners][:odd]:
                won[seat] += 1
        for seat in self.order:
            won[seat] = _n(won[seat])
            self.stack[seat] = _n(self.stack[seat] + won[seat])
        self.in_front = dict.fromkeys(self.order, 0)
        self.result = {"pots": pots, "won": won, "fee": fee}
        self.phase = "done"

    def net(self, seat: int):
        """What the hand has cost or earned this player so far."""
        return _n(self.stack[seat] - self.start[seat])

    def busted(self) -> list[int]:
        return [s for s in self.order if self.phase == "done" and self.stack[s] <= 0]


def build_hand(number: int, stacks: dict, button: int, level: dict, away=(), rules: dict | None = None) -> dict:
    """A hand as it is stored: the frozen start, and an empty list of events.

    ``stacks`` maps each dealt-in seat to its chips before antes and blinds.
    ``level`` holds ``sb``, ``bb``, ``ante`` (every player) and ``bb_ante``
    (the big blind pays it for the table).  ``rules``: ``short_post``,
    ``allin_or_fold``, ``fee``.
    """
    order = preflop_order([s for s, chips in stacks.items() if chips > 0], button)
    return {"no": number, "level": dict(level), "button": button, "order": order,
            "away": [s for s in order if s in away], "leaving": [],
            "start": {str(s): stacks[s] for s in order},
            "rules": dict(rules or {"short_post": "ante_first", "allin_or_fold": False, "fee": 0}),
            "hero_cards": "", "board": [], "shown": {}, "events": [], "ranking": None,
            "advice": {}, "settled": False, "skipped": False}


def replay(hand: dict) -> HandState:
    """The one pure function of the hand: the stored hand in, where it stands out.

    It never changes ``hand``.  Events must be legal and in turn; the friendly
    layer of the session makes sure they are before it stores them.
    """
    state = HandState(hand)
    for index, event in enumerate(hand["events"]):
        state.apply(event, index)
    if hand.get("ranking") and state.phase == "showdown":
        state.award(hand["ranking"])
    return state


def imply_until(state: HandState, seat: int) -> list[dict]:
    """Give every player who acts before ``seat`` in this round the passive default.

    Changes ``state`` and returns the implied events.  Raises ``_NoTurn`` when
    the round closes without reaching the seat.
    """
    phase, implied = state.phase, []
    while state.phase == phase:
        actor = state.to_act()
        if actor is None:
            break
        if actor == seat:
            return implied
        event = {"street": phase, "seat": actor, "kind": state.implied_kind(actor), "auto": True}
        state.apply(event)
        implied.append(event)
    raise _NoTurn()


# ==========================================================================
# 3. The session
# ==========================================================================

def default_folder() -> str:
    """Where sessions are saved: ``tournament/app/`` here, ``~/PokerCoach/app/`` for the packaged program.

    ``$POKER_COACH_APP`` names another folder (a second copy of the program, or a trial run
    that must not touch the real sessions), as ``$POKER_COACH_STATE`` does for the command line.
    """
    if os.environ.get("POKER_COACH_APP"):
        return os.environ["POKER_COACH_APP"]
    if getattr(sys, "frozen", False):
        return os.path.join(S.ROOT, "app")
    return os.path.join(S.ROOT, "tournament", "app")


def ladder_levels(name: str) -> list[dict]:
    return [{"sb": sb, "bb": bb, "ante": ante} for sb, bb, ante in D.LADDERS[name]["levels"]]


def next_big_blind(bb):
    """The big blind after ``bb`` once a ladder has run out: 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, then times ten."""
    scale = 1.0
    while scale * D.CONTINUE_STEPS[-1] <= bb:
        scale *= 10
    while scale > bb:
        scale /= 10
    for factor in (scale, scale * 10):
        for step in D.CONTINUE_STEPS:
            if step * factor > bb * (1 + 1e-9):
                return tidy(step * factor, 0.01)
    return tidy(bb * 1.25, 0.01)


def new_seat(name: str = "", stack=0, stale: bool = False) -> dict:
    return {"name": name, "stack": stack, "status": "active", "type": "unknown", "note": "", "stale": stale}


def blank_session(mode: str, size=None, start_stack=None, ladder=None) -> dict:
    """A new session with the defaults of its mode: a full table, everybody on the starting stack."""
    size = size or D.TABLE_SIZE[mode]
    stack = start_stack or D.START_STACK[mode]
    ladder = ladder or D.LADDER_FOR_MODE[mode]
    aof = mode == "aof"
    # tournament opponents start on a guess (the starting stack) until their real stacks are typed
    seats = {str(n): new_seat("", stack, stale=mode == "tournament") for n in range(2, size + 1)}
    seats[str(HERO)] = new_seat(D.HERO_NAME, stack)
    tally = {"games": 0, "wins": 0} if mode == "spin" else {"net_bb": 0, "hands": 0, "banked": 0} if aof else None
    return {
        "version": 1, "mode": mode, "started": False,
        "rules": {"ante_kind": D.ANTE_KIND[mode], "short_post": D.SHORT_POST, "button_rule": D.BUTTON_RULE,
                  "allin_or_fold": aof,
                  "cap_bb": D.AOF_CAP_BB if aof else None, "fee_bb": D.AOF_FEE_BB if aof else 0,
                  "refill": D.AOF_REFILL if aof else False},
        "tournament": {"name": "", "buyin": None, "entrants": None, "remaining": None, "paid": None,
                       "payouts": None, "prize_pool": None, "start_stack": stack, "avg_stack": None,
                       "total_chips": None, "reentry_open": False, "bounty": False, "history": []},
        "config": {"style": D.STYLE, "plan": D.PLAN, "opponents": D.OPPONENTS[mode][0], "pace": D.PACE},
        "structure": {"ladder": ladder, "levels": ladder_levels(ladder), "index": 0, "custom": None},
        "table": {"size": size, "button": HERO, "seats": seats},
        "game": {"start_stack": stack, "over": None, "hands": 0},   # Spin: one game of three players
        "hand": None, "hand_no": 0,
        "hands": [], "hands_base": 0,
        "tally": tally,
        "journal": {"undo": [], "redo": []},
    }


# ---- facts derived from a session (no changes) ------------------------------

def session_level(data: dict) -> dict:
    """The blinds of the session now: ``{"number", "sb", "bb", "ante", "bb_ante"}`` as a hand will post them."""
    structure = data["structure"]
    if structure["custom"]:
        level, number = structure["custom"], None
    else:
        level, number = structure["levels"][structure["index"]], structure["index"] + 1
    kind = data["rules"]["ante_kind"]
    return {"number": number, "sb": level["sb"], "bb": level["bb"], "ante_kind": kind,
            "ante": level.get("ante", 0) if kind == "player" else 0,             # every player pays it
            "bb_ante": level.get("bb_ante", level["bb"]) if kind == "bb" else 0}  # the big blind pays one for the table


def goal_for(data: dict) -> str:
    """The prize model for the engine: chips are money in Spin, All-In or Fold and while re-entry is open."""
    if data["mode"] != "tournament" or data["tournament"].get("reentry_open"):
        return "chips"
    return "itm" if data["config"]["style"] == "cash" else "balanced"


def engine_state(data: dict) -> dict:
    """The dict ``poker_coach.state`` works on, built from a session.

    Stacks are start-of-hand stacks (the table is only updated when a hand is
    settled).  ``history`` is the session's own list, so
    ``state.record_remaining`` writes straight into the session.
    """
    t, table, hand = data["tournament"], data["table"], data["hand"]
    level = hand["level"] if hand and not hand["settled"] else session_level(data)
    fill = data["config"]["opponents"] if data["config"]["opponents"] in PLAYER_TYPES else "unknown"
    seats = {}
    for key, seat in table["seats"].items():
        ptype = seat["type"] if seat["type"] != "unknown" or int(key) == HERO else fill
        seats[key] = {"name": seat["name"] or f"Seat{key}", "stack": float(seat["stack"]),
                      "status": seat["status"], "type": ptype, "notes": [seat["note"]] if seat["note"] else []}
    tournament = data["mode"] == "tournament"
    state = S.blank_state()
    state["tournament"].update({k: t.get(k) if tournament else None for k in
                                ("buyin", "entrants", "remaining", "paid", "payouts", "prize_pool",
                                 "start_stack", "avg_stack", "total_chips")})
    state["tournament"]["name"] = t.get("name") or ""
    state["level"] = {"sb": level["sb"], "bb": level["bb"], "ante": level["ante"],
                      "bb_ante": level["bb_ante"], "number": level.get("number")}
    state["table"] = {"max_seats": table["size"], "button": table["button"], "hero": HERO, "seats": seats}
    state["config"] = {"goal": goal_for(data), "pace": data["config"].get("pace", D.PACE)}
    state["history"] = t["history"]
    return state


def average_stack(data: dict):
    """The tournament's average stack when it can be worked out, else what was typed, else ``None``."""
    t = data["tournament"]
    total = t.get("total_chips") or ((t.get("entrants") or 0) * (t.get("start_stack") or 0))
    if total and t.get("remaining"):
        return total / t["remaining"]
    return t.get("avg_stack")


def stage_of(data: dict) -> dict:
    """``{"code", "label"}``: how far the money is.  Codes: unknown early middle approach bubble itm final."""
    if data["mode"] != "tournament":
        return {"code": "unknown", "label": ""}
    info = S.stage(engine_state(data))
    to_money = info.get("to_money")
    if to_money is None:
        # what the stage needs and does not have yet: players left, places paid
        t = data["tournament"]
        missing = [word for word, known in (("LEFT", t.get("remaining")),
                                            ("PAID", t.get("paid") or t.get("entrants") or t.get("payouts"))) if not known]
        return {"code": "unknown", "label": "ADD " + " AND ".join(missing or ["LEFT", "PAID"])}
    return {
        "early": {"code": "early", "label": "EARLY"},
        "middle": {"code": "middle", "label": "MIDDLE"},
        "approach": {"code": "approach", "label": f"{to_money} FROM THE MONEY"},
        "near_bubble": {"code": "approach", "label": f"{to_money} FROM THE MONEY"},
        "bubble": {"code": "bubble", "label": "BUBBLE"},                # a few places from the money
        "itm": {"code": "itm", "label": "IN THE MONEY"},
        "final_table": {"code": "final", "label": "FINAL TABLE"},
    }.get(info["code"], {"code": "unknown", "label": "ADD LEFT AND PAID"})


def icm_level(data: dict) -> str:
    """How much the prize maths knows: off, estimated, on or exact."""
    t = data["tournament"]
    if goal_for(data) == "chips" or not t.get("remaining"):
        return "off"                                    # chips are money, or nobody said how many are left
    if not (t.get("paid") or t.get("entrants") or t.get("payouts")):
        return "off"
    knows_field = bool(t.get("total_chips") or (t.get("entrants") and t.get("start_stack")))
    if not knows_field:
        return "estimated"                              # the field's stacks are taken from this table
    # exact: a prize was typed for every paid place.  With only the top prizes typed the places
    # below take the last one (``state.payouts``): that is "on", and ``prizes_typed`` says how many are real
    return "exact" if t.get("payouts") and len(t["payouts"]) >= (t.get("paid") or 0) else "on"


def prizes_typed(data: dict) -> int:
    """How many places have a prize that was typed (0: the typical ladder is used)."""
    return len(data["tournament"].get("payouts") or [])


class Session:
    """The app's state and the single way to change it.

        session = Session()                              # files in tournament/app/
        view = session.apply({"op": "deal"})             # the new view, or ModelError(message, fix)
        view = session.view()

    ``folder`` is where the files go (tests pass their own); ``save=False``
    keeps everything in memory.
    """

    def __init__(self, folder: str | None = None, save: bool = True):
        self.folder = folder or default_folder()
        self.saving = save
        self.app = {"version": 1, "mode": "tournament", "unit": "chips", "deck": D.DECKS[0],
                    "rev": 0, "notice_seen": False}
        self._parked: dict[str, dict] = {}                  # the other modes' sessions, once they were opened
        self._toast: list[str] = []
        self._notices: list[str] = []                       # what the first view must tell: a file set aside, a copy used
        self._dirty: set[str] = set()                       # files the last save did not reach
        self.unsaved = ""                                   # ... and why, while that is so
        self.last_fault = ""                                # the detail of the last unreadable request, for the log
        self._sweep_temporary_files()
        self.app.update(self._load("app", self._checked_app) or {})
        self.data = self._load_mode(self.app["mode"])       # the session of the mode on screen

    # ---- files ----------------------------------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self.folder, name + ".json")

    def _sweep_temporary_files(self) -> None:
        """Half-written files of a program that was killed in the middle of a save."""
        if not self.saving:
            return
        try:
            for name in os.listdir(self.folder):
                path = os.path.join(self.folder, name)
                old = time.time() - os.path.getmtime(path) > STALE_TEMPORARY_SECONDS
                if name.endswith(".tmp") and ".json" in name and old:
                    os.remove(path)
        except OSError:                                     # no folder yet, or a file that is held: nothing to tidy
            pass

    @staticmethod
    def _read(path: str):
        """``("ok", content)``, ``("absent", None)`` or ``("bad", None)`` (not JSON, not text, cut short).

        A file that is there and cannot be opened is tried for about a second (on Windows an
        antivirus or a sync program holds a file for a moment) and then raises ``StorageError``:
        a healthy file is never treated as a damaged one.
        """
        problem = None
        for attempt in range(READ_TRIES):
            try:
                with open(path, encoding="utf-8-sig") as fh:    # -sig: an editor may have put a byte-order mark in front
                    return "ok", json.load(fh, parse_constant=_not_a_number)
            except FileNotFoundError:
                return "absent", None
            except (ValueError, RecursionError):                # bad JSON, bad UTF-8, brackets nested without end
                return "bad", None
            except OSError as err:
                problem = err
                if attempt + 1 < READ_TRIES:
                    time.sleep(READ_WAIT)
        raise StorageError(f"Cannot read {path} ({problem.strerror or problem}). "
                           "Close the program that holds the file and start again.")

    def _load(self, name: str, check):
        """A saved file, checked, or ``None`` when there is none that can be used.

        ``check(content)`` returns the content made complete, or raises ``ValueError`` when it is
        not what this program saves.  A file with bad content is set aside under a dated name,
        never deleted; the copy kept from one change earlier (``.bak``) is used when it is good.
        What happened is told in the first view's toast.
        """
        if not self.saving:
            return None
        path = self._path(name)
        file = os.path.basename(path)
        status, content = self._read(path)
        if status == "ok":
            try:
                return check(content)
            except ValueError:
                status = "bad"
        aside = self._set_aside(path) if status == "bad" else None
        try:
            status2, content2 = self._read(path + ".bak")
            if status2 == "ok":
                content2 = check(content2)
        except (ValueError, OSError):
            status2 = "bad"
        if status2 == "ok":
            why = f"could not be read and was set aside as {aside}" if status == "bad" else "was missing"
            self._notices.append(f"{file} {why}. The table from one change earlier is back")
            self._dirty.add(name)                           # the next save writes the main file again
            return content2
        if status == "bad":
            self._notices.append(f"{file} could not be read and was set aside as {aside}. This is a new table")
        return None

    @staticmethod
    def _set_aside(path: str) -> str:
        """Rename a damaged file to ``<name>.unreadable-<date-time>``, never over an older one; returns the new name."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target, n = f"{path}.unreadable-{stamp}", 1
        while os.path.exists(target):
            n += 1
            target = f"{path}.unreadable-{stamp}-{n}"
        try:
            os.replace(path, target)
        except OSError:
            return os.path.basename(path) + " (it could not be renamed)"
        return os.path.basename(target)

    def _write(self, name: str, content: dict) -> None:
        """Write a file in one step: a crash can leave the old file or the new one, never half of one.

        The file as it was is kept as ``<name>.json.bak``.  When another program holds the file
        the step is tried again for half a second; after that ``OSError`` goes to the caller.
        """
        if not self.saving:
            return
        os.makedirs(self.folder, exist_ok=True)
        path = self._path(name)
        tmp = f"{path}.{os.getpid()}.tmp"                       # a name of this process: two programs never share it
        text = json.dumps(content, separators=(",", ":"))     # in one go: much faster than json.dump to a file
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            kept = False
            if name != "app":
                try:
                    os.replace(path, path + ".bak")             # one change earlier: read when the file is damaged
                    kept = True
                except OSError:
                    pass                                        # no file yet, or it is held: this save goes without a copy
            for attempt in range(WRITE_TRIES):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if attempt + 1 == WRITE_TRIES:
                        if kept:
                            os.replace(path + ".bak", path)     # not saved: the file is where it was
                        raise
                    time.sleep(WRITE_WAIT)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _checked_app(content) -> dict:
        """What ``app.json`` may set: only the keys this program wrote, each of the right kind."""
        if not isinstance(content, dict):
            raise ValueError("app.json is not an object")
        app = {}
        for key, options in (("mode", D.MODES), ("unit", D.UNITS), ("deck", D.DECKS)):
            if content.get(key) in options:
                app[key] = content[key]
        rev = content.get("rev")
        if isinstance(rev, int) and not isinstance(rev, bool) and 0 <= rev <= MAX_AMOUNT:
            app["rev"] = rev
        if isinstance(content.get("notice_seen"), bool):
            app["notice_seen"] = content["notice_seen"]
        return app

    def _load_mode(self, mode: str) -> dict:
        return self._load(mode, lambda content: self._checked_session(content, mode)) or blank_session(mode)

    def _checked_session(self, data, mode: str) -> dict:
        """A loaded session made complete, or ``ValueError`` when it is not a session of this mode.

        A file from an older version lacks what was added since: missing keys, seat fields and
        hand fields are filled from the defaults.  Then the view is built once; a session that
        cannot be drawn is not loaded.
        """
        if not isinstance(data, dict) or data.get("mode") != mode:
            raise ValueError("not a session of this mode")
        fresh = blank_session(mode)
        for key, value in fresh.items():
            if key not in data:
                data[key] = value
            elif isinstance(value, dict):
                if not isinstance(data[key], dict):
                    raise ValueError(f"{key} is not an object")
                for k2, v2 in value.items():
                    data[key].setdefault(k2, v2)
            elif isinstance(value, list) and not isinstance(data[key], list):
                raise ValueError(f"{key} is not a list")
        seats = data["table"]["seats"]
        if not isinstance(seats, dict) or not all(isinstance(seat, dict) for seat in seats.values()):
            raise ValueError("the seats are not objects")
        seats.setdefault(str(HERO), new_seat(D.HERO_NAME, 0))
        for seat in seats.values():
            for key, value in new_seat().items():
                seat.setdefault(key, value)
        hand = data["hand"]
        if hand is not None:
            if not isinstance(hand, dict):
                raise ValueError("the hand is not an object")
            for key, value in build_hand(0, {}, HERO, {"sb": 0, "bb": 0}).items():
                hand.setdefault(key, value)
        journal = data["journal"]
        for key in ("undo", "redo"):
            if not isinstance(journal.get(key), list) or not all(isinstance(step, str) for step in journal[key]):
                journal[key] = []                           # the undo history is lost; the table is not
        while journal["undo"] and '"started":false' in journal["undo"][0]:
            del journal["undo"][0]                          # undo stops at the first table (older files went one further)
        if not self._can_be_drawn(data):
            raise ValueError("the view cannot be built from it")
        return data

    def _can_be_drawn(self, data: dict) -> bool:
        """Build the view of ``data`` once, as the page will ask for it."""
        held = self.__dict__.get("data")
        self.data = data
        try:
            json.dumps(self.view(), allow_nan=False)
            return True
        except Exception:                                   # whatever is wrong in the file, the answer is the same
            return False
        finally:
            if held is None:
                del self.data
            else:
                self.data = held

    def _save(self) -> None:
        """Write what changed.  A file that cannot be written now is written with the next change.

        The change itself stays made: the page is told "made, not saved yet", not a refusal.
        """
        self._dirty.update((self.app["mode"], "app"))
        problem = None
        for name in sorted(self._dirty):
            content = self.app if name == "app" else self.data if name == self.app["mode"] else self._parked.get(name)
            try:
                if content is not None:
                    self._write(name, content)
                self._dirty.discard(name)
            except OSError as err:
                problem = err
        self.unsaved = ""
        if problem is not None:
            self.unsaved = f"{problem.strerror or problem} ({self.folder})"

    # ---- the way in -------------------------------------------------------------

    @property
    def rev(self) -> int:
        """Goes up by one with every accepted intent; advice is computed for one revision."""
        return self.app["rev"]

    def do(self, op: str, **args) -> dict:
        """Shorthand: ``session.do("act", seat=4, kind="call")``."""
        return self.apply({"op": op, **args})

    def apply(self, intent: dict) -> dict:
        """Carry out one intent and return the new view.

        On ``ModelError`` nothing has changed.  Every accepted intent is one
        undo step and is saved at once.  An intent may carry ``rev``, the
        revision of the view it was made on: when the table has changed since,
        it is refused with the code ``stale``.
        """
        if not isinstance(intent, dict) or not intent.get("op"):
            raise ModelError("The request names no operation.", 'Send {"op": "..."}.')
        op = str(intent["op"])
        handler = getattr(self, "_op_" + op, None)
        if handler is None:
            raise ModelError(f"Unknown operation {op!r}.", "See the list at the top of model.py.")
        if intent.get("rev") is not None:
            sent = intent["rev"]
            if isinstance(sent, bool) or not isinstance(sent, (int, float)) or sent != self.rev:
                raise ModelError("The table had changed since that was sent.", "Look again and repeat it.", code="stale")
            intent = {key: value for key, value in intent.items() if key != "rev"}
        if op == "new_session" and intent.get("mode") and str(intent["mode"]).lower() != self.app["mode"]:
            self.apply({"op": "set_mode", "mode": intent["mode"]})     # a new session in another mode: go there first
        self._toast, self._toast_redo = [], False
        app_before = dict(self.app)
        held = (self.data, dict(self._parked))          # what a change of mode that fails goes back to
        was_started = self.data["started"]
        if op == "new_session":
            before = self._snapshot(all_hands=self.data["hands"])   # it empties the history: undo needs all of it
        else:
            before = self._snapshot()
        journal_before = (list(self.data["journal"]["undo"]), list(self.data["journal"]["redo"]))
        try:
            undoable = handler(intent) is not False     # a handler returns False when there is nothing to undo
        except (ModelError, AmountError) as err:
            self._put_back(app_before, before, journal_before, held)
            raise ModelError(err.message, err.fix, getattr(err, "code", "")) from None
        except StorageError as err:
            # the other mode's file is held by another program: the mode on screen stays
            self._put_back(app_before, before, journal_before, held)
            self.last_fault = f"{op}: {err}"
            raise ModelError("The saved table of that mode cannot be read right now.",
                             "Close the program that holds its file, then try again.") from None
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError) as err:
            # an argument of the wrong kind (a list where a seat number belongs).  The page never
            # sends one; the detail is for the --verbose log, not for the user
            self._put_back(app_before, before, journal_before, held)
            self.last_fault = f"{op}: {type(err).__name__}: {err}"
            raise ModelError("That request could not be read.",
                             "Check its arguments: the list is at the top of model.py.", code="unreadable") from None
        if undoable:
            journal = self.data["journal"]
            if was_started:                             # the first table of a session is where undo stops
                journal["undo"].append(before)
                del journal["undo"][:-D.UNDO_LIMIT]
            journal["redo"].clear()
            self.data["started"] = True
        self.app["rev"] += 1
        try:
            view = self.view(toast=True)                # before saving: a table that cannot be shown is never saved
            json.dumps(view, allow_nan=False)
        except Exception as err:
            self._put_back(app_before, before, journal_before, held)
            self.last_fault = f"{op}: the view failed: {type(err).__name__}: {err}"
            raise ModelError("That change would leave a table that cannot be shown, so it was not made.",
                             "Check the numbers in it.", code="unreadable") from None
        self._notices = []                              # told with this view
        self._save()
        view["unsaved"] = self.unsaved
        if self.unsaved:
            said = f"Made, not saved yet: {self.unsaved}. The next change saves again"
            view["toast"] = {"text": " · ".join(filter(None, [view["toast"]["text"] if view["toast"] else "", said])),
                             "undo": view["can"]["undo"], "redo": False}
        return view

    def _put_back(self, app_before: dict, before: str, journal_before, held) -> None:
        """A refused intent leaves no trace."""
        if self.app["mode"] != app_before["mode"]:
            self.data, self._parked = held              # a change of mode: the session that was on screen is as it was
        else:
            self._restore(before)
            self.data["journal"]["undo"], self.data["journal"]["redo"] = journal_before
        self.app = app_before

    # ---- undo and redo ------------------------------------------------------------

    def _snapshot(self, **extra) -> str:
        """The session written out as text, without the undo journal itself.

        Finished hands are only counted (the list just grows), so a snapshot
        stays small.  Text, because that is what the file holds anyway, and
        because writing the file is then quick.
        """
        light = {k: v for k, v in self.data.items() if k not in ("journal", "hands")}
        light["n_hands"] = self.data["hands_base"] + len(self.data["hands"])
        light.update(extra)
        return json.dumps(light, separators=(",", ":"))

    def _restore(self, snapshot: str) -> None:
        """Put a snapshot back.  The journal stays; the list of finished hands is cut back to the snapshot's count."""
        snap = json.loads(snapshot)
        count = snap.pop("n_hands")
        tail = snap.pop("tail", [])
        if "all_hands" in snap:                         # taken around a new session: the whole history comes back
            snap["hands"] = snap.pop("all_hands")
        else:
            snap["hands_base"] = self.data["hands_base"]
            snap["hands"] = self.data["hands"][:max(0, count - snap["hands_base"])] + tail
        snap["journal"] = self.data["journal"]
        self.data = snap

    def _exchange(self, snapshot: str) -> str:
        """Restore a snapshot and return one of what was there, so undo and redo are each other's mirror."""
        snap = json.loads(snapshot)
        if "all_hands" in snap:
            now = self._snapshot(all_hands=self.data["hands"])
        else:
            keep = max(0, snap["n_hands"] - self.data["hands_base"])
            now = self._snapshot(tail=self.data["hands"][keep:])     # hands this step takes away: the way back needs them
        self._restore(snapshot)
        return now

    def _op_undo(self, a) -> bool:
        journal = self.data["journal"]
        if not journal["undo"]:
            raise ModelError("There is nothing to undo.", "This is the table the session began with.")
        journal["redo"].append(self._exchange(journal["undo"].pop()))
        self._say("Undone")
        self._toast_redo = True                         # the button beside "Undone" takes it back: it is Redo
        return False

    def _op_redo(self, a) -> bool:
        journal = self.data["journal"]
        if not journal["redo"]:
            raise ModelError("There is nothing to redo.", "Nothing was undone since the last change.")
        journal["undo"].append(self._exchange(journal["redo"].pop()))
        self._say("Redone")
        return False

    # ---- small helpers --------------------------------------------------------------

    def _say(self, text: str) -> None:
        """A line for the toast that goes back with this intent's view."""
        if text and text not in self._toast:
            self._toast.append(text)

    @property
    def mode(self) -> str:
        return self.data["mode"]

    @property
    def _step(self) -> float:
        """Amounts are whole chips, or tenths of a big blind in All-In or Fold."""
        return 0.1 if self.mode == "aof" else 1

    def _seats(self) -> dict:
        return self.data["table"]["seats"]

    def _seat_arg(self, a: dict, empty_ok: bool = False) -> int:
        try:
            seat = int(a.get("seat"))
        except (TypeError, ValueError, OverflowError):
            raise ModelError("Which seat?", "Name a seat by its number.") from None
        if not 1 <= seat <= self.data["table"]["size"]:
            raise ModelError(f"There is no seat {seat} at this table.",
                             f"Seats run from 1 to {self.data['table']['size']}.")
        if not empty_ok and str(seat) not in self._seats():
            raise ModelError(f"Seat {seat} is empty.", "Add a player there first.")
        return seat

    def _who(self, seat: int, labels: dict | None = None) -> str:
        """A player's name for a sentence: his name, else his position, else the seat number."""
        entry = self._seats().get(str(seat)) or {}
        if entry.get("name"):
            return entry["name"]
        return (labels or {}).get(seat) or f"Seat {seat}"

    def _who_is(self, seat: int, labels: dict | None = None) -> str:
        return "You are" if seat == HERO else f"{self._who(seat, labels)} is"

    def _who_has(self, seat: int, labels: dict | None = None) -> str:
        return "You have" if seat == HERO else f"{self._who(seat, labels)} has"

    def _dealt_in(self) -> list[int]:
        """Seats that get cards: playing or sitting out, with chips."""
        return sorted(int(k) for k, s in self._seats().items()
                      if s["status"] in ("active", "away") and s["stack"] > 0)

    def _open_hand(self):
        """The hand in progress, or ``None`` (between hands, or the hand on screen is already settled)."""
        hand = self.data["hand"]
        return hand if hand and not hand["settled"] else None

    def _need_open_hand(self) -> dict:
        hand = self.data["hand"]
        if hand is None:
            raise ModelError("No hand is being played.", "Deal a new hand first (N).")
        if hand["settled"]:
            raise ModelError("This hand is settled.", "Undo to reopen it, or deal the next hand (N).")
        return hand

    def _bb(self):
        hand = self._open_hand()
        return hand["level"]["bb"] if hand else session_level(self.data)["bb"]

    def _amount(self, text, current=None, field: str = "stack"):
        """A typed stack or tournament amount, in this table's unit."""
        if field == "stack" and self.mode == "aof":
            field = "stack_bb"
        return parse_amount(text, bb=self._bb(), current=current, step=self._step, fix=FIELD_FIX[field])

    # ---- public helpers for the advice adapter --------------------------------------------

    def engine_state(self) -> dict:
        """The dict ``poker_coach.state`` works on (``stage``, ``fold_clock``, ``build_prizes``, ``hand_setup``)."""
        return engine_state(self.data)

    def hand_state(self):
        """``replay`` of the hand on screen, or ``None`` between hands."""
        return replay(self.data["hand"]) if self.data["hand"] else None

    def record_advice(self, rev: int, verb: str, follow: dict | None = None) -> bool:
        """Remember the advice shown for the current decision, for the hand history.

        Not an intent: the revision does not change and there is nothing to
        undo.  Ignored when ``rev`` is no longer the current revision.
        """
        hand = self._open_hand()
        if hand is None or rev != self.rev:
            return False
        self._keep_advice(hand, verb, follow)
        self._save()                                    # a save that fails is made up for by the next change
        return True

    @staticmethod
    def _keep_advice(hand: dict, verb, follow=None) -> None:
        """File the advice under the number of hero's next decision in this hand (0 = his first)."""
        decision = sum(1 for e in replay(hand).log if e["seat"] == HERO)
        hand["advice"][str(decision)] = {"verb": str(verb), "follow": follow}

    # ==========================================================================
    # Intents: session, mode, tournament, settings
    # ==========================================================================

    def _op_set_mode(self, a) -> bool:
        mode = str(a.get("mode") or a.get("name") or "").lower()
        if mode not in D.MODES:
            raise ModelError(f"Unknown mode {mode!r}.", "Modes: " + ", ".join(D.MODES) + ".")
        if mode != self.app["mode"]:
            # the other mode first: when its file cannot be read, nothing has been changed yet
            other = self._parked.get(mode) or self._load_mode(mode)
            self._parked.pop(mode, None)
            self._parked[self.app["mode"]] = self.data  # each mode keeps its own table and its own undo history
            self.app["mode"] = mode                     # (its file is up to date, or still marked for the next save)
            self.data = other
        return False

    def _op_new_session(self, a) -> None:
        mode = self.app["mode"]
        size = self._size_arg(a.get("size") or D.TABLE_SIZE[mode])
        ladder = a.get("ladder") or D.LADDER_FOR_MODE[mode]
        if ladder not in D.LADDERS:
            raise ModelError(f"Unknown ladder {ladder!r}.", "Ladders: " + ", ".join(D.LADDERS) + ".")
        stack = a.get("start_stack")
        if stack not in (None, ""):
            stack = parse_amount(stack, step=self._step, fix=FIELD_FIX["start_stack"])
        else:
            stack = D.START_STACK[mode]
        if stack <= 0:
            raise ModelError("The starting stack must be above zero.", "Type the starting stack, such as 10000.")
        journal = self.data["journal"]
        old_tally = self.data.get("tally")
        self.data = blank_session(mode, size, stack, ladder)
        self.data["journal"] = journal                  # starting over can be undone like anything else
        if a.get("keep_tally") and old_tally:
            self.data["tally"] = old_tally
        if a.get("button") not in (None, ""):
            self._op_set_button({"seat": a["button"]})
        if a.get("hero_stack") not in (None, ""):
            self._seats()[str(HERO)]["stack"] = self._amount(a["hero_stack"])
        if a.get("level") or a.get("blinds"):
            self._op_set_level({"text": a.get("level") or a.get("blinds")})
        fields = {k: a[k] for k in ("name", "buyin", "entrants", "remaining", "paid", "payouts", "avg_stack") if k in a}
        if fields:
            self._op_set_tournament(fields)
        for key in ("style", "plan", "opponents", "pace", "reentry_open", "bounty"):
            if key in a:
                self._op_set_config({key: a[key]})
        self._say({"tournament": "New tournament started", "spin": "New Spin & Gold session started",
                   "aof": "New All-In or Fold session started"}[mode])

    def _op_set_tournament(self, a) -> None:
        t = self.data["tournament"]
        fields = dict(a)
        if a.get("field"):                              # the strip sends one field and what was typed
            fields = {str(a["field"]): a.get("text", a.get("value"))}
        known = ("name", "buyin", "entrants", "remaining", "paid", "payouts", "avg_stack", "start_stack",
                 "prize_pool", "reentry_open", "bounty")
        touched = False
        for key in known:
            if key not in fields:
                continue
            touched = True
            value = fields[key]
            empty = value is None or (isinstance(value, str) and not value.strip())
            if key == "name":
                t["name"] = _text(value, D.TOURNAMENT_NAME_LENGTH)
            elif key in ("reentry_open", "bounty"):
                t[key] = _truth(value)
            elif key == "payouts":
                t["payouts"] = parse_payouts(value)     # "auto" clears it: the estimated table is used
            elif key == "remaining":
                self._set_remaining(None if empty else parse_count(value, *COUNT_FIELDS[key]))
            elif key in ("entrants", "paid"):
                t[key] = None if empty else parse_count(value, *COUNT_FIELDS[key])
                if key == "entrants":
                    t["total_chips"] = None             # the total follows entrants x starting stack again
            elif key == "avg_stack":
                t["avg_stack"] = None if empty else self._amount(value, field="avg_stack")
                # an average read from the lobby fixes the chips in play: it covers re-entries and add-ons
                t["total_chips"] = t["avg_stack"] * t["remaining"] if t["avg_stack"] and t.get("remaining") else None
            elif key == "start_stack":
                t["start_stack"] = None if empty else self._amount(value, field="start_stack")
                t["total_chips"] = None
            else:                                       # buyin, prize_pool: money, not chips (1.000 is a thousand)
                t[key] = None if empty else parse_amount(value, step=0.01, fix=FIELD_FIX[key], dots_are_thousands=True)
        if not touched:
            raise ModelError("Nothing to set.", "Fields: " + ", ".join(known) + ".")
        if t.get("paid") and t.get("entrants") and t["paid"] > t["entrants"]:
            self._say(f"{t['paid']} places paid is more than the {t['entrants']} entrants: check both")

    def _set_remaining(self, remaining) -> None:
        t = self.data["tournament"]
        if remaining is not None and remaining < 1:
            raise ModelError("Players left must be one or more.", "Type the number shown in the lobby.")
        t["remaining"] = remaining
        if remaining:
            # time-stamped: the fold clock works out the bust rate from these
            S.record_remaining(engine_state(self.data), remaining)
            # ... and it looks back twenty minutes or so: older marks would only make the file bigger
            newest = t["history"][-1]["t"]
            recent = [mark for mark in t["history"] if mark["t"] >= newest - D.REMAINING_MINUTES_KEPT * 60]
            t["history"] = recent[-D.REMAINING_MARKS_KEPT:]

    def _op_remaining(self, a) -> None:
        if self.mode != "tournament":
            raise ModelError("Players left belongs to tournaments.", "")
        t = self.data["tournament"]
        value = a.get("value", a.get("text"))
        if value not in (None, ""):
            self._set_remaining(parse_count(value, *COUNT_FIELDS["remaining"], current=t.get("remaining")))
            return
        delta = _whole(a.get("delta") or a.get("step") or 0, "delta")
        if not delta:
            raise ModelError("Nothing to change.", "Send a number, or a step of -1 or +1.")
        if not t.get("remaining"):
            raise ModelError("Players left is not set yet.", "Type the number shown in the lobby.")
        self._set_remaining(min(MAX_COUNT, max(1, t["remaining"] + delta)))

    def _op_set_config(self, a):
        fields = dict(a)
        if a.get("key") or a.get("field"):
            fields = {str(a.get("key") or a.get("field")): a.get("value", a.get("text"))}
        config, t = self.data["config"], self.data["tournament"]
        undoable = False
        touched = False
        for key, value in fields.items():
            if key == "op":
                continue
            text = str(value).strip().lower() if value is not None else ""
            if key == "unit":
                self.app["unit"] = _choice(text or _next(D.UNITS, self.app["unit"]), D.UNITS, "unit")
            elif key == "deck":
                self.app["deck"] = _choice(text or _next(D.DECKS, self.app["deck"]), D.DECKS, "deck")
            elif key == "notice_seen":
                self.app["notice_seen"] = _truth(value)
            elif key == "style":
                config["style"] = _choice(text or _next(D.STYLES, config["style"]), D.STYLES, "style")
                undoable = True
            elif key == "plan":
                if text and text not in PLAN_NAMES:
                    raise ModelError(f"Unknown plan {text!r}.", "Plans: full, allin.")
                config["plan"] = PLAN_NAMES[text] if text else _next(D.PLANS, config["plan"])
                undoable = True
            elif key == "pace":
                config["pace"] = _choice(text, D.PACES, "pace")
                undoable = True
            elif key == "opponents":
                config["opponents"] = self._opponents(text)
                undoable = True
            elif key in ("reentry_open", "bounty"):
                t[key] = _truth(value) if value is not None else not t[key]
                undoable = True
            elif key == "tally" and isinstance(value, dict) and self.data["tally"] is not None:
                for k in self.data["tally"]:
                    if k in value:
                        self.data["tally"][k] = _n(_finite(value[k], "tally " + k))
                undoable = True
            elif key == "refill" and self.mode == "aof":
                self.data["rules"]["refill"] = _truth(value)
                undoable = True
            elif key == "short_post":
                self.data["rules"]["short_post"] = _choice(text, ("ante_first", "blind_first"), "short_post")
                undoable = True
            elif key == "button_rule":
                rules = self.data["rules"]
                rules["button_rule"] = _choice(text or _next(D.BUTTON_RULES, rules["button_rule"]), D.BUTTON_RULES,
                                               "button rule")
                self._say("Button rule: dead button (the big blind always moves on by one player)"
                          if rules["button_rule"] == "dead" else "Button rule: the button always goes to the next player")
                undoable = True
            else:
                raise ModelError(f"Unknown setting {key!r}.",
                                 "Settings: style, plan, opponents, pace, reentry_open, bounty, button_rule, unit, deck.")
            touched = True
        if not touched:
            raise ModelError("Nothing to set.",
                             "Settings: style, plan, opponents, pace, reentry_open, bounty, button_rule, unit, deck.")
        return undoable                                 # how numbers are drawn is not part of the undo history

    def _opponents(self, text: str) -> str:
        options = D.OPPONENTS[self.mode]
        if not text:
            current = self.data["config"]["opponents"]
            return _next(options, current) if current in options else options[0]
        text = {"vloose": "very-loose", "very loose": "very-loose", "very_loose": "very-loose"}.get(text, text)
        if text in options or (self.mode == "tournament" and text in PLAYER_TYPES):
            return text
        raise ModelError(f"Unknown opponent type {text!r}.", "Choose one of: " + ", ".join(options) + ".")

    # ==========================================================================
    # Intents: blinds
    # ==========================================================================

    def _fixed_blinds(self) -> None:
        if self.mode == "aof":
            raise ModelError("All-In or Fold has fixed blinds.", "")

    def _op_level_up(self, a) -> None:
        self._fixed_blinds()
        structure = self.data["structure"]
        levels = structure["levels"]
        if structure["custom"]:
            # typed blinds that are not on the ladder: go to the first level above them
            bb = structure["custom"]["bb"]
            above = [i for i, lv in enumerate(levels) if lv["bb"] > bb]
            if not above:
                levels.append(self._level_after(structure["custom"]))
            structure["index"], structure["custom"] = (above[0] if above else len(levels) - 1), None
        else:
            if structure["index"] + 1 >= len(levels):
                levels.append(self._level_after(levels[-1]))    # the ladder ran out: it continues by the rule
            structure["index"] += 1
        self._level_changed()

    def _op_level_down(self, a) -> None:
        self._fixed_blinds()
        structure = self.data["structure"]
        if structure["custom"]:
            below = [i for i, lv in enumerate(structure["levels"]) if lv["bb"] < structure["custom"]["bb"]]
            if not below:
                raise ModelError("These blinds are below the first level.", "Type the blinds instead.")
            structure["index"], structure["custom"] = below[-1], None
        else:
            if structure["index"] == 0:
                raise ModelError("This is the first level.", "Type the blinds if they are lower.")
            structure["index"] -= 1
        self._level_changed()

    @staticmethod
    def _level_after(level: dict) -> dict:
        bb = next_big_blind(level["bb"])
        ante = tidy(bb * (level.get("ante") or 0) / level["bb"])    # the ante keeps its share of the big blind
        return {"sb": tidy(bb / 2, 0.01), "bb": bb, "ante": ante}

    def _op_set_level(self, a) -> None:
        self._fixed_blinds()
        structure, rules = self.data["structure"], self.data["rules"]
        if a.get("text") not in (None, ""):
            typed = parse_blinds(a["text"])
        else:
            try:
                typed = {k: parse_amount(a[k], step=0.01, dots_are_thousands=True) if a.get(k) not in (None, "") else None
                         for k in ("sb", "bb", "ante")}
            except AmountError:
                raise ModelError("Cannot read those blinds.", BLINDS_FIX) from None
            if not typed["bb"] or (typed["sb"] or 0) > typed["bb"]:
                raise ModelError("The blinds need a big blind, and a small blind that is not above it.", BLINDS_FIX)
        bb = typed["bb"]
        sb = typed["sb"] if typed["sb"] is not None else tidy(bb / 2, 0.01)
        on_ladder = next((i for i, lv in enumerate(structure["levels"]) if lv["bb"] == bb), None)
        ante = typed["ante"]
        if ante and ante >= bb and rules["ante_kind"] == "player":
            # taken as typed: every player pays it.  On most sites an ante that big is the big blind's
            self._say(f"Ante {fmt(ante)} from every player. A big-blind ante? {key_for('ante')} switches it")
        if ante is not None and ante > 0 and rules["ante_kind"] == "none":
            # an ante was typed where there was none: one big blind or more is a big-blind ante
            rules["ante_kind"] = "bb" if ante >= bb else "player"
            self._say("Ante: the big blind pays it" if rules["ante_kind"] == "bb" else "Ante: every player pays it")
        elif ante == 0 and rules["ante_kind"] != "none":
            rules["ante_kind"] = "none"
            self._say("No ante")
        level = {"sb": sb, "bb": bb}
        if on_ladder is not None:
            level["ante"] = structure["levels"][on_ladder].get("ante", 0)      # the big blind alone: the ladder's ante
        else:
            level["ante"] = tidy(bb * D.ANTE_SHARE_OF_BB)
        if ante and rules["ante_kind"] == "bb":
            level["bb_ante"] = ante
        elif ante:
            level["ante"] = ante
        elif ante is None and rules["ante_kind"] == "player" and level["ante"]:
            # an ante nobody typed is about to be played: say where it came from and how to drop it
            source = {"turbo": "the turbo levels", "regular": "the regular levels"}.get(structure["ladder"],
                                                                                         "the blind levels")
            source = f"from {source}" if on_ladder is not None else "added, an eighth of the big blind"
            self._say(f"Ante {fmt(level['ante'])} {source}; type {_plain(sb)}/{_plain(bb)}/0 for none")
        if on_ladder is not None:
            structure["levels"][on_ladder] = level      # the screen wins: the ladder learns what was typed
            structure["index"], structure["custom"] = on_ladder, None
        else:
            below = [i for i, lv in enumerate(structure["levels"]) if lv["bb"] < bb]
            structure["index"], structure["custom"] = (below[-1] if below else 0), level
        self._level_changed()

    def _op_set_ante_kind(self, a) -> None:
        self._fixed_blinds()
        rules = self.data["rules"]
        kind = str(a.get("kind") or a.get("ante_kind") or "").lower()
        kind = {"every": "player", "each": "player", "players": "player", "big blind": "bb", "bb_ante": "bb",
                "off": "none", "no": "none"}.get(kind, kind)
        rules["ante_kind"] = _choice(kind or _next(D.ANTE_KINDS, rules["ante_kind"]), D.ANTE_KINDS, "ante kind")
        self._level_changed()

    def _op_set_ladder(self, a) -> None:
        self._fixed_blinds()
        structure = self.data["structure"]
        playing = dict(structure["custom"] or structure["levels"][structure["index"]])     # the blinds on the table now
        name = a.get("name") or a.get("ladder")
        if a.get("text"):
            structure["levels"], structure["ladder"] = parse_ladder(a["text"]), "custom"
        elif a.get("levels"):
            text = "\n".join("/".join(str(x) for x in level) for level in a["levels"])
            structure["levels"], structure["ladder"] = parse_ladder(text), "custom"
        elif name in D.LADDERS:
            structure["levels"], structure["ladder"] = ladder_levels(name), name
        else:
            raise ModelError(f"Unknown ladder {name!r}.", "Ladders: " + ", ".join(D.LADDERS) + ", or paste the levels.")
        # Stay at the blinds being played: the same big blind on the new ladder, or between two of its levels.
        levels = structure["levels"]
        same = [i for i, lv in enumerate(levels) if lv["bb"] == playing["bb"]]
        below = [i for i, lv in enumerate(levels) if lv["bb"] < playing["bb"]]
        if a.get("keep_level") is False or not self.data["started"]:
            structure["index"], structure["custom"] = 0, None           # a session not begun: start at level 1
        elif same:
            structure["index"], structure["custom"] = same[0], None
        else:
            structure["index"], structure["custom"] = (below[-1] if below else 0), playing
        self._level_changed()

    def _level_changed(self) -> None:
        """New blinds.  Before the first action the hand on the table is posted again; later they wait for the next hand."""
        hand = self._open_hand()
        if hand is None:
            return
        if hand["events"]:
            self._say("The new blinds start with the next hand")
            return
        self._deal_again(hand)

    # ==========================================================================
    # Intents: the table
    # ==========================================================================

    def _size_arg(self, size) -> int:
        low, high = D.SIZE_LIMITS[self.mode]
        size = _whole(size, "size")
        if not low <= size <= high:
            seats = f"{low} to {high} seats" if low != high else f"{low} seats"
            raise ModelError(f"A {D.MODE_LABELS[self.mode]} table has {seats}.", "")
        return int(size)

    def _op_set_size(self, a) -> None:
        """More or fewer seats.  Empty seats above a smaller size just go; players there need ``clear``."""
        table = self.data["table"]
        size = self._size_arg(a["size"] if a.get("size") not in (None, "")
                              else table["size"] + _whole(a.get("delta") or 0, "delta"))
        taken = sorted(int(k) for k in table["seats"] if int(k) > size)
        if taken:
            hand = self._open_hand()
            names = _listed([f"seat {n}" for n in taken]).capitalize()
            if not _truth(a.get("clear")):
                raise ModelError(f"{names} {'is' if len(taken) == 1 else 'are'} taken.",
                                 "Clear them as well (the players moved away), or clear those seats first.",
                                 code="seats_taken")
            if hand and hand["events"] and any(n in hand["order"] for n in taken):
                raise ModelError(f"{names} {'is' if len(taken) == 1 else 'are'} in the hand being played.",
                                 "Finish or discard the hand first.")
            for seat in taken:                          # they moved away: nobody busted, players left stays
                table["seats"].pop(str(seat))
            self._say(f"{names} removed: {len(taken)} player{'s' if len(taken) > 1 else ''} moved away")
        if size < table["size"]:
            table.pop("moved", None)                    # the table was rearranged: the button is where it is put
        table["size"] = size
        if table["button"] > size:
            table["button"] = size
        self._cast_changed()
        self._spin_game_check()

    def _op_new_table(self, a) -> None:
        """A table move: new opponents, hero and the tournament stay."""
        data, table = self.data, self.data["table"]
        if self._open_hand():
            self._forget_hand()
        data["hand"] = None
        size = self._size_arg(a.get("size") or table["size"])
        hero = table["seats"][str(HERO)]
        # nobody is known at the new table: every seat gets the average stack until the real ones are typed
        guess = average_stack(data) or hero["stack"] or data["tournament"]["start_stack"]
        table["size"] = size
        table["seats"] = {str(n): new_seat("", tidy(guess, self._step), stale=True) for n in range(2, size + 1)}
        table["seats"][str(HERO)] = hero
        table.pop("moved", None)
        table["button"] = min(table["button"], size)
        if a.get("button") not in (None, ""):
            self._op_set_button({"seat": a["button"]})
        self._say("New table: type the stacks you see")

    def _op_set_button(self, a) -> None:
        """The button by hand.  An empty seat is fine: a dead button, after its player went out."""
        seat = self._seat_arg(a, empty_ok=True)
        self._button_may_move(self._open_hand())
        self.data["table"]["button"] = seat
        self._button_changed()

    @staticmethod
    def _button_may_move(hand) -> None:
        """Once a hand has an action the button stays: moving it would deal every action to another seat.

        (Played again from new positions, the players passed over took the implied fold, hero included.)
        """
        if hand and hand["events"]:
            raise ModelError("The button cannot move once the hand has an action.",
                             f"Undo to before the first action, or discard the hand ({key_for('discard')}), "
                             "then move the button.")

    def _op_button_step(self, a) -> None:
        step = _whole(a.get("step") or a.get("delta") or 1, "step")
        table = self.data["table"]
        hand = self._open_hand()
        self._button_may_move(hand)
        button = hand["button"] if hand else table["button"]
        stops = sorted(hand["order"]) if hand else self._dealt_in()     # the button moves from player to player
        if not stops:
            stops = list(range(1, table["size"] + 1))
        for _ in range(abs(step) % len(stops)):         # a full round ends where it began
            if step > 0:
                button = next((s for s in stops if s > button), stops[0])
            else:
                button = next((s for s in reversed(stops) if s < button), stops[-1])
        table["button"] = button
        self._button_changed()

    def _button_changed(self) -> None:
        """The button was moved by hand.  A hand nobody has acted in is posted again from its new positions."""
        self.data["table"].pop("moved", None)           # set by hand: it no longer follows the hand before
        hand = self._open_hand()
        if hand is not None:                            # (with an action on it the move was refused)
            self._deal_again(hand)
            self._say("The blinds were posted again from the new button")

    def _op_seat_player(self, a) -> None:
        seat = self._seat_arg(a, empty_ok=True)
        if seat == HERO and str(HERO) in self._seats():
            entry = self._seats()[str(HERO)]            # hero's seat is his: this is a re-entry or a new stack
        else:
            entry = new_seat()
        was_out = seat == HERO and self._hero_out()
        default = None
        if a.get("stack", a.get("text")) in (None, ""):
            default = self._default_stack()
            entry["stack"], entry["stale"] = default, True
        else:
            entry["stack"], entry["stale"] = self._amount(a.get("stack", a.get("text"))), False
        if a.get("name") is not None:
            entry["name"] = _text(a["name"], D.NAME_LENGTH)
        if a.get("type"):
            entry["type"] = self._type(a["type"])
        if a.get("status"):
            entry["status"] = _choice(str(a["status"]).lower(), ("active", "away"), "status")
        hand = self._open_hand()
        if hand and hand["events"] and seat in hand["order"]:
            raise ModelError(f"Seat {seat} is in the hand being played.", "Finish or discard the hand first.")
        self._seats()[str(seat)] = entry
        if default is not None:
            self._say(f"Seat {seat} sits with {fmt(default)}: type the real stack when you see it")
        if was_out:
            self._reentry(entry)
        self._cast_changed()
        self._spin_game_check()

    def _default_stack(self):
        """A stack for a player whose chips were not typed: the average if known, else the starting stack."""
        if self.mode == "aof":
            return self.data["rules"]["cap_bb"]
        guess = average_stack(self.data) or self.data["tournament"]["start_stack"] or D.START_STACK[self.mode]
        return tidy(guess, self._step)

    def _op_clear_seat(self, a) -> None:
        self._remove_player(self._seat_arg(a), bust=False)

    def _op_bust(self, a) -> None:
        self._remove_player(self._seat_arg(a), bust=True)

    def _remove_player(self, seat: int, bust: bool) -> None:
        """A player leaves (``clear_seat``) or is knocked out (``bust``: one fewer left in the tournament)."""
        if seat == HERO and not bust:
            raise ModelError("Seat 1 is yours.", "Use New table for a table move, or Bust if you are out.")
        who = self._who(seat)
        hand = self._open_hand()
        if hand and hand["events"] and seat in hand["order"]:
            # his chips stay in the pot; he takes the passive default from here on and goes when the hand ends
            if seat not in hand["leaving"]:
                hand["leaving"].append(seat)
            self._mark_away(hand, seat, True)
            self._after_action(hand)
        else:
            self._take_seat_away(seat)
            self._cast_changed()                        # (a bust typed after the hand moves the button as one in it does)
        if bust:
            self._count_bust(1)
            self._say("You are out" if seat == HERO else f"{who} is out")
        else:
            self._say(f"{who} left the table")
        self._spin_game_check()

    def _take_seat_away(self, seat: int) -> None:
        if seat == HERO:
            self._seats()[str(HERO)]["stack"] = 0       # hero keeps his seat: he may re-enter
            self._seats()[str(HERO)]["busted"] = True   # ... and a stack typed there then is a re-entry
        else:
            self._seats().pop(str(seat), None)

    def _hero_out(self) -> bool:
        """Hero has no chips and no hand of his is running."""
        hand = self._open_hand()
        return self._seats()[str(HERO)]["stack"] <= 0 and not (hand and HERO in hand["order"])

    def _reentry(self, entry: dict) -> None:
        """Hero was knocked out and has chips again: one more player is left, one more entry was bought."""
        if not entry.pop("busted", False) or entry["stack"] <= 0:
            return
        if self.mode != "tournament":
            return
        t, counted = self.data["tournament"], []
        if t.get("remaining"):
            self._set_remaining(min(MAX_COUNT, t["remaining"] + 1))
            counted.append(f"players left {fmt(t['remaining'])}")
        if t.get("total_chips"):
            t["total_chips"] += entry["stack"]          # the chips in play were read from the lobby: his are new
        if t.get("entrants"):
            t["entrants"] = min(MAX_COUNT, t["entrants"] + 1)
            counted.append(f"entrants {fmt(t['entrants'])}")
        self._say("Re-entry: " + (" and ".join(counted) if counted else "you are dealt in again"))

    def _count_bust(self, players: int) -> None:
        t = self.data["tournament"]
        if self.mode == "tournament" and t.get("remaining") and players:
            self._set_remaining(max(1, t["remaining"] - players))

    def _op_set_stack(self, a) -> None:
        seat = self._seat_arg(a)
        self._set_stack(seat, a.get("text", a.get("stack", a.get("value", a.get("amount")))))
        self._spin_game_check()

    def _set_stack(self, seat: int, text) -> None:
        """A stack typed by hand is exact, and it is always accepted: the screen wins."""
        entry = self._seats()[str(seat)]
        hand = self._open_hand()
        if hand and seat in hand["order"]:
            # mid-hand the number on screen is the chips behind now: the start stack is that plus what went in
            state = replay(hand)
            behind = self._amount(text, current=state.stack[seat])
            start = _n(behind + state.start[seat] - state.stack[seat])
            entry["stack"], entry["stale"] = start, False
            if hand["events"]:
                hand["start"][str(seat)] = start
                self._rebuild(hand, hand["events"])
                self._after_action(hand)
            else:
                self._deal_again(hand)
        else:
            had_chips = entry["stack"] > 0
            was_out = seat == HERO and self._hero_out()
            entry["stack"], entry["stale"] = self._amount(text, current=entry["stack"]), False
            if was_out:
                self._reentry(entry)
            if had_chips != (entry["stack"] > 0):
                self._cast_changed()                    # he is dealt in from now on, or no longer

    def _op_set_stacks(self, a) -> None:
        """The stack sweep: one value per seat, clockwise from seat 1.  "" keeps, "-" empties the seat."""
        values = a.get("values", a.get("stacks"))
        if isinstance(values, str) or (values is None and a.get("text")):
            values = str(values or a["text"]).replace(";", " ").split()     # a pasted list fills the seats in order
        if isinstance(values, dict):
            pairs = [(int(k), v) for k, v in values.items()]
        else:
            pairs = list(enumerate(values or [], start=1))
        if not pairs:
            raise ModelError("No stacks were given.", "Send one value per seat.")
        for seat, value in pairs:
            if not 1 <= seat <= self.data["table"]["size"]:
                raise ModelError(f"There is no seat {seat} at this table.", "")
            if value is None or (isinstance(value, str) and not value.strip()):
                continue                                # blank: this stack stays as it is
            taken = str(seat) in self._seats()
            if isinstance(value, str) and value.strip() == "-":
                if taken and seat != HERO:
                    self._remove_player(seat, bust=False)
            elif taken:
                self._set_stack(seat, value)
            else:
                self._op_seat_player({"seat": seat, "stack": value})
        self._spin_game_check()

    def _op_set_status(self, a) -> None:
        seat = self._seat_arg(a)
        entry = self._seats()[str(seat)]
        status = str(a.get("status") or "").lower()
        status = {"out": "away", "sitout": "away", "sit_out": "away", "back": "active", "in": "active"}.get(status, status)
        entry["status"] = _choice(status or ("active" if entry["status"] == "away" else "away"),
                                  ("active", "away"), "status")
        hand = self._open_hand()
        if hand and seat in hand["order"]:
            if hand["events"]:
                self._mark_away(hand, seat, entry["status"] == "away")
                self._after_action(hand)
            else:
                self._deal_again(hand)

    @staticmethod
    def _mark_away(hand: dict, seat: int, away: bool) -> None:
        """During a hand: from this point on the player takes the passive default (or acts again)."""
        state = replay(hand)
        if state.phase in BETTING and (seat in state.away) != away:
            hand["events"].append({"street": state.phase, "seat": seat, "kind": "away" if away else "back",
                                   "auto": False})

    def _op_rename(self, a) -> None:
        seat = self._seat_arg(a)
        self._seats()[str(seat)]["name"] = _text(a.get("name", a.get("text")), D.NAME_LENGTH)

    def _type(self, text) -> str:
        low = str(text or "").strip().lower()
        low = TYPE_KEYS.get(low, low)
        if norm_type(low) == "unknown" and low not in ("unknown", "", "?", "none"):
            raise ModelError(f"Unknown player type {text!r}.", "Types: " + ", ".join(PLAYER_TYPES) + ".")
        return norm_type(low)

    def _op_set_type(self, a) -> None:
        seat = self._seat_arg(a)
        self._seats()[str(seat)]["type"] = self._type(a.get("type", a.get("text")))

    def _op_note(self, a) -> None:
        seat = self._seat_arg(a)
        self._seats()[str(seat)]["note"] = _text(a.get("text", a.get("note")), D.NOTE_LENGTH)

    def _cast_changed(self) -> None:
        """Seats or stacks changed.  A hand nobody has acted in yet is dealt again; a hand under way keeps its cast.

        Between hands the button follows: who posts the next big blind depends on who is still there.
        """
        hand = self._open_hand()
        if hand and hand["events"]:
            return
        self._place_button()
        if hand:
            self._deal_again(hand)

    # ==========================================================================
    # Intents: the hand
    # ==========================================================================

    def _op_deal(self, a) -> None:
        data = self.data
        if self._open_hand():
            self._skip_hand(self._open_hand(), hero_in=False)    # the hand left open is closed as it stands
        if self.mode == "spin" and data["game"]["over"]:
            self._new_game(None)
        data["hand"] = None
        data["hand_no"] += 1
        hand = self._freeze_hand(data["hand_no"])
        data["hand"] = hand
        cards = a.get("hero_cards", a.get("cards", a.get("hero")))
        if cards:
            self._set_hero_cards(hand, cards)
        self._after_action(hand)                        # a table where everybody sits out plays itself

    def _freeze_hand(self, number: int) -> dict:
        """Copy what a hand needs from the table: the hand keeps its own cast, stacks, blinds and button."""
        data, rules = self.data, self.data["rules"]
        if rules["allin_or_fold"]:
            self._cut_to_cap()
        dealt = self._dealt_in()
        if len(dealt) < 2:
            raise ModelError("A hand needs two players with chips.", "Add a player or fix the stacks first.")
        level = session_level(data)
        if not level["bb"] or level["bb"] <= 0:
            raise ModelError("The blinds are not set.", BLINDS_FIX)
        seats = self._seats()
        return build_hand(number, {s: seats[str(s)]["stack"] for s in dealt}, data["table"]["button"], level,
                          away=[s for s in dealt if seats[str(s)]["status"] == "away"],
                          rules={"short_post": rules["short_post"], "allin_or_fold": rules["allin_or_fold"],
                                 "fee": rules["fee_bb"]})

    def _cut_to_cap(self) -> None:
        """All-In or Fold: chips above the cap leave the table before the cards are dealt."""
        cap = self.data["rules"]["cap_bb"]
        for key, seat in self._seats().items():
            if cap and seat["stack"] > cap:
                if int(key) == HERO:
                    self.data["tally"]["banked"] = _n(self.data["tally"]["banked"] + seat["stack"] - cap)
                seat["stack"] = cap

    def _deal_again(self, hand: dict) -> None:
        """Nobody has acted yet and the table changed: post the same hand again from the table as it is now."""
        try:
            fresh = self._freeze_hand(hand["no"])
        except ModelError:
            self._forget_hand()                         # no longer two players: there is no hand
            self._say("The hand was taken back: it needs two players")
            return
        for key in ("hero_cards", "board", "shown", "advice"):
            fresh[key] = hand[key]
        self.data["hand"] = fresh
        self._after_action(fresh)

    def _forget_hand(self) -> None:
        self.data["hand"] = None
        self.data["hand_no"] -= 1

    def _op_discard_hand(self, a) -> None:
        self._need_open_hand()
        self._forget_hand()                             # stacks and button are as they were at the deal
        self._say("Hand discarded")

    # ---- cards ----------------------------------------------------------------------------

    def _op_set_cards(self, a) -> None:
        hand = self._need_open_hand()
        slot = str(a.get("slot") or "").lower()
        text = a.get("text")
        hero = a.get("hero", a.get("hero_cards", a.get("cards")))
        board = a.get("board")
        if text is not None and hero is None and board is None:
            if not slot:                                # no slot named: the cards go where they are needed
                slot = "hero" if self._needs(hand, replay(hand)) == "cards" and self._may_be_hero_cards(hand, text) \
                    else "board"
            if slot in ("hero", "cards"):
                hero = text
            elif slot in ("board", "flop", "turn", "river"):
                board = text
            else:
                raise ModelError(f"Unknown card slot {slot!r}.", "Slots: hero, flop, turn, river, board.")
        if hero is None and board is None and not a.get("shown"):
            raise ModelError("No cards were given.", "Send hero's cards or the board.")
        if hero is not None:
            self._set_hero_cards(hand, hero, replace=_truth(a.get("replace")))
        if board is not None:
            self._set_board(hand, board, slot)
        for seat, cards in (a.get("shown") or {}).items():
            self._set_shown(hand, int(seat), cards)
        self._check_no_card_twice(hand)
        self._after_action(hand)

    @staticmethod
    def _class_on_record(hand: dict) -> str:
        """``AKs`` while hero's hand is known as a class only (enough before the flop), else ``""``."""
        return hand["hero_cards"] if hand["hero_cards"] and len(hand["hero_cards"]) != 4 else ""

    def _may_be_hero_cards(self, hand: dict, text) -> bool:
        """Cards typed with no slot named, while hero's cards are wanted: are they his?

        Never when they are the board: three cards or more, or, with a class on record
        (AKs), anything that is not that very hand.
        """
        text = str(text or "").strip()
        try:
            index, exact = parse_hand(text)
        except (ValueError, KeyError, IndexError):
            return not self._class_on_record(hand) and len(text) <= 4      # not two cards: let the hero slot say so
        on_record = self._class_on_record(hand)
        return not on_record or HANDS[index] == on_record

    def _set_hero_cards(self, hand: dict, text, replace: bool = True) -> None:
        """Hero's two cards, exact (AhKd) or as a class (AKs).

        With a class on record the suits are what is still missing: only two
        exact cards of that class are taken, so cards meant for the board never
        become hero's hand.  ``replace`` says the user is changing the hand itself.
        """
        text = str(text or "").strip()
        if not text:
            hand["hero_cards"] = ""
            return
        try:
            index, exact = parse_hand(text)
        except (ValueError, KeyError, IndexError):
            raise ModelError(f"Cannot read {text[:20]!r} as two cards.", "Type them like AhKd, or AKs, AKo, 77.") from None
        on_record = self._class_on_record(hand)
        if on_record and not replace and (HANDS[index] != on_record):
            raise ModelError(f"{text} is not {on_record}.",
                             f"Pick the suits of your {on_record}. To change the hand itself, select your cards "
                             "and type them again.", code="class_mismatch")
        # exact cards when the suits were typed, else the class (enough before the flop)
        hand["hero_cards"] = card_str(exact[0]) + card_str(exact[1]) if exact else HANDS[index]
        self._check_no_card_twice(hand)

    def _want_suits(self, hand: dict, needs: str):
        """While the exact cards of a class hand are wanted: every holding of it the known cards leave."""
        on_record = self._class_on_record(hand)
        if needs != "cards" or not on_record:
            return None
        high, low = on_record[0], on_record[1]
        if high == low:
            pairs = [(a, b) for i, a in enumerate(SUIT_ORDER) for b in SUIT_ORDER[i + 1:]]
        elif on_record.endswith("s"):
            pairs = [(a, a) for a in SUIT_ORDER]
        else:
            pairs = [(a, b) for a in SUIT_ORDER for b in SUIT_ORDER if a != b]
        known = set(self._known_cards(hand))
        options = [[high + a, low + b] for a, b in pairs]
        return {"hand": on_record, "options": [pair for pair in options if not known & set(pair)]}

    def _set_board(self, hand: dict, text, slot: str) -> None:
        text = str(text or "").strip()
        try:
            cards = [card_str(c) for c in parse_cards(text)]
        except ValueError:
            raise ModelError(f"Cannot read {text[:20]!r} as board cards.", "Type them like Ks7d2c.") from None
        old = hand["board"]
        if slot == "flop":
            board = cards + old[3:]
            ok = len(cards) == 3
        elif slot == "turn":
            board = old[:3] + cards + old[4:]
            ok = len(cards) == 1 and len(old) >= 3
        elif slot == "river":
            board = old[:4] + cards
            ok = len(cards) == 1 and len(old) >= 4
        elif len(cards) in (0, 3, 4, 5):
            board, ok = cards, True                     # the whole board as it stands
        else:
            board, ok = old + cards, len(old) >= 3      # one or two more cards: the turn, the river
        if not ok or len(board) > 5:
            raise ModelError(f"{text[:20]!r} does not fit the board.",
                             "The flop is three cards, the turn and the river one each.")
        # The betting must have reached that street.  Players nobody mentioned take the passive
        # default, as with Enter; if that ends the hand there is no board to deal.
        state = replay(hand)
        while state.phase in BETTING and BOARD_CARDS[state.phase] < len(board):
            if not self._close_round(hand):
                break
            state = replay(hand)
        if BOARD_CARDS[state.phase] < len(board) or (state.phase == "done" and len(state.live()) == 1
                                                        and len(board) > len(old)):
            raise ModelError("The hand ended before those cards: nobody called.",
                             "Enter who called first, then the board.")
        hand["board"] = board

    def _set_shown(self, hand: dict, seat: int, text) -> None:
        if seat not in hand["order"]:
            raise ModelError(f"Seat {seat} is not in this hand.", "")
        text = str(text or "").strip()
        if not text:
            hand["shown"].pop(str(seat), None)
            return
        try:
            cards = parse_cards(text)
        except ValueError:
            cards = []
        if len(cards) != 2:
            raise ModelError(f"Cannot read {text[:20]!r} as two cards.", "Type them like QhQd.")
        hand["shown"][str(seat)] = card_str(cards[0]) + card_str(cards[1])

    @staticmethod
    def _known_cards(hand: dict) -> list[str]:
        cards = list(hand["board"])
        if len(hand["hero_cards"]) == 4:
            cards += [hand["hero_cards"][:2], hand["hero_cards"][2:]]
        for shown in hand["shown"].values():
            cards += [shown[:2], shown[2:]]
        return cards

    def _check_no_card_twice(self, hand: dict) -> None:
        cards = self._known_cards(hand)
        for card in cards:
            if cards.count(card) > 1:
                raise ModelError(f"The {card} is used twice.", "Each card exists once: fix the one that is wrong.")

    # ---- actions ----------------------------------------------------------------------------

    def _op_act(self, a) -> None:
        hand = self._need_open_hand()
        state = replay(hand)
        named = a.get("seat") not in (None, "")
        if state.phase not in BETTING and not named:
            raise ModelError("The betting is over.", "Say who won the pot.")
        seat = self._seat_arg(a, empty_ok=True) if named else self._target(hand, state)[0]
        kind = KINDS.get(str(a.get("kind") or a.get("verb") or "").strip().lower())
        if kind is None:
            raise ModelError(f"Unknown action {a.get('kind') or a.get('verb')!r}.",
                             "Actions: fold, check, call, bet, raise, allin.")
        amount = a.get("amount", a.get("to", a.get("text")))
        if amount == "":
            amount = None
        if seat not in state.order:
            raise ModelError(f"{self._who_is(seat)} not in this hand.",
                             "A player who just sat down is dealt in next hand.")
        if seat not in state.folded and state.stack[seat] <= 0:
            raise ModelError(f"{self._who_is(seat, state.labels)} all-in already.", "")
        if seat == HERO and a.get("advice"):
            self._keep_advice(hand, a["advice"])        # what the coach showed when hero acted
        # with no seat named the action is the target's, on the street the hand is on (as Enter and the
        # coach's own button mean it); a named seat may also be a player forgotten in the round just closed
        now = self._street_being_played(hand, state) if named else state.phase
        if now == state.phase and seat not in state.folded:
            try:
                self._append_action(hand, seat, kind, amount, bool(a.get("force")))
                self._after_action(hand)
                return
            except _NoTurn:
                pass                                    # he was passed by: see _late_action
        self._late_action(hand, state, seat, kind, amount, bool(a.get("force")), now)
        self._after_action(hand)

    @staticmethod
    def _street_being_played(hand: dict, state: HandState) -> str:
        """The street a typed action belongs to.

        The street the hand is on, once its cards are on the board or somebody has acted on it.
        While the hand waits for a street's cards, or for the result, it is the betting round
        that just closed: a player forgotten there can still be added.
        """
        if state.phase in BETTING:
            if state.phase == "preflop" or len(hand["board"]) >= BOARD_CARDS[state.phase] \
                    or any(entry["street"] == state.phase for entry in state.log):
                return state.phase
            return BETTING[BETTING.index(state.phase) - 1]
        return state.log[-1]["street"] if state.log else "preflop"

    def _append_action(self, hand: dict, seat: int, kind: str, amount=None, force: bool = False,
                       friendly: bool = True, inferred: bool = False) -> None:
        """Record one action.  Players who act before the seat take the passive default first.

        ``friendly`` turns what was typed into a legal action where it can
        (see ``_friendly``); without it the action is taken as recorded and
        must be legal as it is.  ``inferred``: nobody typed it, it follows from
        a later action of the same player ("he must have called").
        """
        state = replay(hand)
        implied = imply_until(state, seat)              # raises _NoTurn: the caller decides what that means
        if friendly or inferred:
            event = self._friendly(state, seat, kind, amount, force)
        else:
            event = {"seat": seat, "kind": kind, "to": amount, "forced": force}
        event.update(street=state.phase, auto=False)
        if inferred:
            event["inferred"] = True
        state.apply(event)                              # the strict check: raises ModelError when it is not legal
        hand["events"].extend(implied + [event])

    def _friendly(self, state: HandState, seat: int, kind: str, amount, force: bool) -> dict:
        """Turn what the user said into a legal action: convert, do not reject."""
        who = self._who(seat, state.labels)
        owe, top = state.owe(seat), state.max_to(seat)
        if state.aof:
            if kind == "call" and not state.anyone_all_in():
                raise ModelError("In All-In or Fold there is nothing to call before an all-in.", "Choose all-in or fold.")
            if kind in ("bet", "raise", "check"):
                raise ModelError("In All-In or Fold the only moves are all-in and fold.", "Choose all-in or fold.")
            return {"seat": seat, "kind": "fold" if kind == "fold" else "allin"}
        if kind == "call" and owe <= 0:
            kind = "check"                              # nothing to call: it is a check
        if kind == "check" and owe > 0:
            raise ModelError(f"{who} cannot check: {fmt(owe)} to call.", "Call, raise or fold.")
        if kind in ("fold", "check", "call"):
            return {"seat": seat, "kind": kind}
        if kind == "allin":
            return {"seat": seat, "kind": "allin"}
        # a bet or a raise: the amount is the total in front of the player on this street
        can_raise = state.may_raise(seat)
        if amount is None:
            to = self._default_size(state, seat)
        else:
            to = self._bet_amount(state, seat, amount)
        if to >= top:
            return {"seat": seat, "kind": "allin"}      # more than the stack: an all-in
        if not can_raise:
            # the betting is not open for a raise (a short all-in, or nobody left to call one)
            self._say(f"{who} cannot raise here: recorded as a {'call' if owe > 0 else 'check'}")
            return {"seat": seat, "kind": "call" if owe > 0 else "check"}
        low = state.min_raise_to(seat)
        if to < low and not force:
            if amount is not None:
                self._say(f"Lifted to the minimum, {fmt(low)}")
            to = low                                    # below the minimum: lifted to it
            if to >= top:
                return {"seat": seat, "kind": "allin"}
        if to <= state.bet_to:
            raise ModelError(f"A raise must be above the bet of {fmt(state.bet_to)}.", "Type a bigger total.")
        return {"seat": seat, "kind": "bet" if state.bet_to == 0 else "raise", "to": to,
                "forced": bool(force and to < low)}

    def _bet_amount(self, state: HandState, seat: int, amount):
        """A typed bet or raise as a street total."""
        text = str(amount).strip() if isinstance(amount, str) else None
        if text and text.endswith("%") and state.bet_to > 0:
            # a pot-sized raise: call first, then raise by that share of the pot as it would then be
            pot_after_call = state.pot_total() + state.owe(seat)
            return _n(state.bet_to + parse_amount(text, pot=pot_after_call, step=self._step))
        return parse_amount(amount, bb=state.bb, bet=state.bet_to, pot=state.pot_total(), step=self._step)

    def _default_size(self, state: HandState, seat: int):
        """The likeliest size when none is typed: 2.2bb to open, three times a bet, half the pot."""
        if state.bet_to == 0:
            to = state.pot_total() * D.BET_DEFAULT
        elif state.phase == "preflop" and state.raises == 0:
            to = state.bb * D.OPEN_DEFAULT_BB
        else:
            to = state.bet_to * D.RERAISE_DEFAULT
        to = tidy(to, self._step)
        return max(state.min_raise_to(seat), min(to, state.max_to(seat)))

    # ---- an action for a player who was passed by ----------------------------------------------
    #
    # Typing an action implies the passive default for everybody in front of that player.  When
    # the user then types an action for one of those players, he was not out after all:
    #
    # - his implied action is on the street being played (or in the round that just closed, while
    #   the hand waits for cards or a result): the typed action takes its place, on that street;
    # - his fold was implied on an earlier street: he must have called there.  The fold becomes a
    #   call (a check when it was free) on its own street and the typed action is recorded on the
    #   street being played;
    # - his fold was typed: refused, the hand line is the place to change it;
    # - a fold is typed for him and the record has him folded since an earlier street (or since the
    #   round that just closed): nothing changes, and the answer says he is folded already.
    #
    # While the hand waits for a street's cards the round just closed is reopened only for a call
    # or a check (the forgotten caller).  A bet, a raise or an all-in typed then could be meant for
    # either street, so it is refused: the cards first, then the bet.
    #
    # In no case is a typed action read on another street than the one it was typed for, and none
    # of this may drop, change or imply an action of hero: then it is refused and nothing changes.

    def _late_action(self, hand: dict, state: HandState, seat: int, kind: str, amount, force: bool, now: str) -> None:
        """An action for a seat that has no turn coming on the street being played (``now``)."""
        labels = state.labels
        mine = [k for k, e in enumerate(hand["events"]) if e["seat"] == seat and e["kind"] not in MARKERS]
        last = hand["events"][mine[-1]] if mine else None
        if seat in state.away:
            raise ModelError(f"{self._who_is(seat, labels)} sitting out: the defaults are his actions.",
                             "Mark the player as back first.")
        implied_here = last is not None and last["auto"] and last["street"] == now
        implied_fold = seat in state.folded and last is not None and last["auto"] and last["kind"] == "fold"
        if kind == "fold" and implied_fold and last["street"] != state.phase:
            # a fold for a player the record already has out since an earlier street (or since the round
            # that just closed): nothing to do.  It must not put him back in with a call, or reopen that round
            raise ModelError(f"{self._who_is(seat, labels)} already folded on the record.", "")
        if (implied_here or implied_fold) and state.phase in BETTING and now != state.phase \
                and kind in ("bet", "raise", "allin") \
                and not (kind == "allin" and implied_here and self._all_in_is_a_call(hand, mine[-1], seat)):
            raise self._cards_first(state, seat, kind, now, his_fold=implied_here and last["kind"] == "fold")
        if implied_here:
            self._replace_implied(hand, state, seat, mine[-1], kind, amount, force, now)
        elif implied_fold:
            self._must_have_called(hand, state, seat, last["street"], kind, amount, force, now)
        elif seat in state.folded:
            street = last["street"] if last is not None else now
            when = f" {STREET_WORDS[street]}" if street != now else ""
            who = "You" if seat == HERO else self._who(seat, labels)
            raise ModelError(f"{who} folded{when}.", "Select that fold on the hand line to change it.")
        elif state.phase not in BETTING:
            raise ModelError("The betting is over.",
                             "Say who won the pot. To change an earlier action, select it on the hand line.")
        elif now != state.phase:
            # the next street's cards are not typed yet and his last action stands: he acts on the next street
            try:
                self._append_action(hand, seat, kind, amount, force)
            except _NoTurn:
                raise ModelError(f"{self._who_has(seat, labels)} no turn now.",
                                 "Select the earlier action on the hand line to change it.") from None
        else:
            ahead = replay(hand)
            try:
                imply_until(ahead, seat)
            except _NoTurn:
                pass
            if last is None and ahead.phase == "done" and ahead.live() == [seat]:
                # everybody in front would be folded and the pot would be his without a decision
                # (the big blind, typed before anybody came in)
                entered = "moved all-in" if state.aof else "called or raised"
                where = "the big blind" if labels[seat] == "BB" else labels[seat]
                raise ModelError(f"Nobody has entered the pot before {where}.",
                                 f"Record who {entered} first, or press {key_for('accept')} if everybody folded.")
            raise ModelError(f"{self._who_has(seat, labels)} no turn now.",
                             "Select the earlier action on the hand line to change it.")

    def _cards_first(self, state: HandState, seat: int, kind: str, now: str, his_fold: bool) -> ModelError:
        """The refusal of a bet, raise or all-in typed for a seat while the hand waits for a street's cards."""
        street = state.phase                            # the street whose cards are wanted
        word = {"bet": "bet", "raise": "raise", "allin": "all-in"}[kind]
        he, his = ("you", "your") if seat == HERO else ("he", "his")
        if his_fold:
            way = f"select {his} fold on the hand line, then Raised."
        else:
            way = f"undo to that point ({key_for('undo')})."
        return ModelError(f"Type the {street} first ({BOARD_EXAMPLE[street]}), then record the {word}.",
                          f"A bet or raise {he} made {STREET_WORDS[now]}: {way}")

    @staticmethod
    def _all_in_is_a_call(hand: dict, index: int, seat: int) -> bool:
        """Where his implied action stands (the stored event ``index``): all his chips are no more than a call."""
        there = replay(dict(hand, events=hand["events"][:index], ranking=None))
        return there.phase in BETTING and there.to_act() == seat and there.owe(seat) > 0 and not there.may_raise(seat)

    def _replace_implied(self, hand: dict, state: HandState, seat: int, index: int, kind: str, amount, force: bool,
                         now: str) -> None:
        """His implied action on the street being played becomes the typed one; the rest is played again."""
        events = copy.deepcopy(hand["events"])
        events[index] = {"street": now, "seat": seat, "kind": kind, "to": amount, "forced": force,
                         "auto": False, "new": True}
        # "the rest fold" (Enter) was said before this action was known: the players behind him decide again
        events = events[:index + 1] + [e for e in events[index + 1:] if not (e.get("auto") and e.get("close"))]
        trial = copy.deepcopy(hand)
        dropped = self._rebuild(trial, events, quiet=True)      # ModelError: the action cannot be played there
        after = replay(trial)
        who = self._who(seat, state.labels)
        if not self._hero_untouched(state, after):
            raise ModelError("That would undo or change your own action in this hand.",
                             f"Undo to that point, or select {who}'s action on the hand line and change it there.")
        hand["events"], hand["ranking"] = trial["events"], None
        if dropped:
            self._say("No longer possible, dropped: " + "; ".join(dropped))
        if now != state.phase:
            entry = [e for e in after.log if e["seat"] == seat and e["street"] == now][-1]
            self._say(f"Added to the betting {STREET_WORDS[now]}: {who} {self._verb_words(entry, seat)}")

    def _must_have_called(self, hand: dict, state: HandState, seat: int, fold_street: str, kind: str, amount,
                          force: bool, now: str) -> None:
        """His fold on an earlier street was only implied, and now he acts: he must have called there."""
        who = "You" if seat == HERO else self._who(seat, state.labels)
        refusal = ModelError(f"{who} folded {STREET_WORDS[fold_street]} on the record.",
                             "Undo to that point, or select that fold on the hand line and change it to a call first.")
        trial, events = copy.deepcopy(hand), copy.deepcopy(hand["events"])
        for _ in range(12):                             # once for every bet he was folded to on the way
            if self._rebuild(trial, events, quiet=True):
                raise refusal
            reached = replay(trial)                     # the rounds in between close with the usual defaults
            while reached.phase in BETTING and BETTING.index(reached.phase) < BETTING.index(now):
                if not self._close_round(trial):
                    break
                reached = replay(trial)
            events = copy.deepcopy(trial["events"])
            k = next((i for i, e in enumerate(events) if e["seat"] == seat and e.get("auto") and e["kind"] == "fold"
                      and BETTING.index(e["street"]) < BETTING.index(now)), None)
            if k is None:
                break
            events[k] = {"street": events[k]["street"], "seat": seat, "kind": "call", "auto": False, "inferred": True}
        else:
            raise refusal
        events.append({"street": now, "seat": seat, "kind": kind, "to": amount, "forced": force,
                       "auto": False, "new": True})
        try:
            dropped = self._rebuild(trial, events, quiet=True)
        except ModelError as err:
            if err.message in (self.NO_FIT, self.NOT_IN_HAND):
                raise refusal from None                 # he is all-in from the call, or the round never comes to him
            raise                                       # the typed action itself is not possible: "cannot check"
        after = replay(trial)
        typed_before, typed_after = self._acts(state, typed=True), iter(self._acts(after, typed=True))
        kept = not dropped and all(act in typed_after for act in typed_before)      # all of them, in their order
        entries = [e for e in after.log if e["seat"] == seat]
        # (also when he would act behind hero while hero still owes a decision: with the fold
        # changed to a call on the hand line he is in the hand, and hero decides knowing it)
        if not kept or (seat != HERO and not self._hero_untouched(state, after)) \
                or entries[-1]["street"] != now or entries[-1]["auto"]:
            raise refusal
        hand["events"], hand["ranking"] = trial["events"], None
        there = next(e for e in entries if e["street"] == fold_street and not e["auto"])
        was, he = ("You were", "you") if seat == HERO else (f"{who} was", "he")
        self._say(f"{was} folded {STREET_WORDS[fold_street]} on the record: now {he} "
                  f"{'checked' if there['kind'] == 'check' else 'called'} there, and "
                  f"{self._verb_words(entries[-1], seat)} here. {key_for('undo')} takes it back.")

    def _hero_untouched(self, before: HandState, after: HandState) -> bool:
        """Hero's typed actions are exactly what they were, and no action was implied for him that was not there."""
        was, now = self._acts(before, HERO), self._acts(after, HERO)
        if [act for act in was if not act[-1]] != [act for act in now if not act[-1]]:
            return False                                # one of his own actions was dropped or changed
        implied_before = iter([act for act in was if act[-1]])
        return all(act in implied_before for act in now if act[-1])     # a default he had may go; none may come or change

    @staticmethod
    def _acts(state: HandState, seat=None, typed: bool = False) -> list[tuple]:
        """The actions of the log in a shape that can be compared: (seat, street, kind, total, implied)."""
        return [(e["seat"], e["street"], "allin" if e["allin"] else e["kind"], e["to"], e["auto"])
                for e in state.log if (seat is None or e["seat"] == seat) and not (typed and e["auto"])]

    @staticmethod
    def _verb_words(entry: dict, seat: int) -> str:
        """``calls``, ``bets 600``, ``moves all-in``: a log entry as the words of a sentence."""
        s = "" if seat == HERO else "s"
        kind, to = entry["kind"], fmt(entry["to"])
        if entry["allin"]:
            return f"call{s} all-in" if kind == "call" else f"move{s} all-in"
        return {"fold": f"fold{s}", "check": f"check{s}", "call": f"call{s}", "bet": f"bet{s} {to}",
                "raise": f"raise{s} to {to}"}[kind]

    NO_FIT = "That action does not fit there."
    NOT_IN_HAND = "That player is no longer in the hand at that point."

    def _rebuild(self, hand: dict, events: list[dict], quiet: bool = False) -> list[str]:
        """Play recorded actions again on a hand whose start or events were edited.

        Typed actions are played again as recorded, each on the street it was
        typed for; one that is no longer possible is dropped, named in the
        toast (unless ``quiet``) and returned.  Implied actions are not
        replayed: the typed action after them implies them again.  The
        exception is the implied actions of Enter ("the rest fold"), which
        are given again where it still is that player's turn.

        The event marked ``new`` is the one the user is entering now: it gets
        the friendly treatment, and if it cannot be played the edit is refused.
        """
        hand["events"] = []
        hand["ranking"] = None
        dropped = []
        for event in events:
            state = replay(hand)
            if state.phase not in BETTING:
                if event.get("new"):
                    raise ModelError(self.NO_FIT, "")
                if not event.get("auto") and event["kind"] not in MARKERS:
                    dropped.append(self._event_text(event, state))
                continue
            street = event.get("street", state.phase)
            if event["kind"] in MARKERS:
                hand["events"].append(dict(event, street=state.phase))
                continue
            if event.get("auto"):
                if event.get("close") and state.phase == street and state.to_act() == event["seat"]:
                    hand["events"].append({"street": street, "seat": event["seat"], "auto": True, "close": True,
                                           "kind": state.implied_kind(event["seat"])})
                continue
            # an action from a later street: the round before it closes with the passive defaults
            while state.phase in BETTING and BETTING.index(state.phase) < BETTING.index(street):
                if not self._close_round(hand):
                    break
                state = replay(hand)
            is_new = bool(event.get("new"))
            try:
                if state.phase != street or event["seat"] in state.folded or event["seat"] not in state.order:
                    raise ModelError(self.NOT_IN_HAND, "")
                self._append_action(hand, event["seat"], event["kind"], event.get("to"),
                                    bool(event.get("forced")), friendly=is_new, inferred=bool(event.get("inferred")))
            except (ModelError, AmountError, _NoTurn) as err:
                if is_new:
                    message = getattr(err, "message", "") or self.NO_FIT
                    raise ModelError(message, getattr(err, "fix", "")) from None
                dropped.append(self._event_text(event, state))
        if dropped and not quiet:
            self._say("No longer possible, dropped: " + "; ".join(dropped))
        return dropped

    def _event_text(self, event: dict, state: HandState) -> str:
        who = self._who(event["seat"], state.labels)
        amount = f" {fmt(event['to'])}" if event.get("to") is not None else ""
        return f"{who} {event['kind']}{amount}"

    def _op_close_round(self, a) -> None:
        hand = self._need_open_hand()
        callers = [int(s) for s in (a.get("callers") or [])]
        if not self._close_round(hand, callers):
            raise ModelError("Nobody is left to act.", "Enter the next cards or the result.")
        self._after_action(hand)

    def _close_round(self, hand: dict, callers=()) -> int:
        """Everybody still to act in this round takes the passive default (or calls, when listed)."""
        state = replay(hand)
        phase, added = state.phase, 0
        while state.phase == phase and state.to_act() is not None:
            actor = state.to_act()
            calls = actor in callers and state.owe(actor) > 0
            event = {"street": phase, "seat": actor, "kind": "call" if calls else state.implied_kind(actor),
                     "auto": not calls, "close": True}
            if state.aof and calls:
                event["kind"] = "allin"
            state.apply(event)
            hand["events"].append(event)
            added += 1
        return added

    def _op_edit_event(self, a) -> None:
        """Change an earlier action (its kind, its amount or its seat) and play the rest of the hand again."""
        hand = self._need_open_hand()
        index = self._event_index(hand, a)
        events = copy.deepcopy(hand["events"])
        old = events[index]
        kind = a.get("kind") or a.get("verb")
        amount = a.get("amount", a.get("to", a.get("text")))
        amount = None if amount == "" else amount
        if kind is None and amount is None and a.get("seat") in (None, ""):
            raise ModelError("Nothing to change.", "Send a new action, amount or seat.")
        if kind is not None:
            new_kind = KINDS.get(str(kind).strip().lower())
            if new_kind is None:
                raise ModelError(f"Unknown action {kind!r}.", "Actions: fold, check, call, bet, raise, allin.")
        elif amount is not None:
            new_kind = old["kind"] if old["kind"] in ("bet", "raise") else "raise"    # a new amount: he bet or raised
        else:
            new_kind, amount = old["kind"], old.get("to")
        seat = old["seat"] if a.get("seat") in (None, "") else self._seat_arg(a, empty_ok=True)
        events[index] = {"street": old["street"], "seat": seat, "kind": new_kind, "to": amount,
                         "forced": bool(a.get("force")), "auto": False, "new": True}
        self._rebuild(hand, events)
        self._after_action(hand)

    def _op_remove_event(self, a) -> None:
        hand = self._need_open_hand()
        index = self._event_index(hand, a)
        if hand["events"][index].get("auto"):
            raise ModelError("That action was not typed: it follows from the others.",
                             "Change the action that caused it.")
        events = copy.deepcopy(hand["events"])
        del events[index]
        self._rebuild(hand, events)
        self._after_action(hand)

    def _event_index(self, hand: dict, a: dict) -> int:
        """The stored event behind an item of the hand line (``index`` is the item's ``i``)."""
        raw = a.get("index", a.get("i"))
        if raw is None and a.get("event") is not None:
            index = _whole(a["event"], "event")
        else:
            try:
                if int(raw) < 0:                        # Python would count from the end: the last step, silently
                    raise IndexError(raw)
                item = self._line(hand, replay(hand))[int(raw)]
            except (TypeError, ValueError, IndexError, OverflowError):
                raise ModelError("That step is not on the hand line.", "Select an action on the line.") from None
            if item["kind"] != "act":
                raise ModelError("That step is cards, not an action.", "Retype the cards to change them.")
            if item["event"] is None:
                raise ModelError("That action was not typed: the player is sitting out.",
                                 "Mark the player as back first.")
            index = item["event"]
        if not 0 <= index < len(hand["events"]):
            raise ModelError("That step is not on the hand line.", "Select an action on the line.")
        return index

    @staticmethod
    def _decisions(hand: dict, state: HandState) -> list[dict]:
        """Hero's decisions in the hand: what the coach said (when it was kept) and what he did."""
        decisions = []
        for number, entry in enumerate(e for e in state.log if e["seat"] == HERO):
            shown = hand["advice"].get(str(number)) or {}
            did = "allin" if entry["allin"] and entry["kind"] in ("bet", "raise") else entry["kind"]
            decisions.append({"street": entry["street"], "did": did, "advice": shown.get("verb", ""),
                              "deviated": _deviated(shown.get("verb"), shown.get("follow"),
                                                    entry["kind"], entry["allin"])})
        return decisions

    def _after_action(self, hand: dict) -> None:
        """The hand may have ended by itself (everybody folded): then it is settled at once."""
        if not hand["settled"] and replay(hand).phase == "done":
            self._settle(hand)

    # ---- the result ----------------------------------------------------------------------------

    def _op_award(self, a) -> None:
        hand = self._need_open_hand()
        state = replay(hand)
        if state.phase != "showdown":
            raise ModelError("The betting is not over.", "Finish the round first (Enter gives the rest their default).")
        ranking = self._ranking(a, hand, state)
        state.award(ranking)                            # raises ModelError naming a pot nobody was given
        hand["ranking"] = ranking
        self._settle(hand)

    def _ranking(self, a: dict, hand: dict, state: HandState) -> list[list[int]]:
        """Who won, as tiers of seats, best hand first."""
        live = state.live()
        hero = str(a.get("hero") or "").lower()
        if a.get("ranking"):
            ranking = [[int(s) for s in (tier if isinstance(tier, (list, tuple)) else [tier])] for tier in a["ranking"]]
        elif a.get("winners"):
            ranking = [[int(s) for s in a["winners"]]]  # they tie
        elif a.get("winner", a.get("seat")) not in (None, ""):
            ranking = [[int(a.get("winner", a.get("seat")))]]
        elif a.get("split") or hero in ("split", "tie"):
            ranking = [list(live)]
        elif hero in ("won", "win", "w"):
            ranking = [[HERO]]
        elif hero in ("lost", "lose", "l"):
            others = [s for s in live if s != HERO]
            if len(others) != 1:
                raise ModelError("More than one opponent is in the pot.", "Click the player who won.")
            ranking = [others]
        else:
            ranking = self._ranking_from_cards(hand, state)
        for tier in ranking:
            for seat in tier:
                if seat not in live:
                    raise ModelError(f"{self._who_is(seat, state.labels)} not in the pot.",
                                     "Choose among the players still in the hand.")
        return ranking

    def _ranking_from_cards(self, hand: dict, state: HandState) -> list[list[int]]:
        """With the board and every hand known, the cards decide."""
        cards = dict(hand["shown"])
        if len(hand["hero_cards"]) == 4:
            cards[str(HERO)] = hand["hero_cards"]
        missing = [s for s in state.live() if str(s) not in cards]
        if len(hand["board"]) < 5 or missing:
            raise ModelError("Who won?", "Name the winner, or enter the board and the cards shown.")
        board = parse_cards("".join(hand["board"]))
        value = {s: evaluate(parse_cards(cards[str(s)]) + board) for s in state.live()}
        tiers: list[list[int]] = []
        for seat in sorted(value, key=lambda s: -value[s]):
            if tiers and value[tiers[-1][0]] == value[seat]:
                tiers[-1].append(seat)
            else:
                tiers.append([seat])
        return tiers

    def _settle(self, hand: dict) -> None:
        """The hand is over: stacks, busts, players left, the tally, the history and the button follow."""
        data, seats = self.data, self._seats()
        state = replay(hand)
        hand["settled"] = True
        for seat in state.order:
            if str(seat) in seats:
                seats[str(seat)]["stack"] = state.stack[seat]
        busted = state.busted()
        hand["busted"] = busted
        self._file_hand(hand, state, skipped=False)     # while every player still has his name at the table
        gone = [s for s in hand["leaving"] if s not in busted]
        for seat in gone:
            self._take_seat_away(seat)
        refill = data["rules"]["allin_or_fold"] and data["rules"]["refill"]
        for seat in busted:
            if refill:
                seats[str(seat)]["stack"] = data["rules"]["cap_bb"]      # he sits down again with a full stack
                if seat != HERO:
                    seats[str(seat)].update(name="", type="unknown", note="", stale=False)   # a new player
            else:
                self._take_seat_away(seat)
        # a bust entered by hand (the bust intent) was already counted when it was entered
        self._count_bust(len([s for s in busted if s not in hand["leaving"]]))
        if HERO in state.order:
            if self.mode == "aof":
                tally = data["tally"]
                tally["net_bb"] = _n(tally["net_bb"] + state.net(HERO))
                tally["hands"] += 1
            if HERO in busted and not refill and self.mode != "spin":      # (Spin says how the game ended)
                self._say("You are out. Type a new stack on your seat to re-enter, or start a new tournament."
                          if self.mode == "tournament" else
                          "You are out. Type a new stack on your seat to sit down again.")
        self._spin_game_check()
        self._advance_button(hand)

    def _advance_button(self, hand: dict | None = None) -> None:
        """A hand was played: the button moves on by the table's rule (``next_button``).

        The seats of that hand's button and blinds are kept until the next hand is over, so a
        player marked as out afterwards (most busts are typed that way) moves the button too.
        """
        table = self.data["table"]
        if hand is not None:
            button, order = hand["button"], hand["order"]
        else:                                           # a hand nobody tracked: the blinds were where the table has them
            button, order = table["button"], preflop_order(self._dealt_in(), table["button"])
        if len(order) < 2:
            return
        table["moved"] = {"button": button, "sb": order[-2], "bb": order[-1]}
        self._place_button(after_a_hand=True)

    def _place_button(self, after_a_hand: bool = False) -> None:
        """Put the button where the hand before and the players now at the table say it goes.

        Also called when a player leaves or sits down between hands; then it speaks only when the
        button moved.
        """
        table = self.data["table"]
        last, dealt = table.get("moved"), self._dealt_in()
        if not last or not dealt:
            return
        rule = self.data["rules"].get("button_rule", D.BUTTON_RULE)
        table["button"] = seat = next_button(last["button"], last["sb"], last["bb"], dealt, rule)
        keys = f"{key_for('button_back')} and {key_for('button_on')} move it"
        news = ""
        if seat not in dealt:
            news = f"Dead button on seat {seat}: its player is out. {keys}"
        elif last["sb"] not in dealt or last["bb"] not in dealt:
            # a blind went out: sites differ here, and a hand without a small blind cannot be entered
            news = f"Button on seat {seat}: check it against your table ({keys})"
        if after_a_hand or news != last.get("said"):
            self._say(news)
        last["said"] = news

    def _op_skip_hand(self, a) -> None:
        hand = self._open_hand()
        if hand is None:
            self.data["hand"] = None                    # a hand went by that was not tracked at all
            self._advance_button()
            self._say("Button moved on")
            return
        self._skip_hand(hand, hero_in=_truth(a.get("hero_in")))
        self.data["hand"] = None

    def _skip_hand(self, hand: dict, hero_in: bool) -> None:
        """Leave a hand without its result.

        Players who folded on the record lose exactly what they put in.  Hero
        counts as folded while he still can fold.  Everybody still in keeps
        his start stack, marked as unsure (``~``) until it is typed again.
        """
        seats = self._seats()
        state = replay(hand)
        if not hero_in and HERO in state.live() and state.stack[HERO] > 0 and state.phase in BETTING:
            try:
                events = imply_until(replay(hand), HERO)     # hero's turn is coming in this round: he folds
                hand["events"].extend(events + [{"street": state.phase, "seat": HERO, "kind": "fold", "auto": True}])
                state = replay(hand)
            except (_NoTurn, ModelError):
                pass
        if state.phase == "done":
            self._settle(hand)                          # hero's fold ended it: a real result after all
            return
        for seat in state.order:
            entry = seats.get(str(seat))
            if entry is None:
                continue
            if seat in state.folded:
                entry["stack"] = state.stack[seat]      # he is out of the pot: this much is certain
            else:
                entry["stale"] = True                   # the pot went somewhere we did not see
        for seat in hand["leaving"]:
            self._take_seat_away(seat)
        hand["settled"] = hand["skipped"] = True
        self._file_hand(hand, state, skipped=True)
        self._advance_button(hand)
        self._say(f"Hand {hand['no']} left without a result: check the stacks marked ~")

    # ---- Spin games ----------------------------------------------------------------------------

    def _spin_game_check(self) -> None:
        """Spin: the game ends when one player holds every chip, and for hero when he is out."""
        if self.mode != "spin" or self.data["game"]["over"]:
            return
        alive = self._dealt_in()
        if HERO in alive and len(alive) > 1:
            return
        won = alive == [HERO]
        self.data["game"]["over"] = "won" if won else "lost"
        self.data["tally"]["games"] += 1
        self.data["tally"]["wins"] += 1 if won else 0
        again = f"Press {key_for('deal').upper()} for a new one."
        self._say(f"You won this game. {again}" if won else f"You lost this game. {again}")

    def _op_new_game(self, a) -> None:
        if self.mode != "spin":
            raise ModelError("New game belongs to Spin & Gold.", "Use New session in the other modes.")
        stack = a.get("start_stack", a.get("stack"))
        game, result = self.data["game"], str(a.get("result") or "").lower()
        if not game["over"] and result in ("won", "lost"):
            self.data["tally"]["games"] += 1            # the game was not played out here: the user says how it ended
            self.data["tally"]["wins"] += 1 if result == "won" else 0
        elif not game["over"] and game["hands"]:
            self._say("The game before was not finished: it is not counted")
        self._new_game(parse_amount(stack) if stack not in (None, "") else None)

    def _new_game(self, stack) -> None:
        """Three fresh stacks and the first blind level; the tally stays."""
        data = self.data
        if self._open_hand():
            self._forget_hand()
        stack = stack or data["game"]["start_stack"]
        data["hand"] = None
        data["game"] = {"start_stack": stack, "over": None, "hands": 0}
        data["tournament"]["start_stack"] = stack
        hero = self._seats()[str(HERO)]
        hero["stack"] = stack
        size = data["table"]["size"]
        data["table"]["seats"] = {str(n): new_seat("", stack) for n in range(2, size + 1)}
        data["table"]["seats"][str(HERO)] = hero
        data["table"].pop("moved", None)
        data["structure"].update(index=0, custom=None)
        self._say(f"New game: {fmt(stack)} chips each")

    # ---- the hand history ----------------------------------------------------------------------------

    def _file_hand(self, hand: dict, state: HandState, skipped: bool) -> None:
        """Add the finished hand to the session's history."""
        decisions = self._decisions(hand, state)
        key = next((d for d in decisions if d["deviated"]), None) or next((d for d in decisions if d["advice"]), None) \
            or (decisions[0] if decisions else {"advice": "", "did": "", "deviated": False})
        in_hand = HERO in state.order
        exact = in_hand and (HERO in state.folded or not skipped)
        # left without a result after hero's fold: for him the hand is complete (who won the rest is not known)
        entry = {"no": hand["no"], "cards": hand["hero_cards"], "pos": state.labels.get(HERO, ""),
                 "advice": key["advice"], "did": key["did"], "deviated": any(d["deviated"] for d in decisions),
                 "net": state.net(HERO) if exact else None, "skipped": skipped and HERO not in state.folded,
                 "text": self._hand_text(hand, state, skipped)}
        hands = self.data["hands"]
        hands.append(entry)
        self.data["game"]["hands"] += 1
        extra = len(hands) - D.HANDS_KEPT
        if extra > 0:                                   # the file does not grow for ever
            del hands[:extra]
            self.data["hands_base"] += extra

    def _hand_text(self, hand: dict, state: HandState, skipped: bool) -> str:
        """The hand as a few lines of text, for copying."""
        level, bb = hand["level"], hand["level"]["bb"]
        ante = ""
        if level["ante"]:
            ante = f" ante {fmt(level['ante'])}"
        elif level["bb_ante"]:
            ante = f" bb ante {fmt(level['bb_ante'])}"
        head = f"Hand {hand['no']} | {fmt(level['sb'])}/{fmt(level['bb'])}{ante} | {state.n} players"
        if HERO in state.order:
            head += f" | you {state.labels[HERO]} {hand['hero_cards'] or '??'} ({fmt_bb(state.start[HERO], bb)})"
        lines = [head]
        for street in BETTING:
            # players who were only passed by (implied folds) are left out; hero's own fold is not
            acts = [e for e in state.log if e["street"] == street
                    and not (e["auto"] and e["kind"] == "fold" and e["seat"] != HERO)]
            cards = " ".join(c for c, s in zip(hand["board"], STREET_OF_CARD) if s == street)
            if not acts and not cards:
                continue
            title = street.capitalize() + (f" {cards}" if cards else "")
            said = ", ".join(self._act_text(e, state, bb) for e in acts) or "no action recorded"
            lines.append(f"{title}: {said}")
        if skipped and HERO in state.folded:
            lines.append(f"Result: you folded ({fmt(state.net(HERO))}); who won the pot was not recorded")
        elif skipped:
            lines.append("Result: not recorded")
        elif state.result:
            lines.append("Result: " + self._result_text([(s, w) for s, w in state.result["won"].items() if w > 0], state))
            if HERO in state.order:
                lines.append(f"You: {'+' if state.net(HERO) > 0 else ''}{fmt(state.net(HERO))}")
        for d in self._decisions(hand, state):
            if d["advice"]:
                lines.append(f"Coach ({d['street']}): {d['advice']} | you: {d['did']}"
                             + (" | deviated" if d["deviated"] else ""))
        return "\n".join(lines)

    def _wins_text(self, seat: int, amount, state: HandState, first: bool = True) -> str:
        """One winner, by seat number and that hand's position: "Seat 4 (BB) wins 81,000", "You (CO) win 5,650".

        The same words as the coach's line for a finished hand (``advice.result_line``); a player's
        name can change or go with him, the seat and the position of that hand cannot.
        """
        won = fmt(amount) + ("bb" if self.mode == "aof" else "")       # All-In or Fold counts in big blinds
        position = state.labels.get(seat, "")
        where = f" ({position})" if position else ""
        if seat == HERO:
            return f"{'You' if first else 'you'}{where} win {won}"
        return f"{'Seat' if first else 'seat'} {seat}{where} wins {won}"

    def _result_text(self, winners, state: HandState) -> str:
        """Every winner of the hand in one line: "You (CO) win 2,825, seat 5 (BB) wins 2,825"."""
        return ", ".join(self._wins_text(seat, amount, state, first=k == 0) for k, (seat, amount) in enumerate(winners))

    def _act_text(self, entry: dict, state: HandState, bb) -> str:
        who = self._who(entry["seat"], state.labels)
        kind = entry["kind"]
        if kind in ("bet", "raise"):
            word = "all-in" if entry["allin"] else kind
            return f"{who} {word} {fmt_bb(entry['to'], bb)}"
        if kind == "call" and entry["allin"]:
            return f"{who} call all-in"
        return f"{who} {kind}"

    # ==========================================================================
    # The view
    # ==========================================================================

    def view(self, toast: bool = False) -> dict:
        """The JSON the browser renders (build spec, section 6)."""
        data = self.data
        hand = data["hand"]
        state = replay(hand) if hand else None
        target, at_target = (None, None)
        if hand and not hand["settled"]:
            target, at_target = self._target(hand, state)
        journal = data["journal"]
        return {
            "rev": self.rev,
            "mode": data["mode"],
            "unit": "bb" if data["mode"] == "aof" else self.app["unit"],
            "deck": self.app["deck"],
            "can": {"undo": bool(journal["undo"]), "redo": bool(journal["redo"])},
            "strip": self._view_strip(hand),
            "table": self._view_table(hand, state, target),
            "hand": self._view_hand(hand, state, target, at_target) if hand else None,
            "history": self._view_history(),
            "toast": self._view_toast(toast),
            "unsaved": self.unsaved,                    # "" when the files hold everything, else why they do not
            "first_run": not data["started"],
            "hero_out": self._hero_out(),               # no chips and no hand of his running: re-enter, or start anew
            "settings": {"ladder": data["structure"]["ladder"],
                         "ladders": [{"name": n, "label": D.LADDERS[n]["label"]} for n in D.LADDERS_FOR_MODE[data["mode"]]],
                         "levels": [[lv["sb"], lv["bb"], lv.get("ante", 0)] for lv in data["structure"]["levels"]],
                         "notice_seen": self.app["notice_seen"], "modes": list(D.MODES),
                         "button_rule": data["rules"].get("button_rule", D.BUTTON_RULE),
                         "size_limits": list(D.SIZE_LIMITS[data["mode"]]),
                         "keys": KEYS_FOR_THE_PAGE},
        }

    def _view_toast(self, of_intent: bool):
        """What the page says once: the lines of the intent just made, and news of the saved files after a start."""
        lines = self._notices + (self._toast if of_intent else [])
        if not lines:
            return None
        redo = of_intent and getattr(self, "_toast_redo", False)
        return {"text": " · ".join(lines), "undo": bool(self.data["journal"]["undo"]) and not redo, "redo": redo}

    def _view_strip(self, hand) -> dict:
        data, t, config = self.data, self.data["tournament"], self.data["config"]
        now = session_level(data)
        level = hand["level"] if hand and not hand["settled"] else now      # a hand keeps the blinds it was dealt with
        waiting = None
        if any(now[k] != level[k] for k in ("sb", "bb", "ante", "bb_ante")):       # new blinds wait for the next hand
            waiting = {"number": now["number"], "sb": now["sb"], "bb": now["bb"], "ante": now["ante"] or now["bb_ante"]}
        avg = average_stack(data) if data["mode"] == "tournament" else None
        tally = None
        if data["mode"] == "spin":
            tally = {"games": data["tally"]["games"], "wins": data["tally"]["wins"]}
        elif data["mode"] == "aof":
            tally = {"net_bb": data["tally"]["net_bb"], "hands": data["tally"]["hands"], "banked": data["tally"]["banked"]}
        return {
            "level": {"number": level.get("number"), "sb": level["sb"], "bb": level["bb"],
                      "ante": level["ante"] or level["bb_ante"], "ante_kind": level["ante_kind"],
                      "pending": waiting},
            "remaining": t["remaining"], "paid": t["paid"], "entrants": t["entrants"],
            "start_stack": t["start_stack"], "buyin": t["buyin"],
            "avg_stack": _n(round(avg)) if avg else None,
            "avg_bb": round(avg / level["bb"], 1) if avg and level["bb"] else None,
            "stage": stage_of(data),
            "icm": icm_level(data),
            "prizes_typed": prizes_typed(data),         # of the places paid: the others take the last prize typed
            "style": config["style"], "plan": config["plan"], "opponents": config["opponents"],
            "reentry_open": bool(t["reentry_open"]), "bounty": bool(t["bounty"]),
            "button_rule": data["rules"].get("button_rule", D.BUTTON_RULE),
            "tally": tally,
            "name": t["name"], "payouts": t["payouts"], "pace": config["pace"],
            "game": dict(data["game"]) if data["mode"] == "spin" else None,
        }

    def _view_table(self, hand, state, target) -> dict:
        table = self.data["table"]
        live_hand = bool(hand) and not hand["settled"]
        if live_hand:                                   # a hand being played keeps its own button and positions
            labels, button, bb = state.labels, hand["button"], hand["level"]["bb"]
        else:                                           # between hands: where the next hand will be dealt from
            labels = seat_labels(preflop_order(self._dealt_in(), table["button"]))
            button, bb = table["button"], session_level(self.data)["bb"]
        seats = []
        for number in range(1, table["size"] + 1):
            entry = table["seats"].get(str(number))
            in_hand = bool(hand) and number in state.order
            if entry is None:
                seats.append({"seat": number, "empty": True, "is_hero": False, "name": "", "pos": "",
                              "is_button": number == button, "stack": 0, "stack_bb": 0, "stale": False,
                              "status": "empty", "type": "unknown", "note": "", "in_hand": False, "folded": False,
                              "all_in": False, "bet": 0, "bet_bb": 0, "is_target": False, "delta": None})
                continue
            playing = live_hand and in_hand
            stack = state.stack[number] if playing else entry["stack"]
            bet = state.in_front[number] if playing else 0
            status = entry["status"]
            if entry["stack"] <= 0 and not playing:
                status = "busted"                       # no chips: not dealt in until a stack is typed
            seats.append({
                "seat": number, "empty": False, "is_hero": number == HERO, "name": entry["name"],
                "pos": labels.get(number, ""), "is_button": number == button,
                "stack": stack, "stack_bb": round(stack / bb, 1) if bb else 0, "stale": bool(entry["stale"]),
                "status": status, "type": entry["type"], "note": entry["note"],
                "in_hand": in_hand, "folded": in_hand and number in state.folded,
                "all_in": playing and number not in state.folded and state.stack[number] <= 0,
                "bet": bet, "bet_bb": round(bet / bb, 1) if bb else 0,
                "is_target": number == target,
                "delta": state.net(number) if hand and hand["settled"] and in_hand and not hand.get("skipped") else None,
            })
        return {"size": table["size"], "button": button, "seats": seats}

    def _target(self, hand: dict, state: HandState):
        """The player the next action is for, and the hand as it will stand at his turn.

        Hero, whenever he still owes a decision in this round (the players
        before him are taken to do the passive thing); otherwise the next
        player to act.
        """
        actor = state.to_act()
        if actor is None:
            return None, state
        if actor != HERO and HERO in state.live() and state.stack[HERO] > 0:
            ahead = replay(hand)
            try:
                imply_until(ahead, HERO)
                return HERO, ahead
            except _NoTurn:
                pass
        return actor, state

    def _needs(self, hand: dict, state: HandState) -> str:
        """What the browser should ask for now: cards, action, board, result or next."""
        if hand["settled"] or state.phase == "done":
            return "next"
        if state.phase == "showdown":
            return "result"
        hero_in = HERO in state.live()
        if hero_in and not hand["hero_cards"]:
            return "cards"
        if state.phase != "preflop":
            if hero_in and len(hand["hero_cards"]) != 4:
                return "cards"                          # a class (AKs) is enough before the flop only
            if len(hand["board"]) < BOARD_CARDS[state.phase]:
                return "board"
        return "action"

    def _legal(self, state: HandState, seat: int) -> dict:
        """What the target may do, with amounts as street totals."""
        owe, top = state.owe(seat), state.max_to(seat)
        legal = {"fold": True, "check": owe <= 0, "call": owe if owe > 0 else None,
                 "bet": None, "raise": None, "allin": top}
        if state.aof:
            legal["check"] = False
            legal["call"] = owe if owe > 0 and state.anyone_all_in() else None
            return legal
        if state.may_raise(seat):
            box = {"min": state.min_raise_to(seat), "max": top, "default": self._default_size(state, seat)}
            legal["bet" if state.bet_to == 0 else "raise"] = box
        return legal

    def _presets(self, state: HandState, seat: int) -> list[dict]:
        """Sizes offered as buttons, smallest first, ending with all-in."""
        top = state.max_to(seat)
        if state.aof:
            return [{"label": "All-in", "to": top}]
        if not state.may_raise(seat):
            return []                                   # he can only call or fold
        low = state.min_raise_to(seat)
        if state.bet_to == 0:
            sizes = [("Min", low)] + [(label, state.pot_total() * share) for label, share in D.BET_SIZES]
        elif state.phase == "preflop" and state.raises == 0:
            sizes = [(f"{x:g}x", state.bb * x) for x in D.OPEN_SIZES_BB]
        else:
            sizes = [("Min", low)] + [(f"{x:g}x", state.bet_to * x) for x in D.RERAISE_SIZES]
        presets, seen = [], set()
        for label, to in sizes:
            to = tidy(to, self._step)
            if low <= to < top and to not in seen:
                presets.append({"label": label, "to": to})
                seen.add(to)
        return presets + [{"label": "All-in", "to": top}]

    def _line(self, hand: dict, state: HandState) -> list[dict]:
        """The hand as a strip of steps: hero's cards, each action, each street's cards."""
        bb = hand["level"]["bb"]
        items: list[dict] = []
        if hand["hero_cards"]:
            items.append({"kind": "cards", "street": "preflop", "text": hand["hero_cards"]})
        for street in BETTING:
            cards = [c for c, s in zip(hand["board"], STREET_OF_CARD) if s == street]
            if cards:
                items.append({"kind": "board", "street": street, "text": " ".join(cards)})
            for entry in state.log:
                if entry["street"] != street:
                    continue
                seat = entry["seat"]
                allin = entry["allin"] and entry["kind"] in ("bet", "raise")
                stored = hand["events"][entry["event"]] if entry["event"] is not None else {}
                items.append({"kind": "act", "street": street, "seat": seat, "pos": state.labels[seat],
                              "name": self._seat_name(seat), "verb": "allin" if allin else entry["kind"],
                              "to": entry["to"], "text": self._act_text(entry, state, bb),
                              "auto": entry["auto"], "allin": entry["allin"], "event": entry["event"],
                              # nobody typed it: it follows from a later action of his ("he must have called")
                              "inferred": bool(stored.get("inferred"))})
        for i, item in enumerate(items):
            item["i"] = i
        return items

    def _seat_name(self, seat: int) -> str:
        entry = self._seats().get(str(seat)) or {}
        return entry.get("name", "")

    def _view_hand(self, hand: dict, state: HandState, target, at_target) -> dict:
        bb = hand["level"]["bb"]
        cards = hand["hero_cards"]
        needs = self._needs(hand, state)
        exact = [cards[:2], cards[2:]] if len(cards) == 4 else []
        to_call = at_target.owe(target) if target is not None else 0
        result = None
        if hand["settled"] and state.result and not hand.get("skipped"):
            winners = [{"seat": s, "name": self._seat_name(s), "pos": state.labels[s], "amount": w}
                       for s, w in state.result["won"].items() if w > 0]
            result = {"winners": winners, "pots": state.result["pots"], "fee": state.result["fee"],
                      "net": {str(s): state.net(s) for s in state.order}, "busted": hand.get("busted", []),
                      "text": self._result_text([(w["seat"], w["amount"]) for w in winners], state)}
        return {
            "no": hand["no"], "phase": state.phase, "needs": needs,
            # the seat names and the button this hand was dealt with: they stay on the pods after the
            # result, when the table's own (view.table) are already the next hand's
            "positions": {str(seat): label for seat, label in state.labels.items()}, "button": hand["button"],
            "hero_cards": exact, "hero_class": HANDS[parse_hand(cards)[0]] if cards else "",
            "want_suits": self._want_suits(hand, needs),
            "board": list(hand["board"]),
            "pot": state.pot_total(), "pot_bb": round(state.pot_total() / bb, 1),
            "to_call": to_call, "to_call_bb": round(to_call / bb, 1),
            "target": target, "target_is_hero": target == HERO,
            "legal": self._legal(at_target, target) if target is not None else None,
            "presets": self._presets(at_target, target) if target is not None else [],
            "line": self._line(hand, state),
            "pots": [{"amount": p["amount"], "eligible": p["eligible"]} for p in
                     (state.result["pots"] if state.result else state.pots())],
            "result": result,
            "street_bet": state.bet_to if state.phase in BETTING else 0,
            "shown": dict(hand["shown"]),
            # Players who act before the target and have not acted: they take the passive default
            # unless an action is typed for them.  (The page uses it to keep hero's own action typed:
            # an action for a player behind him would be his fold.)
            "before_target": [e["seat"] for e in at_target.log[len(state.log):]] if target is not None else [],
        }

    def _view_history(self) -> list[dict]:
        """Finished hands, newest first."""
        keys = ("no", "cards", "pos", "advice", "did", "deviated", "net", "text")
        recent = self.data["hands"][-D.HISTORY_IN_VIEW:]
        return [{k: entry.get(k) for k in keys} | {"skipped": bool(entry.get("skipped"))} for entry in reversed(recent)]


# ---- small functions used above ------------------------------------------------------------

def key_for(command: str, group: str = "table") -> str:
    """The first key of a command, as ``defaults.py`` has it, for sentences that name a key."""
    return next((keys[0] for keys, name, _ in D.KEYS[group] if name == command and keys), "")


def keys_for_the_page() -> dict:
    """The key map of ``defaults.py`` as the page reads it: ``{"table": [{"keys", "do", "text"}], ...}``."""
    return {group: [{"keys": list(keys), "do": command, "text": text} for keys, command, text in rows]
            for group, rows in D.KEYS.items()}


KEYS_FOR_THE_PAGE = keys_for_the_page()     # the same in every view: built once


def _not_a_number(name: str):
    """NaN and Infinity in a saved file: no stack or pot is either, so the file is damaged."""
    raise ValueError(f"{name} in a session file")


def _plain(value) -> str:
    """A number as it is typed: no separators, no exponent (1250000, 62.5)."""
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")


def _listed(words) -> str:
    """``seat 7``, ``seat 7 and seat 8``, ``seat 6, seat 7 and seat 8``."""
    words = list(words)
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _text(value, limit: int) -> str:
    """A typed name or note: trimmed, on one line, and no longer than the place it is drawn in."""
    return " ".join(str(value if value is not None else "").split())[:limit].strip()


def _finite(value, what: str) -> float:
    """A number sent as a number (not typed text): it must be one, and of a size a table can hold."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = float("nan")
    if isinstance(value, bool) or number != number or abs(number) > MAX_AMOUNT:
        raise ModelError(f"That request could not be read: check {what}.", "Send a plain number there.")
    return number


def _whole(value, what: str, limit: int = MAX_COUNT) -> int:
    """A whole number sent as a number, such as a step of +1 or a table size."""
    number = _finite(value, what)
    if not number.is_integer() or abs(number) > limit:
        raise ModelError(f"That request could not be read: check {what}.", "Send a whole number there.")
    return int(number)


def _truth(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return bool(value)


def _next(options, current):
    """The option after ``current``, round and round (for keys that cycle a setting)."""
    options = list(options)
    return options[(options.index(current) + 1) % len(options)] if current in options else options[0]


def _choice(value: str, options, what: str) -> str:
    if value not in options:
        raise ModelError(f"Unknown {what} {value!r}.", "Choose one of: " + ", ".join(options) + ".")
    return value


def _advice_kind(verb, follow):
    """The kind of action the coach's headline stands for, or ``None`` when it names none."""
    if follow and follow.get("kind"):
        kind = KINDS.get(str(follow["kind"]).lower())
        return "raise" if kind == "bet" else kind
    text = str(verb or "").upper().split(" AND ")[0]    # "RAISE and call any all-in" is a raise
    if "ALL-IN" in text or "ALLIN" in text or "SHOVE" in text:
        return "allin"
    for word, kind in (("FOLD", "fold"), ("CHECK", "check"), ("CALL", "call"), ("RAISE", "raise"),
                       ("BET", "raise")):
        if word in text:
            return kind
    return None


def _deviated(verb, follow, did: str, all_in: bool) -> bool:
    """Did hero do something else than the coach said?  Sizes are not compared, only the kind of action."""
    want = _advice_kind(verb, follow)
    if want is None:
        return False
    did = "raise" if did == "bet" else did
    if all_in and did == "raise":
        did = "allin"
    if want == "allin" and did == "call" and all_in:
        return False                                    # calling off the whole stack is the all-in that was advised
    return want != did
