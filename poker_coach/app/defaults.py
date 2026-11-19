"""Everything in the table app a user may want to edit, as plain data.

Change a number here and the app follows; nothing in this file is logic.
Chips are whole numbers.  In All-In or Fold every amount is in big blinds.

The tournament ladders are typical online structures, not a copy of one
lobby: when the blinds on screen differ, type them (``300/600/75``) or paste
the tournament's own levels in Settings.
"""

MODES = ("tournament", "spin", "aof")
MODE_LABELS = {"tournament": "Tournament", "spin": "Spin & Gold", "aof": "All-In or Fold"}

HERO_NAME = "You"                       # hero always sits in seat 1

# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

TABLE_SIZE = {"tournament": 8, "spin": 3, "aof": 4}                 # seats at a new table
SIZE_LIMITS = {"tournament": (2, 9), "spin": (3, 6), "aof": (4, 4)}  # smallest and biggest table
START_STACK = {"tournament": 10000, "spin": 300, "aof": 8}

# Spin & Gold is played three-handed, or six-handed (GGPoker's 6-Max): no other table size
SPIN_SIZES = (3, 6)
# The multiplier sets the starting stack (tools/spin_sim.py, from two 2026 guides)
SPIN_START_STACKS = {"x2": 300, "x3": 300, "x4": 500, "x5": 500, "x10": 500}
SPIN_BREAK_EVEN = 0.359                 # share of games a player must win to break even
# Six players (one 2026 guide): x4 and x6 are 92.5% of the games and pay the winner only, like x8;
# x10 and x20 pay two places, x100 and x200 four.  The prizes of such a game are typed (strip, "Prizes").
SPIN6_START_STACKS = {"x4": 300, "x6": 300, "x8": 500, "x10": 500, "x20": 500, "x100": 800, "x200": 800}
SPIN6_BREAK_EVEN = 0.179                # six buy-ins pay back 5.58 on average: one game in 5.58

# All-In or Fold (GGPoker): 4 seats, fixed blinds, stacks cut to 8bb at the deal
AOF_SMALL_BLIND = 0.5
AOF_BIG_BLIND = 1
AOF_CAP_BB = 8                          # chips above this leave the table at the deal
AOF_FEE_BB = 0.1                        # taken from the first pot of every hand, walks included
AOF_REFILL = True                       # a seat that lost everything sits down again with the cap
                                        # (not verified against the site: switch it off if it is wrong)

# --------------------------------------------------------------------------
# Blind ladders: (small blind, big blind, ante of every player)
# --------------------------------------------------------------------------
# The ante column is the one every player pays.  With a big-blind ante the
# app uses one big blind instead; with no ante it uses nothing.

REGULAR_LEVELS = [
    (50, 100, 12), (60, 120, 15), (75, 150, 20), (100, 200, 25), (125, 250, 30), (150, 300, 40),
    (175, 350, 45), (200, 400, 50), (250, 500, 60), (300, 600, 75), (350, 700, 85), (400, 800, 100),
    (500, 1000, 125), (600, 1200, 150), (700, 1400, 175), (800, 1600, 200), (1000, 2000, 250),
    (1250, 2500, 300), (1500, 3000, 400), (1750, 3500, 450), (2000, 4000, 500), (2500, 5000, 600),
    (3000, 6000, 750), (3500, 7000, 850), (4000, 8000, 1000), (5000, 10000, 1250), (6000, 12000, 1500),
    (7000, 14000, 1750), (8000, 16000, 2000), (10000, 20000, 2500), (12500, 25000, 3000),
    (15000, 30000, 4000), (17500, 35000, 4500), (20000, 40000, 5000), (25000, 50000, 6000),
    (30000, 60000, 7500), (35000, 70000, 8500), (40000, 80000, 10000), (50000, 100000, 12500),
]

TURBO_LEVELS = [
    (50, 100, 12), (75, 150, 20), (100, 200, 25), (150, 300, 40), (200, 400, 50), (250, 500, 60),
    (300, 600, 75), (400, 800, 100), (500, 1000, 125), (600, 1200, 150), (800, 1600, 200),
    (1000, 2000, 250), (1250, 2500, 300), (1500, 3000, 400), (2000, 4000, 500), (2500, 5000, 600),
    (3000, 6000, 750), (4000, 8000, 1000), (5000, 10000, 1250), (6000, 12000, 1500),
    (8000, 16000, 2000), (10000, 20000, 2500), (12500, 25000, 3000), (15000, 30000, 4000),
    (20000, 40000, 5000), (25000, 50000, 6000), (30000, 60000, 7500), (40000, 80000, 10000),
    (50000, 100000, 12500),
]

# Spin & Gold: the ladder of tools/spin_sim.py, no ante
SPIN_LEVELS = [
    (10, 20, 0), (15, 30, 0), (20, 40, 0), (30, 60, 0), (40, 80, 0), (50, 100, 0), (60, 120, 0),
    (75, 150, 0), (90, 180, 0), (100, 200, 0), (125, 250, 0), (150, 300, 0), (200, 400, 0),
    (250, 500, 0), (300, 600, 0), (400, 800, 0), (500, 1000, 0), (600, 1200, 0), (800, 1600, 0),
    (1000, 2000, 0), (1250, 2500, 0), (1500, 3000, 0),
]

