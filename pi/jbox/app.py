"""J-Box UI: a small state machine drawn with pygame.

States:
  IDLE      screen dark (lid closed); LED pulses if a note is unread
  GREETING  a time-aware hello, held briefly before the note
  REVEAL    the note types itself out
  READING   the note, with its date and heart status; long notes scroll
  ARCHIVE   her hearted favorites, one at a time

Input is one momentary button: a tap sends the heart (or advances when
more unread notes are waiting), a hold browses favorites. Before it is
soldered, `kill -USR1 <pid>` fakes a tap and `-USR2` a hold. Dev mode
(no GPIO): 'o'/'c' work the lid, 'h'/'a' the button, Esc quits.
"""
from __future__ import annotations

import logging
import os
import queue
import signal
import threading
import time
from datetime import date, datetime
from pathlib import Path

import pygame

from .api import JBoxAPI, Message
from .config import Config
from .hardware import Led, Lid, PushButton, ScreenPower

log = logging.getLogger("jbox.app")

# Palette: a dark, warm interior - like the inside of a jewelry box
BG = (20, 9, 13)
CREAM = (245, 233, 220)
ROSE = (224, 82, 111)
GOLD = (217, 164, 65)
DIM = (138, 122, 114)

FPS = 30
IDLE_FPS = 8  # nothing is animating; this box runs 24/7 on a Zero 2

SCROLL_PAUSE = 3.0     # seconds to read the top before a long note moves
HINT_FADE_AFTER = 8.0  # the nudge retires once she has had a chance to see it
SENT_LABEL_FOR = 4.0   # how long "sent" lingers next to the filled heart


class JBoxApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api = JBoxAPI(cfg.base_url, cfg.device_token)
        self.events: queue.Queue = queue.Queue()

        self.led = Led(cfg.led_pin)
        self.screen_power = ScreenPower(blank_hdmi=cfg.blank_hdmi)
        self.lid = Lid(
            cfg.reed_pin,
            cfg.lid_closed_when_circuit_closed,
            on_open=lambda: self.events.put("lid_open"),
            on_close=lambda: self.events.put("lid_close"),
        )
        self.button = PushButton(
            cfg.button_pin,
            cfg.button_hold_time,
            on_short=lambda: self.events.put("btn_short"),
            on_long=lambda: self.events.put("btn_long"),
        )

        self.fb = None
        self.touch = None
        self.rotate = 0
        if cfg.driver == "fb":
            # draw offscreen and copy pixels straight to /dev/fb0 (SDL's
            # kmsdrm output never reaches this panel)
            from .fbdisplay import FbDisplay
            from .touch import EvdevTouch
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            pygame.init()
            self.display = None
            self.fb = FbDisplay(rotate=cfg.rotate)
            self.surface = pygame.Surface((self.fb.canvas_w, self.fb.canvas_h))
            self.cfg.width, self.cfg.height = self.fb.canvas_w, self.fb.canvas_h
            log.info("panel %dx%d, canvas %dx%d, rotate=%d",
                     self.fb.width, self.fb.height, self.fb.canvas_w, self.fb.canvas_h, cfg.rotate)
            self.touch = EvdevTouch(
                self.fb.width, self.fb.height,
                on_tap=lambda pos: self.events.put(("tap", self.fb.panel_to_canvas(*pos))),
                swap_xy=cfg.touch_swap_xy,
                invert_x=cfg.touch_invert_x,
                invert_y=cfg.touch_invert_y,
            )
        else:
            pygame.init()
            if cfg.fullscreen:
                self.display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.display = pygame.display.set_mode((cfg.width, cfg.height))
            dw, dh = self.display.get_size()
            if (dw, dh) != (cfg.width, cfg.height):
                self.rotate = cfg.rotate
            self.surface = pygame.Surface((cfg.width, cfg.height))
            pygame.display.set_caption("J-Box")
            pygame.mouse.set_visible(False)

        self._load_fonts(cfg.font)

        self.state = "IDLE"
        self.current: Message | None = None
        self.greeting_started = 0.0
        self.reveal_started = 0.0
        self.reading_started = 0.0
        self.heart_sent_at = 0.0
        self.opened_with_unread = False
        self.archive_index = 0

        # before the button is soldered: kill -USR1 <pid> = tap, -USR2 = hold
        signal.signal(signal.SIGUSR1, lambda *_: self.events.put("btn_short"))
        signal.signal(signal.SIGUSR2, lambda *_: self.events.put("btn_long"))

        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ------------------------------------------------------------- setup

    def _load_fonts(self, font_setting: str) -> None:
        """Handwriting face, with a legible fallback if the file is missing."""
        path = Path(font_setting)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        if path.exists():
            # Caveat has a small x-height, so these run larger than a sans would
            self.font_greet = pygame.font.Font(str(path), 76)
            self.font_note = pygame.font.Font(str(path), 52)
            self.font_head = pygame.font.Font(str(path), 34)
            self.font_small = pygame.font.Font(str(path), 30)
            log.info("handwriting font: %s", path.name)
        else:
            log.warning("font %s not found - falling back to DejaVu", path)
            self.font_greet = pygame.font.SysFont("dejavusans", 52)
            self.font_note = pygame.font.SysFont("dejavusans", 38)
            self.font_head = pygame.font.SysFont("dejavusans", 24)
            self.font_small = pygame.font.SysFont("dejavusans", 22)

    # ------------------------------------------------------------- polling

    def _poll_loop(self) -> None:
        while True:
            self.api.poll()
            time.sleep(self.cfg.poll_seconds)

    # ------------------------------------------------------------- helpers

    def _wrap(self, text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            words = paragraph.split(" ")
            line = ""
            for word in words:
                trial = f"{line} {word}".strip()
                if font.size(trial)[0] <= max_width:
                    line = trial
                else:
                    if line:
                        lines.append(line)
                    line = word
            lines.append(line)
        return lines

    def _draw_heart(self, center: tuple[int, int], size: int, color, filled: bool = True) -> None:
        x, y = center
        r = max(3, size // 4)

        def shape(scale: float, col):
            rr = max(1, int(r * scale))
            pts = [(x - 2 * rr, y - rr // 2), (x + 2 * rr, y - rr // 2), (x, y + int(1.6 * rr))]
            pygame.draw.polygon(self.surface, col, pts)
            pygame.draw.circle(self.surface, col, (x - rr, y - rr // 2), rr)
            pygame.draw.circle(self.surface, col, (x + rr, y - rr // 2), rr)

        shape(1.0, color)
        if not filled:
            shape(0.72, BG)  # hollow it out to leave an outline

    def _greeting_text(self) -> tuple[str, tuple[int, int, int]]:
        """Occasions take precedence; otherwise greet by time of day."""
        occ = self.cfg.occasion_today(date.today())
        if occ:
            return occ.label, GOLD
        hour = datetime.now().hour
        if 5 <= hour < 12:
            part = "Good morning"
        elif 12 <= hour < 17:
            part = "Good afternoon"
        elif 17 <= hour < 21:
            part = "Good evening"
        else:
            part = "Good night"
        return f"{part}, Julia", ROSE

    def _unread_oldest_first(self) -> list[Message]:
        return list(reversed(self.api.unread()))  # the api hands back newest first

    def _favorites(self) -> list[Message]:
        return [m for m in self.api.snapshot() if m.hearted_at]

    def _note_area(self) -> tuple[int, int, int]:
        """Left margin, first baseline, and usable height for note text."""
        return 48, 74, self.cfg.height - 74 - 58

    def _draw_note_block(self, lines: list[str], color, offset: int = 0,
                         reveal_chars: int | None = None) -> tuple[int, int] | None:
        """Draw a note centered on the panel; returns the caret position.

        Lines are centered on their *full* width even while typing, so the
        text does not shuffle sideways as characters land. A block short
        enough to fit is also centered vertically; a taller one starts at
        the top and is scrolled by the caller via `offset`.
        """
        font = self.font_note
        _, top, avail_h = self._note_area()
        line_h = font.get_linesize()
        total_h = len(lines) * line_h

        y = top + max(0, (avail_h - total_h) // 2) - offset
        shown = 0
        caret = None

        self.surface.set_clip(pygame.Rect(0, top, self.cfg.width, avail_h))
        for line in lines:
            x = (self.cfg.width - font.size(line)[0]) // 2
            if reveal_chars is None:
                text = line
            else:
                take = max(0, min(len(line), reveal_chars - shown))
                text = line[:take]
                shown += len(line)
            if text and -line_h < y - top < avail_h + line_h:
                img = font.render(text, True, color)
                self.surface.blit(img, (x, y))
                if reveal_chars is not None and len(text) < len(line):
                    caret = (x + img.get_width() + 4, y)
            elif text and reveal_chars is not None and len(text) < len(line):
                caret = (x + 4, y)
            y += line_h
        self.surface.set_clip(None)
        return caret

    # ------------------------------------------------------------- states

    def _enter_idle(self) -> None:
        self.state = "IDLE"
        self.current = None
        self.screen_power.off()
        if self.api.unread():
            self.led.pulse()
        else:
            self.led.off()

    def _open_lid(self) -> None:
        self.screen_power.on()
        unread = self._unread_oldest_first()
        self.opened_with_unread = bool(unread)
        if unread:
            self.current = unread[0]  # oldest first, so nothing is skipped
            self.state = "GREETING"
            self.greeting_started = time.monotonic()
        else:
            msgs = self.api.snapshot()
            self.current = msgs[0] if msgs else None
            self._enter_reading()

    def _start_reveal(self) -> None:
        self.state = "REVEAL"
        self.reveal_started = time.monotonic()

    def _enter_reading(self) -> None:
        self.state = "READING"
        self.reading_started = time.monotonic()

    def _finish_reveal(self) -> None:
        if self.current:
            self.api.mark_read(self.current.id)
        if not self.api.unread():
            self.led.off()
        self._enter_reading()

    def _next_unread(self) -> None:
        """More notes were waiting; reveal the next without another greeting."""
        remaining = self._unread_oldest_first()
        if remaining:
            self.current = remaining[0]
            self._start_reveal()

    # ------------------------------------------------------------- drawing

    def _draw_idle(self) -> None:
        self.surface.fill((0, 0, 0))

    def _draw_greeting(self) -> None:
        self.surface.fill(BG)
        text, color = self._greeting_text()
        img = self.font_greet.render(text, True, color)
        self.surface.blit(img, (self.cfg.width // 2 - img.get_width() // 2,
                                self.cfg.height // 2 - img.get_height() // 2))
        self._draw_heart((self.cfg.width // 2, self.cfg.height // 2 + img.get_height()), 34, ROSE)

        if time.monotonic() - self.greeting_started >= self.cfg.greeting_seconds:
            self._start_reveal()

    def _draw_reveal(self) -> None:
        self.surface.fill(BG)
        if not self.current:
            self._enter_reading()
            return
        left, _, _ = self._note_area()
        lines = self._wrap(self.current.body, self.font_note, self.cfg.width - 2 * left)
        elapsed = time.monotonic() - self.reveal_started
        visible = int(elapsed / self.cfg.typewriter_delay)
        total = sum(len(l) for l in lines)

        caret = self._draw_note_block(lines, CREAM, reveal_chars=visible)
        if caret and int(elapsed * 2) % 2 == 0:
            pygame.draw.rect(self.surface, ROSE, (caret[0], caret[1] + 8, 3, 30))

        if visible >= total + 8:  # a beat after the last character lands
            self._finish_reveal()

    def _draw_reading(self) -> None:
        self.surface.fill(BG)
        left, _, avail_h = self._note_area()

        if not self.current:
            msg = self.font_note.render("No notes yet", True, DIM)
            self.surface.blit(msg, (self.cfg.width // 2 - msg.get_width() // 2,
                                    self.cfg.height // 2 - msg.get_height() // 2))
            return

        # the day counter greets her only when nothing new was waiting
        if not self.opened_with_unread:
            days = self.cfg.days_together(date.today())
            if days:
                head = self.font_head.render(f"Day {days:,} of us", True, ROSE)
                self.surface.blit(head, (self.cfg.width // 2 - head.get_width() // 2, 24))

        lines = self._wrap(self.current.body, self.font_note, self.cfg.width - 2 * left)
        total_h = len(lines) * self.font_note.get_linesize()

        # a long note drifts upward on its own after a beat to read the top
        offset = 0
        if total_h > avail_h:
            moving = time.monotonic() - self.reading_started - SCROLL_PAUSE
            offset = int(max(0.0, min(moving * self.cfg.scroll_speed, total_h - avail_h)))

        self._draw_note_block(lines, CREAM, offset=offset)

        stamp = self.font_small.render(self.current.created_date_text(), True, DIM)
        self.surface.blit(stamp, (left, self.cfg.height - 44))

        hearted = self.current.hearted_at is not None
        self._draw_heart((self.cfg.width - 62, self.cfg.height - 34), 40,
                         ROSE if hearted else DIM, filled=hearted)
        if hearted and time.monotonic() - self.heart_sent_at < SENT_LABEL_FOR:
            sent = self.font_small.render("sent", True, ROSE)
            self.surface.blit(sent, (self.cfg.width - 106 - sent.get_width(),
                                     self.cfg.height - 48))

        self._draw_hint()

    def _draw_hint(self) -> None:
        """The button means different things; say which, then get out of the way."""
        waiting = len(self.api.unread())
        if waiting:
            text = f"{waiting} more new  ·  press for the next"
        elif self.current and not self.current.hearted_at:
            if time.monotonic() - self.reading_started > HINT_FADE_AFTER:
                return
            text = "press to send love  ·  hold for favorites"
        else:
            return
        label = self.font_small.render(text, True, DIM)
        self.surface.blit(label, (self.cfg.width // 2 - label.get_width() // 2,
                                  self.cfg.height - 44))

    def _draw_archive(self) -> None:
        """Her hearted notes, one at a time - a memory jar, not a list."""
        self.surface.fill(BG)
        favs = self._favorites()
        if not favs:
            a = self.font_note.render("No favorites yet", True, DIM)
            b = self.font_small.render("press the heart on a note you love", True, DIM)
            self.surface.blit(a, (self.cfg.width // 2 - a.get_width() // 2, 160))
            self.surface.blit(b, (self.cfg.width // 2 - b.get_width() // 2, 240))
            hint = self.font_small.render("hold to come back", True, DIM)
            self.surface.blit(hint, (self.cfg.width // 2 - hint.get_width() // 2,
                                     self.cfg.height - 44))
            return

        idx = self.archive_index % len(favs)
        m = favs[idx]
        head = self.font_head.render(
            f"{m.created_date_text()}   ·   {idx + 1} of {len(favs)}", True, GOLD)
        self.surface.blit(head, (self.cfg.width // 2 - head.get_width() // 2, 24))

        left, _, _ = self._note_area()
        self._draw_note_block(
            self._wrap(m.body, self.font_note, self.cfg.width - 2 * left), CREAM)

        self._draw_heart((self.cfg.width - 62, self.cfg.height - 34), 40, ROSE)
        hint = self.font_small.render("press for the one before  ·  hold to come back", True, DIM)
        self.surface.blit(hint, (self.cfg.width // 2 - hint.get_width() // 2, self.cfg.height - 44))

    # ------------------------------------------------------------- input

    def _button_short(self) -> None:
        log.info("button tap (state=%s)", self.state)
        if self.state == "IDLE":
            self._open_lid()
        elif self.state == "GREETING":
            self._start_reveal()
        elif self.state == "REVEAL":
            self.reveal_started = -1e9  # skip to the end of the typewriter
        elif self.state == "READING":
            if self.api.unread():
                self._next_unread()
            elif self.current and not self.current.hearted_at:
                self.api.mark_hearted(self.current.id)
                self.heart_sent_at = time.monotonic()
                self.led.heart_flash()
        elif self.state == "ARCHIVE":
            self.archive_index += 1

    def _button_long(self) -> None:
        log.info("button hold (state=%s)", self.state)
        if self.state == "ARCHIVE":
            msgs = self.api.snapshot()
            self.current = msgs[0] if msgs else None
            self.opened_with_unread = False
            self._enter_reading()
        elif self.state in ("READING", "REVEAL", "GREETING"):
            self.archive_index = 0
            self.state = "ARCHIVE"

    # ------------------------------------------------------------- main

    def _animating(self) -> bool:
        if self.state in ("GREETING", "REVEAL"):
            return True
        if self.state == "READING" and self.current:
            since = time.monotonic() - self.reading_started
            if since < SCROLL_PAUSE + 40:  # a scroll may still be in progress
                return True
            if time.monotonic() - self.heart_sent_at < SENT_LABEL_FOR:
                return True
        return False

    def run(self) -> None:
        clock = pygame.time.Clock()
        if self.cfg.always_open or os.environ.get("JBOX_START_OPEN"):
            self.screen_power.on()
            self._open_lid()
        else:
            self._enter_idle()

        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        running = False
                    elif ev.key == pygame.K_o:
                        self.events.put("lid_open")
                    elif ev.key == pygame.K_c:
                        self.events.put("lid_close")
                    elif ev.key == pygame.K_h:
                        self.events.put("btn_short")
                    elif ev.key == pygame.K_a:
                        self.events.put("btn_long")

            try:
                while True:
                    hw = self.events.get_nowait()
                    if hw == "lid_open" and self.state == "IDLE":
                        self._open_lid()
                    elif hw == "lid_close" and not self.cfg.always_open:
                        self._enter_idle()
                    elif hw == "btn_short":
                        self._button_short()
                    elif hw == "btn_long":
                        self._button_long()
                    elif isinstance(hw, tuple) and hw[0] == "tap":
                        self._button_short()
            except queue.Empty:
                pass

            if self.state == "IDLE":
                if self.api.unread():
                    self.led.pulse()
                self._draw_idle()
            elif self.state == "GREETING":
                self._draw_greeting()
            elif self.state == "REVEAL":
                self._draw_reveal()
            elif self.state == "READING":
                self._draw_reading()
                # dev mode has no lid to reopen, so surface arrivals right away
                if self.cfg.always_open and self.api.unread():
                    self._next_unread()
            elif self.state == "ARCHIVE":
                self._draw_archive()

            if self.fb:
                self.fb.blit(self.surface)
            else:
                if self.rotate:
                    self.display.blit(pygame.transform.rotate(self.surface, self.rotate), (0, 0))
                else:
                    self.display.blit(self.surface, (0, 0))
                pygame.display.flip()

            clock.tick(FPS if self._animating() else IDLE_FPS)

        self.led.off()
        self.screen_power.on()
        pygame.quit()
