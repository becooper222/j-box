"""J-Box UI: a small state machine drawn with pygame.

States:
  IDLE     screen dark (box closed); LED pulses if a note is unread
  REVEAL   lid opened on an unread note -> typewriter reveal
  READING  a note on screen with heart + archive controls
  ARCHIVE  browsable list of every note ever sent

Dev mode (no GPIO): 'o' opens the lid, 'c' closes it, Esc quits.
"""
from __future__ import annotations

import logging
import math
import os
import queue
import threading
import time
from datetime import date

import pygame

from .api import JBoxAPI, Message
from .config import Config
from .hardware import Led, Lid, ScreenPower

log = logging.getLogger("jbox.app")

# Palette: a dark, warm interior - like the inside of a jewelry box
BG = (20, 9, 13)
CREAM = (245, 233, 220)
ROSE = (224, 82, 111)
GOLD = (217, 164, 65)
DIM = (138, 122, 114)

FPS = 30
PER_PAGE = 4  # archive rows per page


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
            self.fb = FbDisplay()
            self.surface = pygame.Surface((self.fb.width, self.fb.height))
            self.cfg.width, self.cfg.height = self.fb.width, self.fb.height
            self.touch = EvdevTouch(
                self.fb.width, self.fb.height,
                on_tap=lambda pos: self.events.put(("tap", pos)),
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
        self.archive_page = 0
        self.buttons: dict[str, pygame.Rect] = {}

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

        label = self.font_small.render("archive", True, DIM)
        pos = (self.cfg.width // 2 - label.get_width() // 2, self.cfg.height - 40)
        self.surface.blit(label, pos)
        self.buttons["archive"] = pygame.Rect(pos[0] - 20, pos[1] - 12, label.get_width() + 40, 50)

        # floating hearts after she taps the heart
        if time.monotonic() < self.heart_anim_until:
            t = self.heart_anim_until - time.monotonic()
            for i in range(6):
                phase = (1.5 - t) + i * 0.4
                hx = self.cfg.width - 90 + int(30 * math.sin(phase * 3 + i))
                hy = self.cfg.height - 60 - int(phase * 130)
                if hy > 40:
                    self._draw_heart((hx, hy), 20 + (i % 3) * 8, ROSE)

    def _draw_archive(self) -> None:
        self.surface.fill(BG)
        self.buttons.clear()
        title = self.font_head.render("Every note", True, ROSE)
        self.surface.blit(title, (self.cfg.width // 2 - title.get_width() // 2, 18))

        msgs = self.api.snapshot()
        start = self.archive_page * PER_PAGE
        y = 70
        for idx, m in enumerate(msgs[start:start + PER_PAGE]):
            row = pygame.Rect(30, y, self.cfg.width - 60, 78)
            pygame.draw.rect(self.surface, (36, 20, 26), row, border_radius=12)
            snippet = m.body.replace("\n", " ")
            snippet = snippet[:44] + ("…" if len(snippet) > 44 else "")
            self.surface.blit(self.font_small.render(m.created_date_text(), True, DIM), (48, y + 10))
            self.surface.blit(self.font_small.render(snippet, True, CREAM), (48, y + 40))
            if m.hearted_at:
                self._draw_heart((row.right - 36, y + 39), 22, ROSE)
            self.buttons[f"open:{m.id}"] = row
            y += 90

        if start > 0:
            up = self.font_head.render("▲", True, DIM)
            self.surface.blit(up, (self.cfg.width - 60, 70))
            self.buttons["prev"] = pygame.Rect(self.cfg.width - 90, 50, 80, 80)
        if start + PER_PAGE < len(msgs):
            down = self.font_head.render("▼", True, DIM)
            self.surface.blit(down, (self.cfg.width - 60, self.cfg.height - 90))
            self.buttons["next"] = pygame.Rect(self.cfg.width - 90, self.cfg.height - 110, 80, 80)

        back = self.font_small.render("back", True, DIM)
        pos = (self.cfg.width // 2 - back.get_width() // 2, self.cfg.height - 40)
        self.surface.blit(back, pos)
        self.buttons["back"] = pygame.Rect(pos[0] - 20, pos[1] - 12, back.get_width() + 40, 50)

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
                self.archive_page = 0
                self.state = "ARCHIVE"
            elif name == "back":
                self.state = "READING"
            elif name == "prev":
                self.archive_page -= 1
            elif name == "next":
                self.archive_page += 1
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
            clock.tick(FPS)

        self.led.off()
        self.screen_power.on()
        pygame.quit()
