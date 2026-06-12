# Raspberry Pi Deployment Guide

How to run Lab Flightboard on a Raspberry Pi as a permanent, boot-on wall
display in full-screen kiosk mode.

This suits a Pi 4 (or newer) driving a TV over HDMI. A Pi 4 handles a 4K display
at this board's simple layout comfortably.

---

## 1. Operating system

Install **Raspberry Pi OS (64-bit, with desktop)** using Raspberry Pi Imager.
In the imager's advanced settings, set the hostname, enable SSH, and configure
Wi-Fi/locale so you can finish setup headless.

Boot the Pi, then update:

```bash
sudo apt update && sudo apt full-upgrade -y
```

Set the timezone (also set `"timezone"` to match in your billboard config):

```bash
sudo raspi-config    # Localisation Options -> Timezone
```

---

## 2. Install Lab Flightboard

```bash
sudo apt install -y git python3-pip
git clone https://github.com/<your-org>/lab-flightboard.git
cd lab-flightboard
pip install -e . --break-system-packages
pip install flask --break-system-packages
```

> On Pi OS Bookworm, `--break-system-packages` installs into the system Python.
> Alternatively use a virtualenv (`python3 -m venv .venv && source .venv/bin/activate`)
> and adjust the service `ExecStart` path below.

Create your config (this file is git-ignored, so your private feed URLs stay
local):

```bash
cp examples/billboard_config.example.json billboard_config.json
nano billboard_config.json    # replace demo:// feeds with your https iCal URLs
```

Test it:

```bash
python3 examples/billboard_app.py
# open http://localhost:5200 in the Pi's browser
```

---

## 3. Run the server on boot (systemd)

Create the service. Adjust `User` and paths if you used a virtualenv or a
different clone location.

```bash
sudo nano /etc/systemd/system/flightboard.service
```

```ini
[Unit]
Description=Lab Flightboard billboard server
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/lab-flightboard
ExecStart=/usr/bin/python3 examples/billboard_app.py /home/pi/lab-flightboard/billboard_config.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now flightboard.service
sudo systemctl status flightboard.service
```

The board is now served at `http://localhost:5200` and restarts if it crashes or
the Pi reboots.

---

## 4. Open the display in kiosk mode on boot

Install Chromium and a couple of helpers:

```bash
sudo apt install -y chromium-browser unclutter
```

Create a desktop autostart entry that waits for the server, then opens Chromium
full-screen with the cursor hidden:

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/flightboard-kiosk.desktop
```

```ini
[Desktop Entry]
Type=Application
Name=Lab Flightboard Kiosk
Exec=/bin/bash -c 'until curl -s http://localhost:5200 >/dev/null; do sleep 2; done; unclutter -idle 0 & chromium-browser --noerrordialogs --disable-infobars --kiosk --incognito http://localhost:5200'
X-GNOME-Autostart-enabled=true
```

Reboot to test:

```bash
sudo reboot
```

The Pi should boot straight into the full-screen board.

---

## 5. Stop the screen from blanking

Prevent the display from sleeping. On Pi OS with the Wayland/labwc or X11
desktop, the simplest reliable approach is `xset` via autostart (X11) — add to
the same autostart `Exec` chain before launching Chromium:

```bash
xset s off; xset -dpms; xset s noblank;
```

Or disable screen blanking in `raspi-config` -> Display Options -> Screen Blanking.

---

## 6. Day-to-day

| Task | Command |
|---|---|
| View logs | `journalctl -u flightboard.service -f` |
| Restart after a config edit | `sudo systemctl restart flightboard.service` |
| Reload the screen only | `Ctrl+R` in the kiosk, or restart the Pi |
| Update the code | `git pull` then restart the service |

The board re-fetches feeds every `refresh_seconds` (default 60s) on its own, so
new bookings and incidents appear without any intervention.

---

## Notes

- The board only needs **outbound HTTPS** to reach your iCal feeds. No inbound
  ports need opening unless you want to view it from another machine
  (`http://<pi-ip>:5200`).
- Keep `billboard_config.json` on the Pi only. It is git-ignored for a reason —
  it may contain private calendar tokens.
- For a public-facing screen, set `"mode": "status-only"` so no booking names are
  shown. See [billboard.md](billboard.md).
