#!/usr/bin/env python3
"""
LANlord
--------
Gateway connectivity monitor. Cross-platform (macOS, Linux, Windows).
Zero third-party dependencies - uses only the Python standard library.

Auto-detects your active network interface, local IP, subnet, and default
gateway, then continuously pings the gateway and alerts you when it goes
down (and when it recovers).

Two modes:

  CLI mode (default):
      python3 lanlord.py
      - Pings every 10s (configurable). Prints NOTHING while healthy -
        only prints when the gateway goes down / comes back up.
      - Fires a native OS notification + sound.

  Web mode (graphical dashboard, still zero dependencies):
      python3 lanlord.py --web
      - Starts a local web server (Python's built-in http.server) on
        http://127.0.0.1:8765 and opens it in your default browser.
      - The tab title blinks and a browser notification fires when the
        gateway is unreachable. A live event log is shown on the page.

See README.md for full setup and flags.

Author: @girgiti (https://github.com/girgiti)
License: MIT
"""

import subprocess
import re
import time
import argparse
import platform
import sys
import json
import shutil
import socket
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

SYSTEM = platform.system()  # "Darwin", "Linux", "Windows"


# ----------------------------------------------------------------------
# Shell helper
# ----------------------------------------------------------------------

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=6)
        return result.stdout.strip()
    except Exception:
        return ""


