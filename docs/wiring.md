# J-Box wiring

Three things get soldered: the LED, the reed switch, and the heart button.

## Why there is a button and not touch

This LCD sends **video over HDMI but touch over the GPIO header** — the
XPT2046 is an SPI part, so touch only works if the panel is seated on the
Pi's 40-pin header. We deliberately don't do that: the panel would cover
physical pins 1–26 and fight the USB hub HAT, and a real button is nicer
to press than glass. The screen is HDMI-only, so the entire header is ours.

(If you ever do seat the panel on the header, note it drives **GPIO 18 as
backlight PWM** — don't put the LED there. Symptom of a panel expecting
touch but not connected: the `ads7846` count in `/proc/interrupts` stays
at 0 no matter how much you tap.)

## Pin map (BCM numbering)

| Part | GPIO (BCM) | Physical pin | Goes to |
|---|---|---|---|
| LED anode (long leg) | GPIO 12 | 32 | via 330 Ω resistor |
| LED cathode (short leg) | GND | 34 | ground |
| Button leg 1 | GPIO 16 | 36 | either leg, no polarity |
| Button leg 2 | GND | 39 | ground |
| Reed switch leg 1 | GPIO 26 | 37 | either leg, no polarity |
| Reed switch leg 2 | GND | 39 | ground (shares with button) |

```
 Pi header, bottom corner (pins 27-40)        LED
                                               ___
  pin 32 G12  o───[ 330Ω ]──────────────┐     |>| warm white 5mm
  pin 34 GND  o──────────────────────┐  └─────┤
                                     └────────┘
  pin 36 G16  o──────────── button ──┐
  pin 37 G26  o──────────── reed ────┤
  pin 39 GND  o──────────────────────┘  (both grounds share pin 39)
```

## How the button behaves

One button does everything:

| Action | While reading | While browsing |
|---|---|---|
| **Tap** | sends the ♥ | shows the note before |
| **Hold** (0.8 s) | starts browsing back | returns to the newest |

Closing the lid always resets to the newest note.

## Notes

- **LED**: GPIO 12 is hardware-PWM capable, which is what makes the pulse
  smooth. It is also clear of GPIO 18, which this LCD drives as its
  backlight — putting the LED there would have fought the panel. 330 Ω is
  safe; use 220 Ω for brighter. Solder the resistor in line with the anode
  and cover it with heat-shrink.
- **Reed switch and button**: no polarity, no resistors needed — the code
  enables the Pi's internal pull-ups. Glass reed switches crack easily: bend
  the legs with pliers holding the lead at the glass, never by pulling on the
  body.
- **Button choice**: any momentary (normally-open) pushbutton. A 12 mm
  tactile switch fits the printed case; a larger arcade-style or metal dome
  button feels better to press and is worth the extra hole size.
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

Stop the service first so it isn't holding the pins: `sudo systemctl stop jbox`
(and `sudo systemctl start jbox` when done).

```bash
# LED: should light for 5 seconds
python3 -c "from gpiozero import LED; import time; l=LED(12); l.on(); time.sleep(5)"

# Reed switch: prints True/False as you move the magnet past it
python3 -c "from gpiozero import Button; import time; b=Button(26); \
  [print(b.is_pressed) or time.sleep(0.5) for _ in range(20)]"

# Button: prints True while held
python3 -c "from gpiozero import Button; import time; b=Button(16); \
  [print(b.is_pressed) or time.sleep(0.5) for _ in range(20)]"
```