AOF_LEVELS = [(AOF_SMALL_BLIND, AOF_BIG_BLIND, 0)]          # fixed: there is no level to move to

LADDERS = {
    "regular": {"label": "Regular (10 to 12 minute levels)", "minutes": 10, "levels": REGULAR_LEVELS},
    "turbo": {"label": "Turbo (5 to 6 minute levels)", "minutes": 5, "levels": TURBO_LEVELS},
    "spin": {"label": "Spin & Gold", "minutes": 2, "levels": SPIN_LEVELS},
    "aof": {"label": "All-In or Fold (fixed)", "minutes": 0, "levels": AOF_LEVELS},
}
LADDER_FOR_MODE = {"tournament": "turbo", "spin": "spin", "aof": "aof"}        # the ladder a new session starts on
LADDERS_FOR_MODE = {"tournament": ("turbo", "regular"), "spin": ("spin",), "aof": ("aof",)}

# When a ladder runs out, the big blind keeps climbing through these steps,
# then the same steps times ten, and so on: ... 80k, 100k, 125k, 150k, 200k ...
# The small blind stays half the big blind and the ante keeps its share of it.
CONTINUE_STEPS = (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8)

# Who pays the ante: "none", "player" (every player) or "bb" (the big blind pays one for the table)
ANTE_KINDS = ("none", "player", "bb")
ANTE_KIND = {"tournament": "player", "spin": "none", "aof": "none"}     # GGPoker tournaments: every player antes
ANTE_SHARE_OF_BB = 0.125                # a typed big blind alone gets this ante when every player antes

# A big blind that cannot cover both the ante and the blind: which is paid first.
# "ante_first" is what the push/fold solver assumes; "blind_first" is the other house rule.
SHORT_POST = "ante_first"

# Where the dealer button goes after a hand in which a player went out.
# "dead": the big blind always moves on by one player, and the button may rest on the empty seat
# of a player who is out (the rule of live rooms and of most tournament sites).
# "forward": the button always goes to the next player, and the two players after it post.
BUTTON_RULES = ("dead", "forward")
BUTTON_RULE = "dead"

# --------------------------------------------------------------------------
# Bet and raise sizes offered as buttons
# --------------------------------------------------------------------------

OPEN_SIZES_BB = (2, 2.2, 2.5, 3)        # the first raise before the flop, in big blinds
OPEN_DEFAULT_BB = 2.2
RERAISE_SIZES = (2.5, 3, 4)             # a raise over a bet or a raise: times the bet being raised
RERAISE_DEFAULT = 3
BET_SIZES = (("33%", 1 / 3), ("50%", 1 / 2), ("66%", 2 / 3), ("Pot", 1.0))   # a bet, as a share of the pot
BET_DEFAULT = 1 / 2

# --------------------------------------------------------------------------
# Tournament and coach settings
# --------------------------------------------------------------------------

STYLES = ("cash", "survive", "maxev")   # cash first / survive, then win / max EV
STYLE = "survive"
PLANS = ("full", "allin")               # full poker / all-in or fold
PLAN = "full"
PACES = ("online", "fast", "live")      # seconds a hand, for the fold clock
PACE = "online"
OPPONENTS = {                           # the table-wide opponent type per mode; the first is the default
    "tournament": ("unknown", "loose", "tight"),
    "spin": ("solid", "loose", "very-loose"),
    "aof": ("solid", "loose", "very-loose"),
}
UNITS = ("chips", "bb")                 # how numbers are shown; All-In or Fold is always big blinds
DECKS = ("one-ink", "four-colour")
# Whose action the page asks for first.  "turn": the player whose turn it is at the table, one after the
# other, and the user when it is theirs.  "hero": the user's own decision at once (the players in front
# are taken to fold or check until an action is typed for them).
ORDERS = ("turn", "hero")
ORDER = "turn"

# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------
# One row per command: the keys that run it, the command, and the line shown
# by "?".  Change a key here and both the page and that list follow.  The
# commands themselves are in static/controller.js (COMMANDS, SEAT_COMMANDS).
#
# A key is named as the browser names it: a letter in lower case ("n"), a
# sign as it is typed ("?", "{", "+"), or Space, Enter, Backspace, Delete,
# Escape, ArrowLeft, ArrowRight.  Held keys go in front: "Shift+S",
# "Ctrl+z", "Ctrl+Backspace", "Alt+1".  The seat digits 1 to 9 and the card
# keys (2 to 9, t j q k a; s h d c; s or o for suited, offsuit) are fixed.

