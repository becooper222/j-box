"""Direct /dev/fb0 output.

SDL's kmsdrm backend renders invisibly on some HDMI LCD kits (this box's
Waveshare 4" included), while the kernel framebuffer console displays fine.
So we draw with pygame into an offscreen Surface and copy pixels straight
into the framebuffer ourselves.
"""
from __future__ import annotations

import mmap
from pathlib import Path

import numpy as np
import pygame

SYS = Path("/sys/class/graphics/fb0")


class FbDisplay:
    """rotate: degrees counter-clockwise applied to the canvas before it is
    packed into the panel's framebuffer. The Waveshare 4" is a portrait
    480x800 panel, so a landscape UI needs 90 or -90."""

    def __init__(self, dev: str = "/dev/fb0", rotate: int = 0):
        self.width, self.height = (int(v) for v in (SYS / "virtual_size").read_text().split(","))
        self.bpp = int((SYS / "bits_per_pixel").read_text())
        self.stride = int((SYS / "stride").read_text())
        if self.bpp not in (16, 32):
            raise RuntimeError(f"unsupported framebuffer depth: {self.bpp}bpp")
        self.rotate = rotate
        if rotate in (90, -90, 270, -270):
            self.canvas_w, self.canvas_h = self.height, self.width
        else:
            self.canvas_w, self.canvas_h = self.width, self.height
        self._file = open(dev, "r+b", buffering=0)
        self._mm = mmap.mmap(self._file.fileno(), self.stride * self.height)
        self._row_px = self.stride // (self.bpp // 8)

    def panel_to_canvas(self, px: int, py: int) -> tuple[int, int]:
        """Inverse of the render rotation, for mapping touches back."""
        if self.rotate in (90, -270):
            return self.canvas_w - 1 - py, px
        if self.rotate in (-90, 270):
            return py, self.canvas_h - 1 - px
        if self.rotate in (180, -180):
            return self.canvas_w - 1 - px, self.canvas_h - 1 - py
        return px, py

    def blit(self, surface: pygame.Surface) -> None:
        if self.rotate:
            surface = pygame.transform.rotate(surface, self.rotate)
        if surface.get_size() != (self.width, self.height):
            raise ValueError(
                f"surface {surface.get_size()} does not match framebuffer "
                f"{(self.width, self.height)} after rotate={self.rotate}"
            )
        # pixels3d is (w, h, 3); frame becomes (h, w, 3)
        px = pygame.surfarray.pixels3d(surface)
        frame = np.transpose(px, (1, 0, 2))
        if self.bpp == 16:  # RGB565
            out = (
                (frame[:, :, 0].astype(np.uint16) >> 3 << 11)
                | (frame[:, :, 1].astype(np.uint16) >> 2 << 5)
                | (frame[:, :, 2].astype(np.uint16) >> 3)
            )
        else:  # XRGB8888 little-endian
            out = np.zeros((self.height, self._row_px, 4), dtype=np.uint8)
            out[:, : self.width, 0] = frame[:, :, 2]
            out[:, : self.width, 1] = frame[:, :, 1]
            out[:, : self.width, 2] = frame[:, :, 0]
        del px, frame  # release the surface lock before writing
        if self.bpp == 16 and self._row_px != self.width:
            padded = np.zeros((self.height, self._row_px), dtype=np.uint16)
            padded[:, : self.width] = out
            out = padded
        self._mm.seek(0)
        self._mm.write(out.tobytes())

    def close(self) -> None:
        self._mm.close()
        self._file.close()
