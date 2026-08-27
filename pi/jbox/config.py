"""Load and validate config.yaml."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class Occasion:
    month: int
    day: int
    label: str

    def matches(self, d: date) -> bool:
        return d.month == self.month and d.day == self.day


@dataclass
class Config:
    base_url: str
    device_token: str
    poll_seconds: int = 60
    width: int = 800
    height: int = 480
    fullscreen: bool = True
    rotate: int = 90  # applied when the panel's native mode is portrait
    typewriter_delay: float = 0.045
    led_pin: int = 18
    reed_pin: int = 17
    lid_closed_when_circuit_closed: bool = True
    anniversary: date | None = None
    occasions: list[Occasion] = field(default_factory=list)

    def days_together(self, today: date) -> int | None:
        if not self.anniversary:
            return None
        return (today - self.anniversary).days + 1

    def occasion_today(self, today: date) -> Occasion | None:
        for occ in self.occasions:
            if occ.matches(today):
                return occ
        return None


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        sys.exit(f"Config not found: {path}\nCopy config.example.yaml to config.yaml and edit it.")

    raw = yaml.safe_load(path.read_text()) or {}
    api = raw.get("api", {})
    disp = raw.get("display", {})
    gpio = raw.get("gpio", {})
    dates = raw.get("dates", {}) or {}

    base_url = str(api.get("base_url", "")).rstrip("/")
    token = str(api.get("device_token", ""))
    if not base_url or token in ("", "CHANGE-ME"):
        sys.exit("config.yaml: api.base_url and api.device_token must be set.")

    anniversary = None
    if dates.get("anniversary"):
        anniversary = date.fromisoformat(str(dates["anniversary"]))

    occasions = []
    for item in dates.get("occasions") or []:
        month, day = (int(x) for x in str(item["date"]).split("-"))
        occasions.append(Occasion(month=month, day=day, label=str(item["label"])))

    return Config(
        base_url=base_url,
        device_token=token,
        poll_seconds=int(api.get("poll_seconds", 60)),
        width=int(disp.get("width", 800)),
        height=int(disp.get("height", 480)),
        fullscreen=bool(disp.get("fullscreen", True)),
        rotate=int(disp.get("rotate", 90)),
        typewriter_delay=float(disp.get("typewriter_delay", 0.045)),
        led_pin=int(gpio.get("led_pin", 18)),
        reed_pin=int(gpio.get("reed_pin", 17)),
        lid_closed_when_circuit_closed=bool(gpio.get("lid_closed_when_circuit_closed", True)),
        anniversary=anniversary,
        occasions=occasions,
    )
