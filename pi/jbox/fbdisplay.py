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
    def __init__(self, dev: str = "/dev/fb0"):
        self.width, self.height = (int(v) for v in (SYS / "virtual_size").read_text().split(","))
        self.bpp = int((SYS / "bits_per_pixel").read_text())
        self.stride = int((SYS / "stride").read_text())
        if self.bpp not in (16, 32):
            raise RuntimeError(f"unsupported framebuffer depth: {self.bpp}bpp")
        self._file = open(dev, "r+b", buffering=0)
        self._mm = mmap.mmap(self._file.fileno(), self.stride * self.height)
        self._row_px = self.stride // (self.bpp // 8)

    def blit(self, surface: pygame.Surface) -> None:
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
