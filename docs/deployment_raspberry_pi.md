# Raspberry Pi Deployment Guide

How to run Lab Flightboard on a Raspberry Pi as a permanent, boot-on wall
display in full-screen kiosk mode.

---

## Requirements

**Hardware**

- **Raspberry Pi 4 (or newer)**, 2 GB RAM is plenty. A Pi 4 drives a 4K TV at
  this board's simple layout comfortably; a Pi 3 is fine for 1080p.
- **microSD card** (16 GB+) and a good power supply.
- **HDMI cable** to the TV/monitor (Pi 4 uses micro-HDMI).
- **Network** — Wi-Fi or Ethernet, with outbound internet to reach your feeds.

**Software** (all installed in the steps below)

- **Raspberry Pi OS (64-bit, with desktop)** — Bookworm or newer.
- **Python 3.10+** (ships with Pi OS) and `pip`.
- **Flask** and the `lab_flightboard` package + its dependencies.
- **Chromium** (ships with Pi OS) for the kiosk display.

**Network ports** — none need opening. The Pi only makes *outbound* HTTPS
requests to your iCal feeds. The board is served locally on port 5200; open that
only if you also want to view it from another machine.

---

## Quick version

For someone comfortable on the command line — full details follow below.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-pip chromium-browser unclutter
git clone https://github.com/elliotcheng-uq/Lab-flightboard.git
cd Lab-flightboard
pip install -e . flask --break-system-packages
cp examples/billboard_config.minimal.json billboard_config.json
nano billboard_config.json            # add your instruments + iCal URLs
python3 examples/billboard_app.py     # test at http://localhost:5200
```

Then set up the systemd service (step 3) and the kiosk autostart (step 4) so it
runs on boot.

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
git clone https://github.com/elliotcheng-uq/Lab-flightboard.git
cd Lab-flightboard
pip install -e . --break-system-packages
pip install flask --break-system-packages
```

> On Pi OS Bookworm, `--break-system-packages` installs into the system Python.
> Alternatively use a virtualenv (`python3 -m venv .venv && source .venv/bin/activate`)
> and adjust the service `ExecStart` path below.

Create your config (this file is git-ignored, so your private feed URLs stay
local):

```bash
cp examples/billboard_config.minimal.json billboard_config.json
nano billboard_config.json    # replace the example URLs with your iCal feeds
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
WorkingDirectory=/home/pi/Lab-flightboard
ExecStart=/usr/bin/python3 examples/billboard_app.py /home/pi/Lab-flightboard/billboard_config.json
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