def cidr_to_netmask(cidr):
    if cidr is None:
        return None
    cidr = int(cidr)
    bits = (0xFFFFFFFF << (32 - cidr)) & 0xFFFFFFFF
    return ".".join(str((bits >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))


def netmask_to_cidr(netmask):
    if not netmask:
        return None
    return sum(bin(int(o)).count("1") for o in netmask.split("."))


def get_local_ip():
    """Cross-platform trick: open a UDP 'connection' (no packets sent) to
    find which local IP the OS would use for outbound traffic."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# ----------------------------------------------------------------------
# Network detection - one implementation per OS
# ----------------------------------------------------------------------

def detect_macos():
    output = run_cmd("route -n get default")
    gw_match = re.search(r"gateway:\s*([\d.]+)", output)
    if_match = re.search(r"interface:\s*(\S+)", output)
    gateway = gw_match.group(1) if gw_match else None
    interface = if_match.group(1) if if_match else None

    ip, netmask = None, None
    if interface:
        ifout = run_cmd(f"ifconfig {interface}")
        # Standard LAN-style interface: "inet <ip> netmask <hex>"
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)", ifout)
        if m:
            ip = m.group(1)
            netmask_int = int(m.group(2), 16)
            netmask = ".".join(str((netmask_int >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))
        else:
            # Point-to-point interface (VPN tunnels: utun, ipsec, ppp, etc.):
            # "inet <local> --> <peer> netmask <hex>". There's no separate
            # router here - the peer IS the other end of the tunnel, so we
            # treat it as the thing to ping.
            m = re.search(
                r"inet (\d+\.\d+\.\d+\.\d+) --> (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)",
                ifout,
            )
            if m:
                ip = m.group(1)
                peer = m.group(2)
                # Some VPN clients set the peer address identical to the
                # local address as a placeholder - that's not a real
                # second endpoint, so don't treat it as a gateway.
                if not gateway and peer != ip:
                    gateway = peer
                netmask_int = int(m.group(3), 16)
                netmask = ".".join(str((netmask_int >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))
    return interface, gateway, ip, netmask


def detect_linux():
    output = run_cmd("ip route show default")
    # Point-to-point tunnels often have no "via <ip>" - just "default dev tunX"
    m = re.search(r"default(?: via ([\d.]+))? dev (\S+)", output)
    if not m:
        return None, None, None, None
    gateway, interface = m.group(1), m.group(2)

    addr_output = run_cmd(f"ip -4 addr show dev {interface}")

    # Point-to-point tunnels (VPNs) report addresses as:
    #   inet <local> peer <remote>/<cidr>
    # rather than the usual "inet <local>/<cidr>". The local IP has no
    # CIDR of its own in this format, so it needs its own pattern - the
    # ordinary "inet <ip>/<cidr>" regex below would miss it entirely.
    peer_m = re.search(r"inet ([\d.]+) peer ([\d.]+)/(\d+)", addr_output)
    if peer_m:
        ip = peer_m.group(1)
        peer = peer_m.group(2)
        # Some VPN clients set the peer address identical to the local
        # address as a placeholder - that's not a real second endpoint,
        # so don't treat it as a gateway.
        if not gateway and peer != ip:
            gateway = peer
        netmask = cidr_to_netmask(peer_m.group(3))
    else:
        addr_m = re.search(r"inet ([\d.]+)/(\d+)", addr_output)
        ip = addr_m.group(1) if addr_m else None
        netmask = cidr_to_netmask(addr_m.group(2)) if addr_m else None

    return interface, gateway, ip, netmask


def detect_windows():
    output = run_cmd("ipconfig /all")
    local_ip = get_local_ip()
    blocks = re.split(r"\r?\n\r?\n", output)
    for block in blocks:
        if local_ip and local_ip in block:
            iface_m = re.search(r"^([^\r\n]*adapter[^\r\n]*):", block, re.IGNORECASE | re.MULTILINE)
            gw_m = re.search(r"Default Gateway[ .]*:\s*([\d.]+)", block)
            mask_m = re.search(r"Subnet Mask[ .]*:\s*([\d.]+)", block)
            interface = iface_m.group(1).strip() if iface_m else "Unknown adapter"
            gateway = gw_m.group(1) if gw_m else None
            netmask = mask_m.group(1) if mask_m else None
            return interface, gateway, local_ip, netmask
    return "Unknown adapter", None, local_ip, None


def detect_network_safe(args):
    """Auto-detect network info, allowing manual overrides via CLI flags.
    Never exits - returns (None, None, None, None)-shaped gaps if detection
    fails, so callers (especially the monitoring loop) can keep retrying
    across network changes instead of crashing."""
    try:
        if SYSTEM == "Darwin":
            interface, gateway, ip, netmask = detect_macos()
        elif SYSTEM == "Linux":
            interface, gateway, ip, netmask = detect_linux()
        elif SYSTEM == "Windows":
            interface, gateway, ip, netmask = detect_windows()
        else:
            interface, gateway, ip, netmask = None, None, get_local_ip(), None
    except Exception:
        interface, gateway, ip, netmask = None, None, None, None

    # Manual overrides always win, every cycle
    gateway = args.gateway or gateway
    interface = args.interface or interface
    ip = ip or get_local_ip()

    return interface, gateway, ip, netmask


def detect_network(args):
    """Startup version: same as detect_network_safe, but exits with a
    helpful message if no gateway can be found at all on first run."""
    interface, gateway, ip, netmask = detect_network_safe(args)
    if not gateway:
        print("Could not auto-detect the default gateway.")
        print("Pass it manually, e.g.:  --gateway 192.168.1.1")
        sys.exit(1)
    return interface, gateway, ip, netmask


# ----------------------------------------------------------------------
# Ping
# ----------------------------------------------------------------------

def ping_host(host, timeout=1):
    if SYSTEM == "Windows":
        cmd = f"ping -n 1 -w {int(timeout * 1000)} {host}"
    elif SYSTEM == "Darwin":
        cmd = f"ping -c 1 -t {int(timeout)} {host}"
    else:  # Linux / other POSIX
        cmd = f"ping -c 1 -W {int(timeout)} {host}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0


# ----------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------

def notify(title, message, sound=True):
    """Native OS notification + sound."""
    if SYSTEM == "Darwin":
        script = f'display notification "{message}" with title "{title}" sound name "Basso"'
        try:
            subprocess.run(["osascript", "-e", script], check=False, timeout=3)
        except Exception:
            pass
        if sound:
            try:
                subprocess.run(["afplay", "/System/Library/Sounds/Basso.aiff"], check=False, timeout=5)
            except Exception:
                pass

    elif SYSTEM == "Linux":
        if shutil.which("notify-send"):
            try:
                subprocess.run(["notify-send", title, message], check=False, timeout=3)
            except Exception:
                pass
        else:
            print("(tip: install 'libnotify-bin' / 'notify-send' for desktop popups)")
        if sound:
            print("\a", end="", flush=True)  # terminal bell fallback

    elif SYSTEM == "Windows":
        try:
            ps = (
                'Add-Type -AssemblyName System.Windows.Forms; '
                '$n = New-Object System.Windows.Forms.NotifyIcon; '
                '$n.Icon = [System.Drawing.SystemIcons]::Warning; '
                '$n.Visible = $true; '
                f'$n.ShowBalloonTip(5000,"{title}","{message}",'
                '[System.Windows.Forms.ToolTipIcon]::Warning)'
            )
            subprocess.run(["powershell", "-Command", ps], check=False, timeout=6)
        except Exception:
            pass
        if sound:
            try:
                import winsound
                winsound.MessageBeep()
            except Exception:
                pass


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------
# Shared monitor state (used by both CLI loop and web server thread)
# ----------------------------------------------------------------------

state_lock = threading.Lock()
state = {
    "status": "unknown",
    "gateway": None,
    "interface": None,
    "ip": None,
    "netmask": None,
    "last_check": None,
    "consecutive_failures": 0,
    "history": [],
}


def log_event(event):
    with state_lock:
        state["history"].insert(0, {"time": timestamp(), "event": event})
        state["history"] = state["history"][:50]


def monitor_loop(args, on_status_change=None, on_network_change=None):
    """Pings the gateway on a schedule, re-detecting the network every
    cycle so it follows changes automatically (switching Wi-Fi, hotspot,
    VPN, a new DHCP lease with a different subnet/CIDR, etc.).

    If no real gateway can be detected at all (fully offline, or a VPN
    tunnel with no meaningful peer address), falls back to pinging
    args.probe_host - a known-reliable external host - so a working
    internet connection through a tunnel isn't wrongly reported as
    down just because there's no traditional router to ping."""
    is_down = False
    down_since = None
    last_gateway = None
    last_interface = None

    while True:
        interface, gateway, ip, netmask = detect_network_safe(args)

        # What we actually ping: the detected gateway if we have one,
        # otherwise a known-reliable external probe host as a fallback
        # connectivity check (covers VPN tunnels with no meaningful
        # gateway/peer address, as well as being fully offline).
        using_probe = gateway is None and ip is not None
        ping_target = gateway if gateway else (args.probe_host if using_probe else None)
        display_target = gateway if gateway else (f"{args.probe_host} (probe)" if using_probe else None)

        # A "network change" is a real switch to a different interface or
        # gateway - not the transition into/out of being fully offline
        # (that's just a DOWN/UP event, already logged separately).
        network_changed = (
            last_interface is not None
            and interface is not None
            and (interface != last_interface or gateway != last_gateway)
        )
        if network_changed:
            log_event(f"Network changed - IP {ip or 'unknown'}, "
                      f"gateway {display_target or 'unknown'}")
            if on_network_change:
                on_network_change(interface, display_target, ip, netmask)
            # Old failure streak/down-state was against the previous
            # network - start fresh evaluation against the new one.
            with state_lock:
                state["consecutive_failures"] = 0

        last_gateway = gateway
        last_interface = interface

        with state_lock:
            state.update(interface=interface, gateway=display_target, ip=ip, netmask=netmask)

        reachable = ping_host(ping_target, timeout=args.timeout) if ping_target else False
        now = timestamp()

        with state_lock:
            state["last_check"] = now
            state["consecutive_failures"] = 0 if reachable else state["consecutive_failures"] + 1
            failures = state["consecutive_failures"]

        if reachable:
            if is_down:
                is_down = False
                with state_lock:
                    state["status"] = "up"
                log_event(f"Gateway {display_target} back UP")
                if on_status_change:
                    on_status_change(False, args, down_since, display_target)
                down_since = None
        else:
            if failures >= args.fail_threshold and not is_down:
                is_down = True
                down_since = datetime.now()
                with state_lock:
                    state["status"] = "down"
                if display_target:
                    log_event(f"Gateway {display_target} DOWN")
                else:
                    log_event("No network detected - DOWN")
                if on_status_change:
                    on_status_change(True, args, down_since, display_target)

        time.sleep(args.interval)


def format_duration(down_since):
    if not down_since:
        return None
    seconds = int((datetime.now() - down_since).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


# ----------------------------------------------------------------------
# CLI mode
# ----------------------------------------------------------------------

def run_cli(args):
    interface, gateway, ip, netmask = detect_network(args)
    cidr = netmask_to_cidr(netmask)

    with state_lock:
        state.update(interface=interface, gateway=gateway, ip=ip, netmask=netmask, status="up")

    print("=" * 50)
    print(f"LANlord (CLI) - {SYSTEM}")
    print("=" * 50)
    print(f"Interface : {interface or 'unknown'}")
    print(f"Local IP  : {ip or 'unknown'}")
    print(f"Netmask   : {netmask} (/{cidr})" if netmask else "Netmask   : unknown")
    print(f"Gateway   : {gateway}")
    print(f"Pinging every {args.interval}s (silent unless down). "
          f"Auto-follows network changes. Ctrl+C to stop.\n")

    def on_network_change(interface, gateway, ip, netmask):
        cidr = netmask_to_cidr(netmask)
        print(f"[{timestamp()}] Network changed - now on {interface or 'unknown'}, "
              f"IP {ip or 'unknown'}" + (f"/{cidr}" if cidr else "") +
              f", gateway {gateway or 'unknown'}")

    def on_change(is_down, args, down_since, gateway):
        if is_down:
            if gateway:
                print(f"[{timestamp()}] ALERT: Gateway {gateway} is DOWN "
                      f"(after {args.fail_threshold} failed pings)")
                notify("Network Down", f"Lost connectivity to gateway {gateway}",
                       sound=not args.no_sound)
            else:
                print(f"[{timestamp()}] ALERT: No network detected "
                      f"(after {args.fail_threshold} failed pings)")
                notify("Network Down", "No network detected - connection lost",
                       sound=not args.no_sound)
        else:
            duration = format_duration(down_since)
            suffix = f" (was down for {duration})" if duration else ""
            print(f"[{timestamp()}] Gateway {gateway} is back UP{suffix}")
            notify("Network Restored", f"Gateway {gateway} is reachable again.{suffix}",
                   sound=not args.no_sound)

    try:
        monitor_loop(args, on_status_change=on_change, on_network_change=on_network_change)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")


# ----------------------------------------------------------------------
# Web mode - pure stdlib HTTP server + single HTML page
# ----------------------------------------------------------------------

PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>LANlord - Internet Connectivity Monitor</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#111; color:#eee; margin:0; padding:40px; }
  .card { max-width:480px; margin:0 auto; background:#1c1c1e; border-radius:14px; padding:28px; }
  h1 { font-size:20px; margin-top:0; }
  .status { font-size:28px; font-weight:600; padding:14px 0; }
  .up { color:#32d74b; }
  .down { color:#ff453a; }
  .row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #2c2c2e; font-size:14px; }
  .row span:first-child { color:#8e8e93; }
  #history { margin-top:20px; font-size:13px; color:#aeaeb2; max-height:200px; overflow-y:auto; }
  #history div { padding:4px 0; border-bottom:1px solid #2c2c2e; }
  .footer { margin-top:20px; text-align:center; font-size:12px; color:#5a5a5c; }
  .footer a { color:#5a5a5c; text-decoration:none; }
  .footer a:hover { color:#8e8e93; text-decoration:underline; }
</style>
</head>
<body>
<div class="card">
  <h1>LANlord</h1>
  <div class="status" id="status">Checking...</div>
  <div class="row"><span>Interface</span><span id="interface">-</span></div>
  <div class="row"><span>Local IP</span><span id="ip">-</span></div>
  <div class="row"><span>Netmask</span><span id="netmask">-</span></div>
  <div class="row"><span>Gateway</span><span id="gateway">-</span></div>
  <div class="row"><span>Last check</span><span id="lastcheck">-</span></div>
  <div id="history"></div>
  <div class="footer">LANlord &middot; built by <a href="https://github.com/girgiti" target="_blank" rel="noopener">@girgiti</a></div>
</div>
<script>
const ORIGINAL_TITLE = "LANlord - Internet Connectivity Monitor";
let blinkTimer = null;
let notifiedDown = false;
let lastStatus = null;

if ("Notification" in window && Notification.permission === "default") {
  Notification.requestPermission();
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.frequency.value = 440;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    osc.start(); osc.stop(ctx.currentTime + 0.3);
  } catch (e) {}
}

function startBlink() {
  if (blinkTimer) return;
  let on = false;
  blinkTimer = setInterval(() => {
    document.title = on ? ORIGINAL_TITLE : "GATEWAY DOWN";
    on = !on;
  }, 1000);
}

function stopBlink() {
  if (blinkTimer) { clearInterval(blinkTimer); blinkTimer = null; }
  document.title = ORIGINAL_TITLE;
}

async function poll() {
  try {
    const res = await fetch("/status");
    const data = await res.json();

    document.getElementById("interface").textContent = data.interface || "-";
    document.getElementById("ip").textContent = data.ip || "-";
    document.getElementById("netmask").textContent = data.netmask || "-";
    document.getElementById("gateway").textContent = data.gateway || "-";
    document.getElementById("lastcheck").textContent = data.last_check || "-";

    const el = document.getElementById("status");
    if (data.status === "down") {
      el.textContent = "DOWN";
      el.className = "status down";
      startBlink();
      if (!notifiedDown) {
        notifiedDown = true;
        beep();
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("Network Down", { body: "Lost connectivity to gateway " + data.gateway });
        }
      }
    } else if (data.status === "up") {
      el.textContent = "UP";
      el.className = "status up";
      stopBlink();
      if (notifiedDown && lastStatus === "down") {
        beep();
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("Network Restored", { body: "Gateway " + data.gateway + " is reachable again." });
        }
      }
      notifiedDown = false;
    } else {
      el.textContent = "Checking...";
      el.className = "status";
    }
    lastStatus = data.status;

    const hist = document.getElementById("history");
    hist.innerHTML = data.history.map(h => `<div>${h.time} - ${h.event}</div>`).join("");
  } catch (e) {
    document.getElementById("status").textContent = "Server unreachable";
  }
}

poll();
setInterval(poll, 3000);
</script>
</body>
</html>
"""


class MonitorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *a):
        pass

    def do_GET(self):
        if self.path == "/status":
            with state_lock:
                payload = json.dumps(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path in ("/", "/index.html"):
            payload = PAGE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.end_headers()


def run_web(args):
    interface, gateway, ip, netmask = detect_network(args)
    with state_lock:
        state.update(interface=interface, gateway=gateway, ip=ip, netmask=netmask, status="up")

    def on_network_change(interface, gateway, ip, netmask):
        cidr = netmask_to_cidr(netmask)
        print(f"[{timestamp()}] Network changed - now on {interface or 'unknown'}, "
              f"IP {ip or 'unknown'}" + (f"/{cidr}" if cidr else "") +
              f", gateway {gateway or 'unknown'}")

    def on_change(is_down, args, down_since, gateway):
        if is_down:
            if gateway:
                print(f"[{timestamp()}] ALERT: Gateway {gateway} is DOWN "
                      f"(after {args.fail_threshold} failed pings)")
                notify("Network Down", f"Lost connectivity to gateway {gateway}",
                       sound=not args.no_sound)
            else:
                print(f"[{timestamp()}] ALERT: No network detected "
                      f"(after {args.fail_threshold} failed pings)")
                notify("Network Down", "No network detected - connection lost",
                       sound=not args.no_sound)
        else:
            duration = format_duration(down_since)
            suffix = f" (was down for {duration})" if duration else ""
            print(f"[{timestamp()}] Gateway {gateway} is back UP{suffix}")
            notify("Network Restored", f"Gateway {gateway} is reachable again.{suffix}",
                   sound=not args.no_sound)

    t = threading.Thread(
        target=monitor_loop,
        args=(args, on_change, on_network_change),
        daemon=True,
    )
    t.start()

    server = HTTPServer(("127.0.0.1", args.port), MonitorHandler)
    url = f"http://127.0.0.1:{args.port}"
    print("=" * 50)
    print(f"LANlord (Web) - {SYSTEM}")
    print("=" * 50)
    print(f"Interface : {interface or 'unknown'}")
    print(f"Local IP  : {ip or 'unknown'}")
    print(f"Gateway   : {gateway}")
    print(f"\nOpen this in your browser:  {url}")
    print("Press Ctrl+C to stop.\n")

    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LANlord - gateway connectivity monitor.")
    parser.add_argument("--web", action="store_true", help="Run graphical mode via local web server")
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between pings (default: 10)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Ping timeout in seconds (default: 1)")
    parser.add_argument("--fail-threshold", type=int, default=2,
                         help="Consecutive failed pings before alerting (default: 2)")
    parser.add_argument("--no-sound", action="store_true", help="Disable local sound alert")
    parser.add_argument("--port", type=int, default=8765, help="Web server port (web mode only)")
    parser.add_argument("--gateway", type=str, default=None,
                         help="Manually specify the gateway IP if auto-detect fails")
    parser.add_argument("--interface", type=str, default=None,
                         help="Manually specify the network interface name (cosmetic only)")
    parser.add_argument("--probe-host", type=str, default="1.1.1.1",
                         help="Fallback host to ping when no real gateway can be detected "
                              "(e.g. VPN tunnels with no meaningful peer address). Default: 1.1.1.1")
    args = parser.parse_args()

    if args.web:
        run_web(args)
    else:
        run_cli(args)


if __name__ == "__main__":
    main()
