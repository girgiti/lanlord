# LANlord

A tiny, dependency-free tool that watches your default network gateway and
alerts you the moment your connection drops — on your desktop and in a
browser tab.

Works on **macOS, Linux, and Windows**. Uses only the Python standard
library — no `pip install` required.

## What it does

1. Auto-detects your active network interface, local IP, subnet, and
   default gateway.
2. Pings the gateway on a schedule (default: every 10 seconds).
3. **Automatically follows network changes** — switching Wi-Fi, hotspot,
   VPN, or getting a new DHCP lease with a totally different subnet is
   detected on the fly and pinging continues against the new gateway.
4. When a configurable number of consecutive pings fail, it fires an alert:
   - A native OS notification (Notification Center / libnotify / Windows
     toast) and a sound
   - A blinking browser tab + browser notification, if running in
     **web mode**
5. Sends a "back up" alert too, including how long it was down.

## Requirements

- Python 3.7+ (already installed on macOS and most Linux distros; on
  Windows, install from [python.org](https://www.python.org/downloads/)
  or the Microsoft Store)
- No third-party packages. Everything used (`http.server`, `socket`,
  `subprocess`, `threading`) is part of the standard library.
- **Linux only, optional:** `notify-send` (usually part of `libnotify-bin`
  / `libnotify`) for desktop popups:
  ```bash
  # Debian/Ubuntu
  sudo apt install libnotify-bin
  # Fedora
  sudo dnf install libnotify
  # Arch
  sudo pacman -S libnotify
  ```
  If it's missing, LANlord just skips the popup and still does everything
  else (terminal bell, web dashboard).

## Quick start

```bash
git clone https://github.com/girgiti/lanlord.git
cd lanlord
python3 lanlord.py
```

No install step — it auto-detects your gateway and starts monitoring
immediately.

## Modes

### CLI mode (default)

```bash
python3 lanlord.py
```

Runs silently in the terminal — prints nothing while your connection is
healthy, and only prints when the gateway goes down, comes back up, or the
network itself changes. Still fires OS notifications/sound on every state
change.

Example output:
```
==================================================
LANlord (CLI) - Darwin
==================================================
Interface : en0
Local IP  : 192.168.1.50
Netmask   : 255.255.255.0 (/24)
Gateway   : 192.168.1.1
Pinging every 10.0s (silent unless down). Auto-follows network changes. Ctrl+C to stop.

[2026-07-11 15:44:14] ALERT: Gateway 192.168.1.1 is DOWN (after 2 failed pings)
[2026-07-11 15:44:34] Gateway 192.168.1.1 is back UP (was down for 20s)
```

### Web mode (graphical dashboard)

```bash
python3 lanlord.py --web
```

Starts a local web server at `http://127.0.0.1:8765` and opens it in your
default browser automatically.

**Getting it fully working:**
1. Run the command above — it opens the dashboard for you. If it doesn't,
   just visit `http://127.0.0.1:8765` manually.
2. Your browser will prompt for notification permission — click
   **Allow**. Without this, you'll still get the blinking tab, but not
   the pop-up notification.
3. Leave the tab open somewhere (it doesn't need to be the active/focused
   tab — background is fine). Closing it stops the visual alerts, though
   the server and ping loop keep running regardless.

While it's open, you'll see:
- Live interface / IP / netmask / gateway / last-check info
- A big status indicator (UP / DOWN)
- The tab title blinking `GATEWAY DOWN` when the connection drops
- A browser notification + beep on every state change
- A scrolling history log of every up/down/network-change event

## How fast are alerts?

With the defaults (`--interval 10`, `--fail-threshold 2`):

- **Detecting "up"**: needs only one successful ping → worst case
  **~13s** (1 interval + ~3s web poll)
- **Detecting "down"**: waits for 2 consecutive failures on purpose, to
  avoid a false alarm from a single dropped packet → worst case **~23s**
  (interval × fail-threshold + ~3s web poll)

Want it faster? Lower `--interval` and/or `--fail-threshold`:
```bash
python3 lanlord.py --interval 5 --fail-threshold 1
```
That trades detection speed for a higher chance of a false alarm on a
single dropped packet.

## All options

| Flag | Default | Description |
|---|---|---|
| `--web` | off | Run graphical mode via local web server |
| `--interval` | `10` | Seconds between pings |
| `--timeout` | `1` | Ping timeout in seconds |
| `--fail-threshold` | `2` | Consecutive failed pings before alerting |
| `--no-sound` | off | Disable the local sound alert |
| `--port` | `8765` | Web server port (web mode only) |
| `--gateway IP` | auto | Manually specify the gateway if auto-detect fails |
| `--interface NAME` | auto | Manually specify the interface name (cosmetic only) |

### Sample commands

```bash
# Default CLI mode
python3 lanlord.py

# Web dashboard on the default port
python3 lanlord.py --web

# Web dashboard on a different port (e.g. if 8765 is taken)
python3 lanlord.py --web --port 8899

# Faster detection, no sound
python3 lanlord.py --interval 5 --fail-threshold 1 --no-sound

# Manually pin the gateway (useful if auto-detect fails on an unusual setup)
python3 lanlord.py --gateway 192.168.1.1

# Longer ping timeout for a slow/high-latency network
python3 lanlord.py --timeout 3
```

## How it works

- **Gateway/IP/subnet detection** uses OS-native commands:
  `route`/`ifconfig` on macOS, `ip route`/`ip addr` on Linux, `ipconfig`
  on Windows — re-run on every ping cycle, so it follows network changes
  automatically. If auto-detection fails on your setup (unusual network
  configs, VPNs, etc.), override it manually with `--gateway`.
- **Pinging** uses the OS's native `ping` binary with the correct flags
  per platform (`-c`/`-W` on Linux, `-c`/`-t` on macOS, `-n`/`-w` on
  Windows).
- **Web mode** is a plain `http.server` instance serving one JSON
  endpoint (`/status`) and one HTML page that polls it every 3 seconds —
  no frameworks, no build step.

## Testing it — simulating outages and network changes

Handy for confirming alerts actually fire before you rely on it.

### Check current network info manually

```bash
# macOS
route -n get default
ifconfig en0        # swap en0 for your interface

# Linux
ip route show default
ip -4 addr show

# Windows (PowerShell or cmd)
ipconfig /all
route print -4
```

### Simulate a total disconnect (gateway DOWN)

```bash
# macOS — toggle Wi-Fi off/on (find your interface name first)
networksetup -listallhardwareports
networksetup -setairportpower en0 off
sleep 30
networksetup -setairportpower en0 on

# Linux — toggle via nmcli (NetworkManager) or the interface directly
nmcli radio wifi off
sleep 30
nmcli radio wifi on
# or, without NetworkManager:
sudo ip link set wlan0 down
sleep 30
sudo ip link set wlan0 up

# Windows (elevated PowerShell)
Disable-NetAdapter -Name "Wi-Fi" -Confirm:$false
Start-Sleep -Seconds 30
Enable-NetAdapter -Name "Wi-Fi" -Confirm:$false
```
You should see a DOWN alert after ~20s (default settings), then an UP
alert with the outage duration once it's back.

### Simulate a network change (Wi-Fi ↔ hotspot, different subnet)

Just physically switch — turn on your phone's hotspot and connect your
machine to it, or move between two known Wi-Fi networks. Watch the
terminal or dashboard history log for a line like:
```
[2026-07-11 15:44:04] Network changed - now on en0, IP 172.20.10.5/28, gateway 172.20.10.1
```
No special commands needed — LANlord re-detects the network on every
ping cycle, so it'll pick this up within one interval automatically.

### Ping the gateway manually, for comparison

```bash
# macOS
ping -c 4 -t 2 192.168.1.1

# Linux
ping -c 4 -W 2 192.168.1.1

# Windows
ping -n 4 -w 2000 192.168.1.1
```

## Running at startup

### macOS (launchd)

1. Edit `launchd/com.user.lanlord.plist`:
   - Replace `YOUR_USERNAME` and the script path with your actual path
   - Confirm your Python 3 path matches: `which python3`
2. Install and load it (modern `launchctl` syntax — avoid `sudo` and
   avoid the older `load`/`unload` commands, which throw a cryptic
   `Input/output error` on current macOS):
   ```bash
   cp launchd/com.user.lanlord.plist ~/Library/LaunchAgents/
   plutil -lint ~/Library/LaunchAgents/com.user.lanlord.plist   # sanity check, should print OK
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.lanlord.plist
   ```
3. Manage it:
   ```bash
   launchctl print gui/$(id -u)/com.user.lanlord   # check it's running
   cat /tmp/lanlord.log                            # view logs
   launchctl bootout gui/$(id -u)/com.user.lanlord # stop
   ```

> **Port conflict note:** if you also run `lanlord.py --web` manually
> while the launchd agent is active, both will try to bind port `8765`
> and one will fail. Stop the manual copy first (`Ctrl+C`), or give one
> of them a different `--port`.

### Linux (systemd, user service)

1. Edit `systemd/lanlord.service` — update the script path.
2. Install it:
   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/lanlord.service ~/.config/systemd/user/
   systemctl --user enable --now lanlord.service
   ```
3. Manage it:
   ```bash
   systemctl --user status lanlord.service
   journalctl --user -u lanlord.service -f   # live logs
   systemctl --user disable --now lanlord.service  # stop
   ```
   If it doesn't start automatically at boot (before login), run:
   `sudo loginctl enable-linger $USER`

### Windows (Task Scheduler)

Run this once from an elevated PowerShell prompt (adjust the path):

```powershell
$action = New-ScheduledTaskAction -Execute "python.exe" -Argument "C:\path\to\lanlord.py --web"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "LANlord" -Action $action -Trigger $trigger -RunLevel Limited
```

Manage it via the Task Scheduler GUI, or:

```powershell
Get-ScheduledTask -TaskName "LANlord"
Unregister-ScheduledTask -TaskName "LANlord" -Confirm:$false   # remove
```

## Customizing messages / troubleshooting edits

If you edit the script and a change doesn't seem to take effect, check
these two things first:

1. **Alert text lives in Python, not in the HTML.** The `PAGE_HTML`
   block only renders whatever text it's given — it doesn't generate any
   of the actual alert wording. The messages themselves (including the
   `(none detected)` fallback shown when no gateway can be found) are
   built in `monitor_loop()`, `run_cli()`, and `run_web()` as plain
   Python f-strings, e.g.:
   ```python
   log_event(f"Gateway {gateway or '(none detected)'} DOWN")
   ```
   Editing the HTML/JS section won't change this — you need to edit
   these Python f-strings directly if you want different wording.

2. **Python doesn't hot-reload.** If the process is already running
   (a manual `--web` session, or the launchd/systemd service), it has
   the old code loaded in memory. Any edit needs a restart to take
   effect:
   ```bash
   # Manual run: just Ctrl+C and re-run it

   # macOS launchd service:
   launchctl bootout gui/$(id -u)/com.user.lanlord
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.lanlord.plist

   # Linux systemd service:
   systemctl --user restart lanlord.service
   ```

## Notes and caveats

- **Sleep pauses everything.** If your machine sleeps, the ping loop
  pauses too — this only monitors while the machine is actually awake.
- **Web mode alerts need the tab open.** The server and ping loop keep
  running either way, but the blinking title/browser notification only
  fire while the tab is open somewhere.
- **No remote/phone alerts.** This is intentionally local-only — alerts
  only reach you on the machine running the script, in the terminal or
  a browser tab on that same machine.
- **One port, one instance.** Running two copies of `--web` at once
  (e.g. a manual run plus a startup service) will conflict on the same
  port — see the launchd note above.

## License

MIT — see [LICENSE](LICENSE).

---

Built by [@girgiti](https://github.com/girgiti)
