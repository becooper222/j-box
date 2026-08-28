"""Read taps straight from the XPT2046/ADS7846 evdev device.

Used with the framebuffer display path, where SDL provides no input. A tap
is reported on finger release, using the last absolute position seen.
"""
from __future__ import annotations

import logging
import threading

from evdev import InputDevice, ecodes, list_devices

log = logging.getLogger("jbox.touch")


def find_touchscreen() -> str | None:
    for path in list_devices():
        try:
            if "ADS7846" in InputDevice(path).name:
                return path
        except OSError:
            continue
    return None


class EvdevTouch:
    """Calls on_tap((x, y)) in screen coordinates from a reader thread."""

    def __init__(self, width: int, height: int, on_tap,
                 swap_xy: bool = False, invert_x: bool = False, invert_y: bool = False):
        self.width, self.height = width, height
        self.on_tap = on_tap
        self.swap_xy, self.invert_x, self.invert_y = swap_xy, invert_x, invert_y
        path = find_touchscreen()
        if not path:
            log.warning("no ADS7846 touchscreen found - touch disabled")
            return
        self.dev = InputDevice(path)
        ax = self.dev.absinfo(ecodes.ABS_X)
        ay = self.dev.absinfo(ecodes.ABS_Y)
        self._xmin, self._xmax = ax.min, ax.max
        self._ymin, self._ymax = ay.min, ay.max
        log.info("touch on %s (x %s..%s, y %s..%s)", path, ax.min, ax.max, ay.min, ay.max)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        raw_x = raw_y = None
        touching = False
        for ev in self.dev.read_loop():
            if ev.type == ecodes.EV_ABS:
                if ev.code == ecodes.ABS_X:
                    raw_x = ev.value
                elif ev.code == ecodes.ABS_Y:
                    raw_y = ev.value
            elif ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_TOUCH:
                if ev.value == 1:
                    touching = True
                elif touching:
                    touching = False
                    if raw_x is not None and raw_y is not None:
                        self.on_tap(self._map(raw_x, raw_y))

    def _map(self, rx: int, ry: int) -> tuple[int, int]:
        nx = min(max((rx - self._xmin) / (self._xmax - self._xmin), 0.0), 1.0)
        ny = min(max((ry - self._ymin) / (self._ymax - self._ymin), 0.0), 1.0)
        if self.swap_xy:
            nx, ny = ny, nx
        if self.invert_x:
            nx = 1.0 - nx
        if self.invert_y:
            ny = 1.0 - ny
        return int(nx * (self.width - 1)), int(ny * (self.height - 1))
