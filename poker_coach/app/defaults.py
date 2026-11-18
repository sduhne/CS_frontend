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
SIZE_LIMITS = {"tournament": (2, 9), "spin": (3, 3), "aof": (4, 4)}  # smallest and biggest table
START_STACK = {"tournament": 10000, "spin": 300, "aof": 8}

# Spin & Gold: the multiplier sets the starting stack (tools/spin_sim.py, from two 2026 guides)
SPIN_START_STACKS = {"x2": 300, "x3": 300, "x4": 500, "x5": 500, "x10": 500}
SPIN_BREAK_EVEN = 0.359                 # share of games a player must win to break even

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

# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------

UNDO_LIMIT = 200                        # snapshots kept, one per accepted change
HISTORY_IN_VIEW = 200                   # finished hands sent to the browser, newest first
HANDS_KEPT = 500                        # finished hands kept in the session file
REMAINING_MINUTES_KEPT = 60             # time-stamps of "players left" kept for the fold clock: this far back ...
REMAINING_MARKS_KEPT = 60               # ... and no more than this many
