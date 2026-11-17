"""What a reading of a poker table contains.

The vision model fills ``TableRead`` (the SDK turns the model into the JSON
schema of a structured output, so the answer always parses).  Every field is
required in the schema; a saved reading written by hand can leave fields out
and ``table_from_dict`` fills them in.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SeatRead(BaseModel):
    name: str = Field(description="Player name as shown; empty string if unreadable")
    stack: Optional[float] = Field(description="Chips behind, not counting chips in front of the player; 0 when all-in; null if unreadable")
    bet: float = Field(description="Chips in front of the player on the current street, blinds included; 0 if none")
    is_hero: bool = Field(description="True for the player whose cards are face up (the user)")
    has_button: bool = Field(description="True only for the seat with the dealer button")
    folded: bool = Field(description="True when the player has no cards in this hand")
    all_in: bool = Field(description="True when the player is all-in")
    sitting_out: bool = Field(description="True when the seat shows Sitting out, Away or similar")


class TableRead(BaseModel):
    is_poker_table: bool = Field(description="True when the image shows a poker table")
    money_text: str = Field(description="Exact visible text that shows what the game is played for (Play Money, a buy-in like $5.40, Freeroll); empty if none")
    table_text: str = Field(description="Table title, tournament name, level and blinds text as shown")
    hero_to_act: bool = Field(description="True only when the hero's action buttons are showing now")
    hero_cards: list[str] = Field(description="Hero's two cards like Ah, Td; empty if not visible")
    board: list[str] = Field(description="Community cards in order; empty before the flop")
    small_blind: Optional[float] = Field(description="Small blind; null if not shown")
    big_blind: Optional[float] = Field(description="Big blind; null if not shown")
    ante: Optional[float] = Field(description="Ante amount; null if not shown")
    ante_kind: Literal["none", "per_player", "big_blind", "unknown"] = Field(
        description="per_player: every player antes; big_blind: only the big blind posts it")
    amounts_in_bb: bool = Field(description="True when stacks and bets are shown in big blinds instead of chips")
    middle_pot: Optional[float] = Field(description="Chips gathered in the middle from earlier betting, not counting bets in front of players")
    total_pot: Optional[float] = Field(description="A pot total printed on the table, whatever it includes; null if none")
    players_left: Optional[int] = Field(description="Players left in the tournament, if shown")
    places_paid: Optional[int] = Field(description="Places paid, if shown")
    entrants: Optional[int] = Field(description="Entrants, if shown")
    average_stack: Optional[float] = Field(description="Average stack, if shown")
    seats: list[SeatRead] = Field(description="Every occupied seat, clockwise, starting with the hero")
    unreadable: str = Field(description="What could not be read; empty if everything was clear")


_SEAT_DEFAULTS = {"name": "", "stack": None, "bet": 0.0, "is_hero": False, "has_button": False,
                  "folded": False, "all_in": False, "sitting_out": False}
_TABLE_DEFAULTS = {"is_poker_table": True, "money_text": "", "table_text": "", "hero_to_act": True,
                   "hero_cards": [], "board": [], "small_blind": None, "big_blind": None, "ante": None,
                   "ante_kind": "unknown", "amounts_in_bb": False, "middle_pot": None, "total_pot": None,
                   "players_left": None, "places_paid": None, "entrants": None, "average_stack": None,
                   "seats": [], "unreadable": ""}


def table_from_dict(data: dict) -> TableRead:
    """A reading from a dict that may leave fields out (a saved or hand-written reading)."""
    d = {**_TABLE_DEFAULTS, **data}
    d["seats"] = [{**_SEAT_DEFAULTS, **s} for s in d.get("seats") or []]
    return TableRead.model_validate(d)
