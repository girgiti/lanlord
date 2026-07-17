# LANlord

A tiny, dependency-free network monitor that watches both your local gateway and internet connectivity, distinguishing LAN failures from ISP/WAN outages, with desktop and browser alerts.

Works on **macOS, Linux, and Windows**. Uses only the Python standard
library — no `pip install` required.

## What it does

1. Auto-detects your active network interface, local IP, subnet, and
   default gateway.
2. Independently monitors:
   - Your local gateway
   - Internet connectivity via multiple public endpoints

3. Internet connectivity is verified concurrently against:
   - Cloudflare DNS (1.1.1.1)
   - Google Public DNS (8.8.8.8)
   - Quad9 DNS (9.9.9.9)

   Internet is considered available if **any** provider responds, avoiding
   false alarms caused by a single endpoint outage.
3. **Automatically follows network changes** — switching Wi-Fi, hotspot,
   or getting a new DHCP lease with a totally different subnet is
   detected on the fly and pinging continues against the new gateway.
   For point-to-point VPN tunnels (WireGuard, IPsec, etc. - interfaces
   like `utun`/`ipsec0`/`tun0`), there's no traditional router, so
   LANlord pings the tunnel's peer address instead - see
   [VPN behavior](#vpn-and-point-to-point-tunnels) below.
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
- No third-party packages. Everything used (`http.server`, `socket`, `subprocess`, `threading`, `concurrent.futures`) is part of the standard library.
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
- Live Gateway and Internet status
- Live interface / IP / netmask / gateway information
- External connectivity probes (Cloudflare, Google DNS and Quad9)
- Blinking green/red health indicators
- Context-aware warning banner
- Browser notifications that distinguish **Gateway Unreachable** from **Internet Unavailable**
- Dynamic browser tab title (`🚨 GATEWAY DOWN` / `🚨 INTERNET DOWN`)
- Event history showing gateway failures, internet outages, recoveries and network changes


## Connectivity monitoring

LANlord performs two independent health checks every monitoring cycle.

### Local network

Your detected default gateway is pinged to verify that your LAN (router,
hotspot or VPN endpoint) is reachable.

### Internet

At the same time LANlord performs concurrent connectivity checks against:

- Cloudflare DNS (1.1.1.1)
- Google Public DNS (8.8.8.8)
- Quad9 DNS (9.9.9.9)

These checks run in parallel using Python's built-in
`concurrent.futures.ThreadPoolExecutor`, so the total check time is close
to a single ping timeout.

Internet is considered available if **any** external endpoint responds.

This allows LANlord to distinguish:

| Gateway | Internet | Meaning |
|---------|----------|---------|
| ✅ | ✅ | Healthy |
| ✅ | ❌ | ISP / WAN outage |
| ❌ | ❌ | Local network disconnected |


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
| `--probe-host IP` | `1.1.1.1` | Fallback ping target used when no real gateway can be detected (e.g. VPN tunnels with no meaningful peer address) |

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

# Use a different fallback probe host (e.g. your own DNS server) instead of 1.1.1.1
python3 lanlord.py --probe-host 8.8.8.8
```

## How it works

- **Gateway/IP/subnet detection** uses OS-native commands:
  `route`/`ifconfig` on macOS, `ip route`/`ip addr` on Linux, `ipconfig`
  on Windows — re-run on every ping cycle, so it follows network changes
  automatically. If auto-detection ever fails on an unusual setup,
  override it manually with `--gateway`.
- **Pinging** uses the OS's native `ping` binary with the correct flags
  per platform (`-c`/`-W` on Linux, `-c`/`-t` on macOS, `-n`/`-w` on
  Windows).

### VPN and point-to-point tunnels

Regular Wi-Fi/Ethernet networks have a router with its own address (the
"gateway") that's different from your machine's address. Point-to-point
VPN tunnels (WireGuard, IPsec, OpenVPN, etc. — interfaces named
`utun`/`ipsec0`/`tun0` and similar) don't always work that way. Two cases:

1. **Tunnel with a real, distinct peer address.** LANlord detects this
   (the `--> <address>` shown by macOS `ifconfig`, or `peer <address>`
   shown by Linux `ip addr`) and pings that peer directly, same as a
   normal gateway.
2. **Tunnel with no meaningful peer address.** Some VPN clients set the
   peer/remote address identical to your own local address as a
   placeholder — there's genuinely nothing distinct to ping there. When
   LANlord detects this (or any case where no real gateway can be found
   at all), it falls back to pinging `--probe-host` (default `1.1.1.1`)
   instead — a known-reliable external host, so a working internet
   connection through the tunnel is correctly reported as UP rather than
   being marked down just because there's no traditional router to ping.
   The dashboard/log will show this as e.g. `1.1.1.1 (probe)` in the
   gateway field, so it's clear what's actually being checked.

If your specific VPN client presents its virtual interface in a format
this doesn't recognize at all, `--gateway` still works as a manual
override — and feel free to open an issue with your `ifconfig`/`ip addr`
output for that interface so detection can be improved.

- **Web mode** is a plain `http.server` instance serving one JSON
  endpoint (`/status`) and one HTML page that polls it every 3 seconds —
  no frameworks, no build step.
- **Logging is consistent across modes.** Every up/down/network-change
  event is printed to stdout in both CLI and web mode, so whatever's in
  `/tmp/lanlord.log` (or your systemd/Task Scheduler logs) matches what
  the web dashboard's history panel shows.

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
   (a manual `--web` session, or a launchd/systemd/Task Scheduler
   service), it has the old code loaded in memory. Any edit needs a
   restart to take effect:
   ```bash
   # Manual run (any OS): just Ctrl+C and re-run it

   # macOS launchd service:
   launchctl bootout gui/$(id -u)/com.user.lanlord
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.lanlord.plist

   # Linux systemd service:
   systemctl --user restart lanlord.service
   ```
   ```powershell
   # Windows Task Scheduler service:
   Stop-ScheduledTask -TaskName "LANlord"
   Start-ScheduledTask -TaskName "LANlord"

   # If it's just running in a terminal/PowerShell window instead:
   # Ctrl+C, then re-run the same command
   ```
   On Windows, if you started it via `Register-ScheduledTask` (see
   "Running at startup" below) rather than a plain terminal window, you
   can also just log off and back on — `AtLogOn` triggers a fresh start
   automatically.

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