KEYS_TABLE = [                          # between hands and while a hand is played
    (("n",), "deal", "New hand, next hand. Spin & Gold: a new game of 300 chips once one is over"),
    (("Shift+N",), "new_game_500", "Spin & Gold: a new game of 500 chips"),
    (("Space",), "follow", "Do what the coach says"),
    (("f",), "fold", "Fold"),
    (("c",), "call", "Call"),
    (("x",), "check", "Check"),
    (("b",), "bet", "Bet. Your own: type the amount, then Enter. An opponent's is recorded at the usual size; E changes it"),
    (("r",), "raise", "Raise. Your own: type the amount, then Enter. An opponent's is recorded at the usual size; "
                      "E changes it"),
    (("a",), "allin", "All-in"),
    (("Enter",), "accept", "Before your action: the players in front fold (or check), the keys are yours. "
                           "After it: the rest fold (or check). While a street's cards are wanted: skip the board. "
                           "While a split is ticked: split"),
    (("w",), "won", "You won the pot"),
    (("l",), "lost", "You lost a heads-up pot"),
    (("Shift+W",), "split", "Split pot. Three or more players: tick who shares it with the seat numbers, then Enter"),
    (("Backspace", "z", "Ctrl+z"), "undo", "Undo"),
    (("Ctrl+y", "Ctrl+Shift+Z"), "redo", "Redo"),
    (("Ctrl+Backspace",), "discard", "Discard the hand"),
    (("ArrowLeft",), "line_back", "Previous step of the hand"),
    (("ArrowRight",), "line_on", "Next step of the hand"),
    (("e",), "edit", "Change the amount of the selected bet (or of the last one)"),
    (("Delete",), "delete", "Delete the selected action"),
    (("[",), "button_back", "Dealer button one seat back"),
    (("]",), "button_on", "Dealer button one seat forward"),
    (("{",), "seat_fewer", "One seat fewer"),
    (("}",), "seat_more", "One seat more"),
    (("+", "="), "blinds_up", "Blinds up"),
    (("-",), "blinds_down", "Blinds down"),
    (("Shift+B",), "blinds", "Type the blinds: 300/600/75, or 600 alone"),
    (("Shift+A",), "ante", "Ante: none, every player, big blind"),
    ((",",), "left_minus", "Players left minus one"),
    ((".",), "left_plus", "Players left plus one"),
    (("<",), "left_minus_ten", "Players left minus ten"),
    ((">",), "left_plus_ten", "Players left plus ten"),
    (("Shift+S",), "stacks", "Type every stack, clockwise"),
    (("s",), "my_stack", "Your own stack"),
    (("o",), "my_seat_out", "Sit out, sit back in"),
    (("i",), "tournament", "Tournament numbers"),
    (("g",), "style", "Style (Spin & Gold and All-In or Fold: the opponents)"),
    (("v",), "unit", "Chips or big blinds"),
    (("y",), "history", "Hand history"),
    (("?",), "keys", "This list"),
    (("Alt+1",), "mode_tournament", "Tournament"),
    (("Alt+2",), "mode_spin", "Spin & Gold"),
    (("Alt+3",), "mode_aof", "All-In or Fold"),
    (("Escape",), "cancel", "Cancel, close. In a field: the old value comes back"),
]

KEYS_SEAT = [                           # after a seat digit (the seat's menu is open)
    (("f", "c", "x", "b", "r", "a"), "act", "That player folds, calls, checks, bets, raises, moves all-in"),
    (("w",), "won", "That player won the pot"),
    (("s",), "stack", "Stack"),
    (("e",), "name", "Name"),
    (("t",), "type", "Type: then one of the type keys below"),
    (("m",), "note", "Note"),
    (("o",), "sit_out", "Sit out, sit back in"),
    (("d",), "button", "Dealer button here (an empty seat too)"),
    (("k",), "bust", "Bust: the seat is cleared and one player fewer is left"),
    (("Delete",), "clear", "Clear the seat: the player left the table"),
]

KEYS_TYPE = [                           # after a seat digit and the type key
    (("n",), "nit", "Nit"), (("t",), "tight", "Tight"), (("g",), "tag", "Tight-aggressive"),
    (("l",), "lag", "Loose-aggressive"), (("o",), "loose", "Loose"), (("s",), "station", "Calling station"),
    (("m",), "maniac", "Maniac"), (("u",), "unknown", "Unknown"),
]

KEYS = {"table": KEYS_TABLE, "seat": KEYS_SEAT, "type": KEYS_TYPE}

# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------

NAME_LENGTH = 40                        # a player's name is cut to this many characters
NOTE_LENGTH = 500                       # ... and a note to this many (every undo step carries a copy)
TOURNAMENT_NAME_LENGTH = 80
UNDO_LIMIT = 200                        # snapshots kept, one per accepted change
HISTORY_IN_VIEW = 200                   # finished hands sent to the browser, newest first
HANDS_KEPT = 500                        # finished hands kept in the session file
REMAINING_MINUTES_KEPT = 60             # time-stamps of "players left" kept for the fold clock: this far back ...
REMAINING_MARKS_KEPT = 60               # ... and no more than this many
