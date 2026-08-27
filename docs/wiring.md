# J-Box wiring

Only two things get soldered: the LED and the reed switch. The screen's
XPT2046 touch controller already claims the SPI pins, so stay off BCM
7, 8, 9, 10, 11 and 25.

## Pin map (BCM numbering)

| Part | GPIO (BCM) | Physical pin | Goes to |
|---|---|---|---|
| LED anode (long leg) | GPIO 18 | 12 | via 330 Ω resistor |
| LED cathode (short leg) | GND | 14 | ground |
| Reed switch leg 1 | GPIO 17 | 11 | either leg, no polarity |
| Reed switch leg 2 | GND | 9 | ground |

```
 Pi Zero 2 header (relevant corner)          LED
                                              ___
  pin 9  GND  o──────────── reed ────┐       |>| warm white 5mm
  pin 11 G17  o──────────── reed ────┘   ┌───┤
  pin 12 G18  o───[ 330Ω ]───────────────┘   │
  pin 14 GND  o──────────────────────────────┘
```

## Notes

- **LED**: GPIO 18 is hardware-PWM capable, which is what makes the pulse
  smooth. 330 Ω is safe; use 220 Ω if you want it brighter. Solder the
  resistor in line with the anode wire and cover it with heat-shrink.
- **Reed switch**: no polarity, no resistor needed — the code enables the
  Pi's internal pull-up. Glass reed switches crack easily: bend the legs
  with pliers holding the lead at the glass, never by pulling on the body.
- **Placement**: reed switch sits in the pocket inside the front wall of the
  printed case; the magnet sits in the lid pocket directly above it. Lid
  closed = magnet near = circuit closed. Test the pair's range before gluing
  (they should trigger through ~5 mm of plastic; check with a multimeter).
- **LED mount**: press-fits into the 5.4 mm hole in the front face. A drop of
  CA glue from inside if loose.
- If your reed switch turns out to be a normally-closed type (LED logic
  seems inverted), just flip `lid_closed_when_circuit_closed` in
  `config.yaml` — no resoldering.
