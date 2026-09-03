#!/usr/bin/env bash
# Run on the Pi from inside the pi/ directory: bash install.sh
set -euo pipefail

echo "==> Installing packages"
sudo apt-get update
# libegl1/libgles2/libgl1-mesa-dri: SDL's kmsdrm driver needs them and
# Raspberry Pi OS Lite doesn't ship them
sudo apt-get install -y python3-pygame python3-gpiozero python3-requests python3-yaml \
  libegl1 libgles2 libgl1-mesa-dri libgbm1 python3-numpy python3-evdev

# keep the console's login prompt and blinking cursor off the display
sudo systemctl disable --now getty@tty1 2>/dev/null || true
echo 0 | sudo tee /sys/class/graphics/fbcon/cursor_blink > /dev/null 2>&1 || true
CMDLINE=/boot/firmware/cmdline.txt
[ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
if [ -f "$CMDLINE" ] && ! grep -q vt.global_cursor_default "$CMDLINE"; then
  sudo cp "$CMDLINE" "$CMDLINE.bak"
  sudo sed -i '1s/$/ vt.global_cursor_default=0 consoleblank=0 logo.nologo/' "$CMDLINE"
  echo "==> Disabled console cursor (takes effect next boot)"
fi

if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
  echo "==> Created config.yaml - EDIT IT NOW (base_url, device_token, dates)"
fi

echo "==> Installing systemd service"
sudo cp jbox.service /etc/systemd/system/jbox.service
sudo systemctl daemon-reload
sudo systemctl enable jbox

echo "==> Done. Edit config.yaml, then: sudo systemctl start jbox"
echo "    Logs: journalctl -u jbox -f"
