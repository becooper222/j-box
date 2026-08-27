# Raspberry Pi setup

Target: Pi Zero 2 W, Raspberry Pi OS **Lite** (64-bit, Bookworm), Waveshare
4inch HDMI LCD (800×480, XPT2046 touch). No desktop environment — the app
draws straight to the display via SDL/KMS.

## 1. Flash the SD card

Use Raspberry Pi Imager on your Mac:

1. Choose *Raspberry Pi OS Lite (64-bit)* and your 32 GB card.
2. In the Imager settings (gear icon): set hostname `jbox`, enable SSH,
   set user `pi` + password, and enter your home WiFi credentials.

## 2. Configure the display + touch

The 4" HDMI LCD needs explicit timings, and its touch controller needs the
`ads7846` overlay. After flashing, the card mounts on your Mac as
`bootfs` — edit `config.txt` on it (on the Pi it lives at
`/boot/firmware/config.txt`) and append:

```ini
# --- J-Box: Waveshare 4inch HDMI LCD ---
hdmi_group=2
hdmi_mode=87
hdmi_cvt 800 480 60 6 0 0 0
hdmi_drive=1
# touch (XPT2046 on SPI0 CE1, IRQ on GPIO25)
dtoverlay=ads7846,cs=1,penirq=25,penirq_pull=2,speed=50000,keep_vref_on=0,swapxy=0,pmax=255,xohms=150,xmin=200,xmax=3900,ymin=200,ymax=3900
```

If touch coordinates end up mirrored or swapped once you test, adjust
`swapxy=1` and/or swap the min/max pairs above — the Waveshare wiki for
"4inch HDMI LCD" lists the variants.

## 3. Install the app

```bash
ssh pi@jbox.local
git clone <your-repo-url> jbox        # or: scp -r the J-Box folder over
cd jbox/pi
bash install.sh
nano config.yaml                      # base_url, device_token, dates
```

`device_token` must equal the `JBOX_DEVICE_TOKEN` you set in the
task-manager's Vercel environment. Generate it once with
`openssl rand -hex 32` and paste it in both places.

## 4. Test interactively, then enable

```bash
# foreground test (Esc quits; 'o'/'c' fake the lid if nothing is wired yet)
sudo systemctl stop jbox 2>/dev/null
SDL_VIDEODRIVER=kmsdrm python3 -m jbox

# happy? run it as a service, forever:
sudo systemctl start jbox
journalctl -u jbox -f
```

The service auto-starts on boot and restarts if it ever crashes, so the box
survives power cuts — just plug it back in.

## 5. Power

Any decent 5 V / 2.5 A USB power supply into the Pi's PWR port. The screen
is powered from the Pi. Total draw is ~3–4 W; it's fine to leave on 24/7.

## Troubleshooting

- **Blank screen**: check `hdmi_` lines landed in `/boot/firmware/config.txt`
  (not the old `/boot/config.txt`), and that the HDMI adapter is seated.
- **No touch**: `ls /dev/input/` should show an `event*` device from
  `ADS7846`; `dmesg | grep -i ads7846` confirms the overlay loaded.
- **No messages arriving**: `journalctl -u jbox -f` — a 401 means the token
  mismatch; a DNS error means WiFi credentials.
- **LED never lights**: run `python3 -c "from gpiozero import LED; import time; l=LED(18); l.on(); time.sleep(5)"`.
