"""Live chart: draw a scrolling line chart into a LiveBitmap from a background thread.

What it teaches
  * ``Document.create_bitmap`` + ``<img src="ui4me-bitmap://ID">`` for pixels you render yourself
  * the frame format: straight-alpha RGBA8, row-major, ``width * 4`` bytes per row
  * ``try_present`` from a producer thread (skips a frame instead of queueing when busy)
  * cheap rendering with pure Python: copy a pre-drawn background, then paint only the line
  * stopping the producer on shutdown; the bitmap is released with its document

Run:  python examples/live_chart.py
"""
from __future__ import annotations

import collections
import math
import random
import threading
import time

from nativehtmlkit import Application, NativeHTMLKitError, Window

WIDTH, HEIGHT = 480, 200
BACKGROUND = (16, 22, 34, 255)
GRID = (40, 52, 72, 255)
LINE = (94, 196, 255, 255)

PAGE = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  body {{ margin:0; padding:20px; background:#0b1018; color:#dbe3f0; font:14px sans-serif; }}
  h1 {{ font-size:18px; margin:0 0 12px; }}
  img {{ display:block; border:1px solid #2a3850; border-radius:6px; }}
  .bar {{ display:flex; gap:10px; align-items:center; margin-top:12px; }}
  button {{ padding:6px 14px; border:1px solid #3a4c6a; border-radius:5px; background:#1a2436; color:#dbe3f0; }}
  .stats {{ color:#8b98ad; font-family:monospace; }}
</style></head>
<body>
  <h1>Signal monitor</h1>
  <img id="chart" src="ui4me-bitmap://chart" width="{WIDTH}" height="{HEIGHT}" alt="Live line chart">
  <div class="bar">
    <button id="start">Start</button><button id="stop">Stop</button>
    <span class="stats">value <b id="value">-</b> · frames <b id="frames">0</b> · skipped <b id="skipped">0</b></span>
  </div>
</body></html>"""


def draw_background() -> bytes:
    row = bytes(BACKGROUND) * WIDTH
    grid_row = bytes(GRID) * WIDTH
    frame = bytearray(row * HEIGHT)
    for y in range(0, HEIGHT, 40):                     # horizontal grid lines
        frame[y * WIDTH * 4:(y + 1) * WIDTH * 4] = grid_row
    for x in range(0, WIDTH, 60):                      # vertical grid lines
        for y in range(HEIGHT):
            i = (y * WIDTH + x) * 4
            frame[i:i + 4] = bytes(GRID)
    return bytes(frame)


def render(samples: list[float], background: bytes) -> bytearray:
    """Samples in [0, 1], newest last; one sample per pixel column."""
    frame = bytearray(background)
    pixel = bytes(LINE)
    previous = None
    start = WIDTH - len(samples)
    for column, value in enumerate(samples, start):
        y = HEIGHT - 1 - int(max(0.0, min(1.0, value)) * (HEIGHT - 1))
        low, high = (y, y) if previous is None else (min(y, previous), max(y, previous))
        for row in range(low, high + 1):                # connect to the previous point
            i = (row * WIDTH + column) * 4
            frame[i:i + 4] = pixel
        previous = y
    return frame


class LiveChart:
    def __init__(self, window: Window):
        self.document = window.document
        self.bitmap = self.document.create_bitmap("chart", WIDTH, HEIGHT)
        self.background = draw_background()
        self.samples: collections.deque[float] = collections.deque(maxlen=WIDTH)
        self.frames = self.skipped = 0
        self.running = threading.Event()
        self.stopped = threading.Event()
        self.document.on("click", lambda _e: self.start(), element="start")
        self.document.on("click", lambda _e: self.running.clear(), element="stop")
        self.bitmap.present(self.background)              # first frame: an empty chart

    def next_sample(self, t: float) -> float:
        return 0.5 + 0.3 * math.sin(t * 1.7) + 0.12 * math.sin(t * 7.3) + random.uniform(-0.04, 0.04)

    def draw_frame(self) -> bool:
        """Render and offer one frame; False when it was skipped because a present was busy."""
        result = self.bitmap.try_present(render(list(self.samples), self.background))
        if result is None:
            self.skipped += 1
            return False
        self.frames += 1
        return True

    def start(self) -> None:
        if self.running.is_set():
            return
        self.running.set()
        threading.Thread(target=self._produce, name="chart-producer", daemon=True).start()

    def _produce(self, fps: float = 30.0) -> None:
        started = time.monotonic()
        while self.running.is_set() and not self.stopped.is_set():
            try:
                self.samples.append(self.next_sample(time.monotonic() - started))
                self.draw_frame()
                if self.frames % 10 == 0:                 # text updates are cheaper at a lower rate
                    self.document.batch([
                        {"op": "set_text", "element": "value", "text": f"{self.samples[-1]:.3f}"},
                        {"op": "set_text", "element": "frames", "text": str(self.frames)},
                        {"op": "set_text", "element": "skipped", "text": str(self.skipped)},
                    ])
            except (NativeHTMLKitError, RuntimeError):
                return       # window closed / shutting down (a closed bitmap raises RuntimeError)
            time.sleep(1 / fps)
        self.running.clear()


def build(app: Application) -> LiveChart:
    chart = LiveChart(app.open_html(PAGE, title="Live chart", width=540, height=340))
    app.on_shutdown(chart.stopped.set)
    return chart


def main() -> None:
    with Application.start(name="Live chart") as app:
        build(app).start()
        app.run()


if __name__ == "__main__":
    main()
