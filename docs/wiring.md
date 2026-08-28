# J-Box wiring

Only two things get soldered: the LED and the reed switch.

## What the LCD already claims

The Waveshare 4inch HDMI LCD sends **video over HDMI but touch over the
GPIO header** — the XPT2046 is an SPI part, so the panel must sit on the
Pi's 40-pin header (it covers physical pins 1–26) or touch will never
work. Symptom of a missing connection: the `ads7846` interrupt in
`/proc/interrupts` stays at 0 no matter how much you tap.

Pins the LCD uses, all inside physical 1–26:

| Function | BCM |
|---|---|
| Touch SPI (MOSI/MISO/SCLK/CE1) | 10, 9, 11, 7 |
| Touch pen IRQ | 25 |
| **Backlight PWM** | **18** |

So our two parts live on physical pins **27–40**, which the LCD leaves free.

## Pin map (BCM numbering)

| Part | GPIO (BCM) | Physical pin | Goes to |
|---|---|---|---|
| LED anode (long leg) | GPIO 12 | 32 | via 330 Ω resistor |
| LED cathode (short leg) | GND | 34 | ground |
| Reed switch leg 1 | GPIO 26 | 37 | either leg, no polarity |
| Reed switch leg 2 | GND | 39 | ground |

```
 Pi header, bottom corner (pins 27-40)        LED
                                               ___
  pin 32 G12  o───[ 330Ω ]──────────────┐     |>| warm white 5mm
  pin 34 GND  o──────────────────────┐  └─────┤
                                     └────────┘
  pin 37 G26  o──────────── reed ────┐
  pin 39 GND  o──────────── reed ────┘
```

## Notes

- **LED**: GPIO 12 is hardware-PWM capable, which is what makes the pulse
  smooth. It is also clear of GPIO 18, which this LCD drives as its
  backlight — putting the LED there would have fought the panel. 330 Ω is
  safe; use 220 Ω for brighter. Solder the resistor in line with the anode
  and cover it with heat-shrink.
- **Reed switch**: no polarity, no resistor needed — the code enables the
  Pi's internal pull-up. Glass reed switches crack easily: bend the legs
  with pliers holding the lead at the glass, never by pulling on the body.
- **Placement**: reed switch sits in the pocket inside the front wall of the
  printed case; the magnet sits in the lid pocket directly above it. Lid
  closed = magnet near = circuit closed. Test the pair's range before gluing
  (they should trigger through ~5 mm of plastic; check with a multimeter).
- **LED mount**: press-fits into the 5.4 mm hole in the front face. A drop of
  CA glue from inside if loose.
- If your reed switch turns out to be a normally-closed type (the lid logic
  seems inverted), flip `lid_closed_when_circuit_closed` in `config.yaml` —
  no resoldering.

## Verifying without a multimeter

```bash
# LED: should light for 5 seconds
python3 -c "from gpiozero import LED; import time; l=LED(12); l.on(); time.sleep(5)"

# Reed switch: prints True/False as you move the magnet
python3 -c "from gpiozero import Button; import time; b=Button(26); \
  [print(b.is_pressed) or time.sleep(0.5) for _ in range(20)]"

# Touch: count should rise as you tap (0 forever = LCD not on the header)
watch -n1 "grep ads7846 /proc/interrupts"
```
