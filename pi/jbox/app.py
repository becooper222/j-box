"""J-Box UI: a small state machine drawn with pygame.

States:
  IDLE     screen dark (box closed); LED pulses if a note is unread
  REVEAL   lid opened on an unread note -> typewriter reveal
  READING  a note on screen; the button hearts it
  ARCHIVE  one older note at a time, walked back with the button

Input is one momentary button: a tap sends the heart, a hold browses the
archive. Before it is soldered, `kill -USR1 <pid>` fakes a tap and
`-USR2` a hold. Dev mode (no GPIO): 'o'/'c' work the lid, Esc quits.
"""
from __future__ import annotations

import logging
import math
import os
import queue
import signal
import threading
import time
from datetime import date

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


class JBoxApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api = JBoxAPI(cfg.base_url, cfg.device_token)
        self.events: queue.Queue[str] = queue.Queue()

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
            # draw offscreen, copy pixels straight to /dev/fb0, and take
            # taps from evdev (SDL's kmsdrm path is a no-show on this panel)
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
            # evdev reports in panel space; rotate it into canvas space
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
                self.rotate = cfg.rotate  # 90 = panel is portrait-native
            self.surface = pygame.Surface((cfg.width, cfg.height))
            pygame.display.set_caption("J-Box")
            pygame.mouse.set_visible(False)

        self.font_body = pygame.font.SysFont("dejavusans", 38)
        self.font_head = pygame.font.SysFont("dejavusans", 24)
        self.font_small = pygame.font.SysFont("dejavusans", 22)

        self.state = "IDLE"
        self.current: Message | None = None
        self.reveal_started = 0.0
        self.heart_anim_until = 0.0
        self.archive_index = 0
        self.buttons: dict[str, pygame.Rect] = {}

        # before the button is soldered: kill -USR1 <pid> = tap, -USR2 = hold
        signal.signal(signal.SIGUSR1, lambda *_: self.events.put("btn_short"))
        signal.signal(signal.SIGUSR2, lambda *_: self.events.put("btn_long"))

        threading.Thread(target=self._poll_loop, daemon=True).start()

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

    def _draw_heart(self, center: tuple[int, int], size: int, color, filled=True) -> pygame.Rect:
        x, y = center
        r = size // 4
        pts = [(x - 2 * r, y - r // 2), (x + 2 * r, y - r // 2), (x, y + int(1.6 * r))]
        pygame.draw.polygon(self.surface, color, pts)
        pygame.draw.circle(self.surface, color, (x - r, y - r // 2), r)
        pygame.draw.circle(self.surface, color, (x + r, y - r // 2), r)
        if not filled:
            inner = tuple(max(0, c - 0) for c in BG)
            pygame.draw.polygon(self.surface, inner, [(p[0], p[1]) for p in
                [(x - 2 * r + 6, y - r // 2), (x + 2 * r - 6, y - r // 2), (x, y + int(1.6 * r) - 8)]])
            pygame.draw.circle(self.surface, inner, (x - r, y - r // 2), r - 4)
            pygame.draw.circle(self.surface, inner, (x + r, y - r // 2), r - 4)
        return pygame.Rect(x - 2 * r - 10, y - 2 * r - 10, 4 * r + 20, 4 * r + 20)

    def _header_text(self) -> tuple[str, tuple[int, int, int]]:
        today = date.today()
        occ = self.cfg.occasion_today(today)
        if occ:
            return occ.label, GOLD
        days = self.cfg.days_together(today)
        if days:
            return f"Day {days:,} of us", ROSE
        return "For Julia", ROSE

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
        unread = self.api.unread()
        if unread:
            self.current = unread[-1]  # oldest unread first
            self.state = "REVEAL"
            self.reveal_started = time.monotonic()
        else:
            msgs = self.api.snapshot()
            self.current = msgs[0] if msgs else None
            self.state = "READING"

    def _finish_reveal(self) -> None:
        if self.current:
            self.api.mark_read(self.current.id)
        if not self.api.unread():
            self.led.off()
        self.state = "READING"

    # ------------------------------------------------------------- drawing

    def _draw_idle(self) -> None:
        self.surface.fill((0, 0, 0))

    def _draw_note_chrome(self) -> None:
        header, color = self._header_text()
        if self.current and self.current.occasion:
            color = GOLD
        head = self.font_head.render(header, True, color)
        self.surface.blit(head, (self.cfg.width // 2 - head.get_width() // 2, 18))

    def _draw_reveal(self) -> None:
        self.surface.fill(BG)
        self._draw_note_chrome()
        assert self.current
        lines = self._wrap(self.current.body, self.font_body, self.cfg.width - 90)
        elapsed = time.monotonic() - self.reveal_started
        visible = int(elapsed / self.cfg.typewriter_delay)
        total = sum(len(l) for l in lines)

        y = 80
        shown = 0
        for line in lines:
            take = max(0, min(len(line), visible - shown))
            if take:
                text = self.font_body.render(line[:take], True, CREAM)
                self.surface.blit(text, (45, y))
            shown += len(line)
            y += self.font_body.get_linesize() + 4

        # blinking caret while typing
        if visible < total and int(elapsed * 2) % 2 == 0:
            pygame.draw.rect(self.surface, ROSE, (45 + 4, y - 8, 3, 26))

        if visible >= total + 8:  # small pause after the last character
            self._finish_reveal()

    def _draw_reading(self) -> None:
        self.surface.fill(BG)
        self.buttons.clear()
        self._draw_note_chrome()

        if not self.current:
            empty = self.font_body.render("No notes yet ♥", True, DIM)
            self.surface.blit(empty, (self.cfg.width // 2 - empty.get_width() // 2, 200))
        else:
            lines = self._wrap(self.current.body, self.font_body, self.cfg.width - 90)
            y = 80
            for line in lines[:7]:
                self.surface.blit(self.font_body.render(line, True, CREAM), (45, y))
                y += self.font_body.get_linesize() + 4
            stamp = self.font_small.render(self.current.created_date_text(), True, DIM)
            self.surface.blit(stamp, (45, self.cfg.height - 44))

            hearted = self.current.hearted_at is not None
            rect = self._draw_heart(
                (self.cfg.width - 90, self.cfg.height - 60), 56,
                ROSE if hearted else DIM, filled=hearted,
            )
            self.buttons["heart"] = rect

        hint = "press to send love  ·  hold to look back"
        label = self.font_small.render(hint, True, DIM)
        self.surface.blit(label, (self.cfg.width // 2 - label.get_width() // 2, self.cfg.height - 38))

        # floating hearts after she presses the heart
        if time.monotonic() < self.heart_anim_until:
            t = self.heart_anim_until - time.monotonic()
            for i in range(6):
                phase = (1.5 - t) + i * 0.4
                hx = self.cfg.width - 90 + int(30 * math.sin(phase * 3 + i))
                hy = self.cfg.height - 60 - int(phase * 130)
                if hy > 40:
                    self._draw_heart((hx, hy), 20 + (i % 3) * 8, ROSE)

    def _draw_archive(self) -> None:
        """One older note at a time - a single button can't drive a list."""
        self.surface.fill(BG)
        msgs = self.api.snapshot()
        if not msgs:
            return

        idx = self.archive_index % len(msgs)
        m = msgs[idx]
        head = self.font_head.render(f"{m.created_date_text()}   ({idx + 1} of {len(msgs)})", True, GOLD)
        self.surface.blit(head, (self.cfg.width // 2 - head.get_width() // 2, 18))

        lines = self._wrap(m.body, self.font_body, self.cfg.width - 90)
        y = 80
        for line in lines[:7]:
            self.surface.blit(self.font_body.render(line, True, CREAM), (45, y))
            y += self.font_body.get_linesize() + 4

        if m.hearted_at:
            self._draw_heart((self.cfg.width - 70, self.cfg.height - 60), 44, ROSE)

        hint = "press for the one before  ·  hold to come back"
        label = self.font_small.render(hint, True, DIM)
        self.surface.blit(label, (self.cfg.width // 2 - label.get_width() // 2, self.cfg.height - 38))

    # ------------------------------------------------------------- input

    def _to_canvas(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Map a display-space tap back onto the landscape canvas."""
        dx, dy = pos
        w, h = self.cfg.width, self.cfg.height
        if self.rotate == 90:      # canvas rotated CCW onto the panel
            return w - 1 - dy, dx
        if self.rotate == -90:     # clockwise
            return dy, h - 1 - dx
        if self.rotate == 180:
            return w - 1 - dx, h - 1 - dy
        return dx, dy

    def _button_short(self) -> None:
        log.info("button tap (state=%s)", self.state)
        if self.state == "IDLE":
            self._open_lid()
        elif self.state == "REVEAL":
            self.reveal_started = -1e9  # skip to the end of the typewriter
        elif self.state == "READING":
            if self.current and not self.current.hearted_at:
                self.api.mark_hearted(self.current.id)
            self.heart_anim_until = time.monotonic() + 1.5
        elif self.state == "ARCHIVE":
            self.archive_index += 1

    def _button_long(self) -> None:
        log.info("button hold (state=%s)", self.state)
        if self.state == "ARCHIVE":
            self.state = "READING"
            msgs = self.api.snapshot()
            self.current = msgs[0] if msgs else None
        elif self.state in ("READING", "REVEAL"):
            self.archive_index = 0
            self.state = "ARCHIVE"

    def _tap(self, pos: tuple[int, int]) -> None:
        log.info("tap at %s (state=%s)", pos, self.state)
        if self.state == "IDLE":
            # tap-to-wake: harmless in normal use (lid closed = screen
            # unreachable) and lets the box work even if the reed fails
            self._open_lid()
            return
        if self.state == "REVEAL":
            # tapping skips to the end of the typewriter
            self.reveal_started = -1e9
            return
        for name, rect in self.buttons.items():
            if not rect.collidepoint(pos):
                continue
            if name == "heart" and self.current:
                if not self.current.hearted_at:
                    self.api.mark_hearted(self.current.id)
                self.heart_anim_until = time.monotonic() + 1.5
            elif name == "archive":
                self.archive_index = 0
                self.state = "ARCHIVE"
            elif name == "back":
                self.state = "READING"
            elif name == "next":
                self.archive_index += 1
            elif name.startswith("open:"):
                msg_id = name.split(":", 1)[1]
                for m in self.api.snapshot():
                    if m.id == msg_id:
                        self.current = m
                        self.state = "READING"
                        break
            return

    # ------------------------------------------------------------- main

    def run(self) -> None:
        clock = pygame.time.Clock()
        if self.cfg.always_open or os.environ.get("JBOX_START_OPEN"):
            # no lid sensor wired yet: come up awake and stay awake
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
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    self._tap(self._to_canvas(ev.pos))
                elif ev.type == pygame.FINGERDOWN:
                    # kmsdrm delivers touch as normalized finger events
                    dw, dh = self.display.get_size()
                    self._tap(self._to_canvas((int(ev.x * dw), int(ev.y * dh))))

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
                        self._tap(hw[1])
            except queue.Empty:
                pass

            # a note arriving while the box is closed starts the LED breathing
            if self.state == "IDLE":
                if self.api.unread():
                    self.led.pulse()
                self._draw_idle()
            elif self.state == "READING" and self.cfg.always_open and self.api.unread():
                # dev mode: nothing will ever re-open the lid, so reveal
                # anything that arrives while we sit here
                self._open_lid()
            elif self.state == "REVEAL":
                self._draw_reveal()
            elif self.state == "READING":
                self._draw_reading()
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
            animating = self.state == "REVEAL" or time.monotonic() < self.heart_anim_until
            clock.tick(FPS if animating else IDLE_FPS)

        self.led.off()
        self.screen_power.on()
        pygame.quit()
