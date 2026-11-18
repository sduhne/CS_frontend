"""Grab the table from the screen, and decide when it is worth reading.

Reading costs an API call and a few seconds, so the loop reads only when it
matters:

* ``ButtonWatch`` (recommended): the area where the poker client shows the
  Fold / Call / Raise buttons is compared with how it looks when it is not
  the player's turn.  When the buttons appear, read once; read again only
  after they have gone and come back.
* ``ChangeWatch`` (no setup): read when the table has changed and then held
  still, at most once every few seconds.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

THUMB = (64, 40)


@dataclass
class Rect:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> "Rect":
        parts = [int(float(x)) for x in str(text).replace(" ", "").split(",")]
        if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
            raise ValueError("a region is left,top,width,height in pixels, e.g. 100,80,1280,900")
        return cls(*parts)

    def as_list(self) -> list[int]:
        return [self.left, self.top, self.width, self.height]

    def box(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)


def thumb(image) -> list[int]:
    """A tiny grey copy of an image, to compare frames cheaply."""
    return list(image.convert("L").resize(THUMB).tobytes())


def difference(a: list[int] | None, b: list[int] | None) -> float:
    """Mean absolute difference of two thumbnails, 0 to 255."""
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def screen_grabber():
    """An ``mss`` screen grabber (``mss.MSS`` in new versions, ``mss.mss`` in old ones)."""
    import mss

    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


class Grabber:
    """Screen grabs of one region (``mss``; create it in the thread that uses it)."""

    def __init__(self, region: Rect | None = None, monitor: int = 1):
        self.sct = screen_grabber()
        mon = self.sct.monitors[monitor if monitor < len(self.sct.monitors) else 1]
        self.region = region or Rect(mon["left"], mon["top"], mon["width"], mon["height"])

    def grab(self):
        from PIL import Image

        r = self.region
        shot = self.sct.grab({"left": r.left, "top": r.top, "width": r.width, "height": r.height})
        return Image.frombytes("RGB", shot.size, shot.rgb)


class ButtonWatch:
    """Fires once each time the action buttons appear."""

    def __init__(self, rect: Rect, baseline: list[int], threshold: float = 12.0):
        self.rect, self.baseline, self.threshold = rect, baseline, threshold
        self.active = False

    def look(self, table_image) -> float:
        r = self.rect
        return difference(thumb(table_image.crop(r.box())), self.baseline)

    def update(self, table_image) -> bool:
        """True when the buttons have just appeared."""
        now = self.look(table_image) > self.threshold
        fire = now and not self.active
        self.active = now
        return fire


class ChangeWatch:
    """Fires when the table changed and then held still, at most every ``min_gap`` seconds."""

    def __init__(self, min_gap: float = 4.0, moved: float = 3.0, still: float = 1.5):
        self.min_gap, self.moved, self.still = min_gap, moved, still
        self.last_read_thumb: list[int] | None = None
        self.prev: list[int] | None = None
        self.last_read_time = 0.0

    def update(self, table_image, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        t = thumb(table_image)
        settled = difference(t, self.prev) < self.still
        self.prev = t
        if not settled or now - self.last_read_time < self.min_gap:
            return False
        if difference(t, self.last_read_thumb) < self.moved:
            return False
        self.last_read_thumb, self.last_read_time = t, now
        return True
