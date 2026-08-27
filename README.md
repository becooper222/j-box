# J-Box ♥

A small wooden-jewelry-box-sized gift for Julia: a lidded box with a screen
inside. You send her a note from your phone; a warm LED on the box starts
breathing; she opens the lid and the note types itself out like a letter.
She can tap a heart to send love back, and browse every note ever sent.

## How it works

```
 your phone                    cloud                        the box
┌────────────┐   POST   ┌────────────────┐    poll    ┌───────────────────┐
│ /jbox page ├─────────►│ task-manager   │◄───────────┤ Pi Zero 2 W       │
│ (Auth0)    │          │ on Vercel      │  every 60s │  · pygame app     │
│            │◄─────────┤   │            ├───────────►│  · 4" HDMI touch  │
│ "Julia ♥'d │  status  │   ▼            │  messages  │  · LED (GPIO18)   │
│  this"     │          │ Supabase       │            │  · reed sw (GPIO17)│
└────────────┘          │ jbox_messages  │            └───────────────────┘
                        └────────────────┘
```

- **Send page**: `/jbox` route added to your existing task-manager app,
  behind your existing Auth0 login. Send from anywhere.
- **Storage**: one new table (`jbox_messages`) in your existing Supabase
  project, RLS-locked so the public anon key can't read it.
- **Device**: the Pi polls `/api/jbox/device` with a secret bearer token,
  caches notes locally (works through WiFi hiccups), reports
  delivered / read / hearted back — which show up live on your send page.

## The flow she experiences

1. Box sits closed and dark. A note arrives → the LED starts a slow pulse.
2. She opens the lid (reed switch) → screen wakes → the note reveals itself
   typewriter-style, headed "Day 2,913 of us" (or a gold occasion banner).
3. She can tap the ♥ (you get "Julia ♥'d this" on your page) or browse the
   archive of every note. Closing the lid puts everything back to sleep.

## Repo layout

```
pi/                  everything that runs on the Pi
  jbox/              the Python app (config, API client, hardware, UI)
  config.example.yaml
  jbox.service       systemd unit (auto-start, auto-restart)
  install.sh
case/jbox_case.scad  parametric 3D-printable enclosure (3 parts, no supports)
docs/pi-setup.md     flash → config.txt → install → test
docs/wiring.md       LED + reed switch soldering, pin map
```

Server-side pieces live in the task-manager repo:
`app/jbox/page.tsx`, `app/api/jbox/{messages,device}/route.ts`,
`supabase/migrations/20260826001_jbox.sql`.

## Shopping list (~$10)

| Item | Notes |
|---|---|
| 5 mm warm-white LED (a few spares) | diffused lens looks softest |
| 220–330 Ω resistors | for the LED |
| Normally-open reed switch + small disc magnet (~8×3 mm) | lid sensor |
| M2.5 screws/standoffs kit | mounts screen + Pi in the case |
| Right-angle mini-HDMI adapter | if your current adapter is too tall for the case |
| PETG or PLA filament | whoever prints it will likely supply this |

Already have: Pi Zero 2 W, USB hub HAT, 32 GB SD, Waveshare 4" HDMI LCD,
soldering iron, wires, USB power.

## Build order

1. **Server** — apply the Supabase migration, set `JBOX_DEVICE_TOKEN`
   (`openssl rand -hex 32`) in Vercel env, deploy task-manager, open
   `/jbox` and send a test note.
2. **Pi on the bench** — follow `docs/pi-setup.md`; run the app with a
   keyboard first (`o`/`c` simulate the lid) before any soldering.
3. **Solder** — LED + reed switch per `docs/wiring.md`; test the full flow
   loose on the desk.
4. **Case** — measure the screen with calipers, update the MEASURE values in
   `case/jbox_case.scad`, print the `test` part first to check the aperture,
   then all three parts. Assemble, glue magnet, thread the hinge pin.
5. **Personalize** — fill `dates:` in `config.yaml` (anniversary, her
   birthday) before gifting.

## Before gifting checklist

- [ ] Anniversary + birthday set in `config.yaml`
- [ ] Send a real first note (it'll be the first thing she ever opens)
- [ ] `sudo systemctl enable jbox` so it survives unplugging
- [ ] Test: unplug the box, plug it back in, send a note, watch the LED
