"""LED and lid (reed switch) control.

Falls back to console mocks when gpiozero isn't available, so the whole app
can be developed and demoed on a laptop.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("jbox.hw")

try:
    from gpiozero import PWMLED, Button
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False
    log.warning("gpiozero not available - using mock hardware")


class Led:
    """Warm status LED. pulse() breathes gently until off()/fade_out()."""

    def __init__(self, pin: int):
        self._led = PWMLED(pin) if HAS_GPIO else None
        self._pulsing = False

    def pulse(self) -> None:
        if self._pulsing:
            return
        self._pulsing = True
        if self._led:
            # 2s up, 2s down: a slow breath, not a nag
            self._led.pulse(fade_in_time=2.0, fade_out_time=2.0)
        else:
            log.info("[mock LED] pulsing")

    def off(self) -> None:
        self._pulsing = False
        if self._led:
            self._led.off()
        else:
            log.info("[mock LED] off")


class Lid:
    """Reed-switch lid sensor.

    Wiring: one leg of the reed switch to the configured GPIO, the other to
    GND. Internal pull-up is used. With the magnet mounted in the lid above
    the switch, the circuit is closed while the lid is closed.
    """

    def __init__(self, pin: int, closed_when_circuit_closed: bool, on_open, on_close):
        self._invert = not closed_when_circuit_closed
        self._on_open = on_open
        self._on_close = on_close
        if HAS_GPIO:
            # bounce_time absorbs magnet wobble as the lid moves
            self._btn = Button(pin, pull_up=True, bounce_time=0.1)
            self._btn.when_pressed = self._circuit_closed
            self._btn.when_released = self._circuit_opened
        else:
            self._btn = None
            log.info("[mock lid] press 'o' to open the lid, 'c' to close it")

    @property
    def is_open(self) -> bool:
        if not self._btn:
            return True  # mock: treated as open, keyboard drives transitions
        closed = self._btn.is_pressed
        if self._invert:
            closed = not closed
        return not closed

    def _circuit_closed(self) -> None:
        (self._on_open if self._invert else self._on_close)()

    def _circuit_opened(self) -> None:
        (self._on_close if self._invert else self._on_open)()


class ScreenPower:
    """Best-effort display blanking.

    Inside a closed box a black frame is effectively "off"; when available we
    additionally cut the HDMI signal. The app always renders black while
    idle, so failures here are harmless.
    """

    def __init__(self):
        self._is_on = True

    def on(self) -> None:
        if not self._is_on:
            self._vcgencmd("1")
            self._is_on = True

    def off(self) -> None:
        if self._is_on:
            self._vcgencmd("0")
            self._is_on = False

    @staticmethod
    def _vcgencmd(state: str) -> None:
        try:
            subprocess.run(
                ["vcgencmd", "display_power", state],
                check=False, capture_output=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
