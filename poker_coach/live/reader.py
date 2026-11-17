"""Screenshot -> reading of the table.

``ClaudeReader`` sends the screenshot to Claude's vision and gets a
``TableRead`` back as a structured output.  ``JsonReader`` replays a saved
reading, for tests and for checking decisions without the API.

The API key comes from the environment (``ANTHROPIC_API_KEY``) or an
``ant auth login`` profile.
"""
from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass

from .schema import TableRead, table_from_dict

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "low"            # reading a table needs little thinking, and every second counts
DEFAULT_MAX_PX = 1600             # long edge of the image sent; cards stay readable at table size
MAX_TOKENS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# models that take server-side refusal fallbacks (Haiku does not)
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1")
# dollars per million tokens: input, output (November 2026 list prices)
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-2": (8.0, 40.0)}

SYSTEM_PROMPT = """You read screenshots of online no-limit hold'em tables for a poker training tool and return what you see as JSON.

Read only what is visible. Never guess a card, a name or a number: use null, an empty string or an empty list when you cannot read something, and say what was unreadable in `unreadable`.

Cards: rank then suit, like "Ah", "Td", "9c". Ranks are 2-9, T, J, Q, K, A (write 10 as T). Suits are s, h, d, c. Many clients use a four-colour deck: spades black, hearts red, diamonds blue, clubs green.

Seats: list every occupied seat, going clockwise round the table and starting with the hero, the player whose cards are face up (usually at the bottom centre). Leave out empty seats.
- stack: the chips the player has behind, not counting chips in front of them. 0 when they are all-in.
- bet: the chips in front of the player on the current street, blinds included. 0 if none.
- folded: true when the player has no cards in this hand (mucked, greyed out, or "Fold" shown).
- has_button: true only for the seat with the dealer button (a disc marked D).
- sitting_out: true when the seat says Sitting out, Away or similar.

hero_to_act: true only when the hero's action buttons (Fold, Check, Call, Bet, Raise, All-in) are showing and active now. Pre-selection boxes such as "Check/Fold" do not count.

Pot: middle_pot is the chips already gathered in the middle from earlier betting, not counting bets still in front of players. total_pot is any pot total printed on the table (for example "Pot: 1,250" or "Total pot"), whatever it includes.

amounts_in_bb: true when stacks and bets are shown in big blinds (like "12.5 BB") instead of chips. Give every amount as the number shown.

Blinds and ante: read them from the table title or level text. ante_kind is per_player when every player posts the ante, big_blind when only the big blind posts it (a BB ante), none when there is no ante, unknown when you cannot tell.

money_text: copy exactly any visible text that shows what the game is played for: "Play Money", "Play chips", a buy-in such as "$5.40" or "€10", "Freeroll", "Tickets". Empty string if nothing like that is visible.

table_text: copy the table title, tournament name, level and blinds text you can see.

Tournament numbers (players_left, places_paid, entrants, average_stack): only when the table shows them; otherwise null."""


class ReadError(Exception):
    """The table could not be read; the message says why, for the window."""


@dataclass
class ReadResult:
    table: TableRead
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    model: str = ""


def encode_image(image, max_px: int = DEFAULT_MAX_PX) -> str:
    """A PIL image as base64 PNG, the long edge cut down to ``max_px``."""
    from PIL import Image

    img = image.convert("RGB")
    w, h = img.size
    if max(w, h) > max_px:
        scale = max_px / float(max(w, h))
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return (input_tokens * price_in + output_tokens * price_out) / 1e6


class ClaudeReader:
    """Reads a table screenshot with Claude's vision."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
                 max_px: int = DEFAULT_MAX_PX, client=None):
        self.model, self.effort, self.max_px = model, effort, max_px
        if client is None:
            import anthropic

            # a late answer is no answer: short timeout, one retry
            client = anthropic.Anthropic(timeout=30.0, max_retries=1)
        self.client = client

    def request(self, image) -> dict:
        """The keyword arguments of the API call (separate so tests can check them)."""
        kwargs = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
            "output_config": {"effort": self.effort},
            "output_format": TableRead,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": encode_image(image, self.max_px)}},
                    {"type": "text", "text": "Read this table."},
                ],
            }],
        }
        if self.model in FALLBACK_MODELS:
            # if a safety classifier declines the image, the API re-runs it on its recommended model
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def read(self, image) -> ReadResult:
        import anthropic

        start = time.time()
        try:
            resp = self.client.beta.messages.parse(**self.request(image))
        except anthropic.AuthenticationError as exc:
            raise ReadError("API key missing or wrong: set ANTHROPIC_API_KEY or run `ant auth login`") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ReadError(f"API key not allowed to use {self.model}") from exc
        except anthropic.NotFoundError as exc:
            raise ReadError(f"unknown model {self.model}") from exc
        except anthropic.RateLimitError as exc:
            raise ReadError("rate limited by the API: wait a moment") from exc
        except anthropic.BadRequestError as exc:
            raise ReadError(f"API rejected the request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise ReadError(f"API error {exc.status_code}: try again") from exc
        except anthropic.APIConnectionError as exc:
            raise ReadError("no connection to the API") from exc
        seconds = time.time() - start
        if resp.stop_reason == "refusal":
            raise ReadError("the model declined to read this image")
        if resp.stop_reason == "max_tokens":
            raise ReadError("the reading was cut off")
        table = resp.parsed_output
        if table is None:
            raise ReadError("no reading came back")
        usage = resp.usage
        in_tok = (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        out_tok = usage.output_tokens or 0
        served = getattr(resp, "model", self.model) or self.model
        return ReadResult(table, seconds, in_tok, out_tok, cost_of(served, in_tok, out_tok), served)


class JsonReader:
    """Replays a saved reading (a JSON file in the shape of ``TableRead``)."""

    def __init__(self, path: str):
        with open(path) as fh:
            self.data = json.load(fh)

    def read(self, _image=None) -> ReadResult:
        return ReadResult(table_from_dict(self.data), model="saved reading")
