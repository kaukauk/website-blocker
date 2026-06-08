#!/usr/bin/env python3
"""Social-site blocker with a 5-minute rolling-hour budget."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HOSTS = Path("/etc/hosts")
STATE_DIR = Path("/var/lib/social-blocker")
USAGE_LOG = STATE_DIR / "usage.log"
PID_FILE = STATE_DIR / "session.pid"
SESSION_START_FILE = STATE_DIR / "session.start"
PAUSE_UNTIL_FILE = STATE_DIR / "pause_until"
MARK_BEGIN = "# >>> social-blocker >>>"
MARK_END = "# <<< social-blocker <<<"

BUDGET_SECONDS = 300

SITES = [
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "snapchat.com", "www.snapchat.com", "web.snapchat.com", "accounts.snapchat.com",
    "reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com",
    "np.reddit.com", "i.redd.it",
]

# Substrings that appear in the TLS SNI of the blocked services and their CDNs.
# Matched in the cleartext ClientHello of outbound TCP 443 packets.
SNI_PATTERNS = [
    "youtube.com", "googlevideo.com", "ytimg.com", "youtu.be",
    "instagram.com", "cdninstagram.com",
    "facebook.com", "fbcdn.net",
    "snapchat.com", "snap.com",
    "reddit.com", "redd.it", "redditmedia.com", "redditstatic.com",
]

CHAIN = "SOCIAL_BLOCKER"


def require_root() -> None:
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "--", sys.executable, *sys.argv])


def read_hosts_clean() -> str:
    """Return /etc/hosts contents with any managed block stripped."""
    text = HOSTS.read_text()
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        s = line.rstrip("\n")
        if s == MARK_BEGIN:
            skip = True
            continue
        if s == MARK_END:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "".join(out)


def is_blocked() -> bool:
    return MARK_BEGIN in HOSTS.read_text()


def write_blocked() -> None:
    body = read_hosts_clean()
    if not body.endswith("\n"):
        body += "\n"
    block = [MARK_BEGIN] + [f"0.0.0.0 {s}" for s in SITES] + [MARK_END, ""]
    HOSTS.write_text(body + "\n".join(block))
    flush_dns()
    apply_firewall()


def write_unblocked() -> None:
    HOSTS.write_text(read_hosts_clean())
    flush_dns()
    clear_firewall()


def flush_dns() -> None:
    os.system("resolvectl flush-caches >/dev/null 2>&1")


def _ipt_run(binary: str, *args: str, check: bool = False) -> int:
    return subprocess.run(
        [binary, *args],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=check,
    ).returncode


def _ipt_ensure_chain(binary: str) -> None:
    # Create chain if missing, hook into OUTPUT once.
    _ipt_run(binary, "-N", CHAIN)  # ignore "exists"
    if _ipt_run(binary, "-C", "OUTPUT", "-j", CHAIN) != 0:
        _ipt_run(binary, "-I", "OUTPUT", "-j", CHAIN)


def apply_firewall() -> None:
    for binary in ("iptables", "ip6tables"):
        _ipt_ensure_chain(binary)
        _ipt_run(binary, "-F", CHAIN)
        # Drop UDP/443 wholesale — kills QUIC (encrypted SNI), forces TCP fallback.
        _ipt_run(binary, "-A", CHAIN, "-p", "udp", "--dport", "443", "-j", "DROP")
        # Drop TCP/443 packets whose payload contains a target SNI string.
        for pat in SNI_PATTERNS:
            _ipt_run(
                binary, "-A", CHAIN,
                "-p", "tcp", "--dport", "443",
                "-m", "string", "--algo", "bm", "--string", pat,
                "-j", "DROP",
            )


def clear_firewall() -> None:
    for binary in ("iptables", "ip6tables"):
        _ipt_run(binary, "-F", CHAIN)


def hour_start(now: float) -> float:
    lt = time.localtime(now)
    return now - (lt.tm_min * 60 + lt.tm_sec)


def hour_end(now: float) -> float:
    return hour_start(now) + 3600


def used_in_window(now: float) -> int:
    """Sum of session seconds within the current clock hour (clipped)."""
    cutoff = hour_start(now)
    total = 0.0
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text().splitlines():
            try:
                start_s, end_s = line.split()
                start, end = float(start_s), float(end_s)
            except ValueError:
                continue
            if end <= cutoff:
                continue
            total += end - max(start, cutoff)
    # Add any in-progress session.
    if SESSION_START_FILE.exists():
        try:
            start = float(SESSION_START_FILE.read_text().strip())
            total += now - max(start, cutoff)
        except ValueError:
            pass
    return int(total)


def remaining_budget(now: float) -> int:
    return max(0, BUDGET_SECONDS - used_in_window(now))


def record_session(start: float, end: float) -> None:
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with USAGE_LOG.open("a") as f:
        f.write(f"{start:.0f} {end:.0f}\n")


def daemon_kill_existing() -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.1)
            os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    PID_FILE.unlink(missing_ok=True)


def daemon_run(duration: int) -> None:
    """Run inside the forked daemon: sleep, then block."""
    start = time.time()
    SESSION_START_FILE.write_text(f"{start:.0f}")
    PID_FILE.write_text(str(os.getpid()))

    end_time = start + duration

    def finish(*_a):
        actual_end = time.time()
        record_session(start, min(actual_end, end_time))
        SESSION_START_FILE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        PAUSE_UNTIL_FILE.unlink(missing_ok=True)
        write_blocked()
        sys.exit(0)

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)

    while time.time() < end_time:
        time.sleep(min(5, end_time - time.time()))
    finish()


def spawn_daemon(duration: int) -> None:
    """Double-fork a detached child running daemon_run(duration)."""
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        return
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # Grandchild: detach FDs.
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    daemon_run(duration)


def fmt(secs: int) -> str:
    m, s = divmod(secs, 60)
    return f"{m}m{s:02d}s"


def cmd_status() -> None:
    now = time.time()
    used = used_in_window(now)
    remaining = max(0, BUDGET_SECONDS - used)
    blocked = is_blocked()
    active = SESSION_START_FILE.exists()
    print(f"sites:      {'BLOCKED' if blocked else 'OPEN'}")
    reset_in = int(hour_end(now) - now)
    print(f"used:       {fmt(used)} / {fmt(BUDGET_SECONDS)} (this hour)")
    print(f"remaining:  {fmt(remaining)}")
    print(f"resets in:  {fmt(reset_in)}")
    if active:
        try:
            start = float(SESSION_START_FILE.read_text().strip())
            print(f"session:    active for {fmt(int(now - start))}")
        except ValueError:
            pass


def cmd_unblock(requested_minutes: float | None = None) -> None:
    now = time.time()
    if SESSION_START_FILE.exists():
        print("Session already active. Run 'block' to end it.")
        return
    remaining = remaining_budget(now)
    if remaining <= 0:
        wait = int(hour_end(now) - now)
        print(f"No budget left this hour. Resets in {fmt(wait)}.")
        return
    until_hour_end = int(hour_end(now) - now)
    cap = min(remaining, until_hour_end)
    if requested_minutes is None:
        granted = cap
    else:
        if requested_minutes <= 0:
            print("Minutes must be positive.")
            return
        requested = int(requested_minutes * 60)
        granted = min(requested, cap)
        if granted < requested:
            print(f"Requested {fmt(requested)}, but only {fmt(granted)} available.")
    write_unblocked()
    print(f"Unblocked for {fmt(granted)}. Will auto-block when time runs out.")
    spawn_daemon(granted)


def read_pause_until() -> float | None:
    if not PAUSE_UNTIL_FILE.exists():
        return None
    try:
        return float(PAUSE_UNTIL_FILE.read_text().strip())
    except ValueError:
        return None


def cmd_pause(minutes: float) -> None:
    """Open access for an arbitrary duration, ignoring the hourly budget. Survives reboots."""
    if minutes <= 0:
        print("Minutes must be positive.")
        return
    if SESSION_START_FILE.exists():
        print("Session already active. Run 'block' to end it.")
        return
    duration = int(minutes * 60)
    PAUSE_UNTIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_UNTIL_FILE.write_text(f"{time.time() + duration:.0f}")
    write_unblocked()
    print(f"Unblocked for {fmt(duration)} (budget bypassed). Survives reboots.")
    spawn_daemon(duration)


def cmd_init() -> None:
    """Called at boot. Respects an active pause; otherwise blocks."""
    until = read_pause_until()
    now = time.time()
    if until is not None and until > now:
        remaining = int(until - now)
        write_unblocked()
        print(f"Pause active — {fmt(remaining)} remaining.")
        spawn_daemon(remaining)
    else:
        PAUSE_UNTIL_FILE.unlink(missing_ok=True)
        write_blocked()
        print("Blocked.")


def cmd_block() -> None:
    daemon_kill_existing()
    # Give the daemon's SIGTERM handler a moment to record + block; then ensure block.
    time.sleep(0.3)
    PAUSE_UNTIL_FILE.unlink(missing_ok=True)
    write_blocked()
    SESSION_START_FILE.unlink(missing_ok=True)
    print("Blocked.")


def main() -> None:
    require_root()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        cmd_status()
    elif cmd == "unblock":
        minutes = None
        if len(sys.argv) > 2:
            try:
                minutes = float(sys.argv[2])
            except ValueError:
                print(f"invalid minutes: {sys.argv[2]}", file=sys.stderr)
                sys.exit(2)
        cmd_unblock(minutes)
    elif cmd == "block":
        cmd_block()
    elif cmd == "init":
        cmd_init()
    elif cmd == "pause":
        if len(sys.argv) < 3:
            print(f"usage: {sys.argv[0]} pause <minutes>", file=sys.stderr)
            sys.exit(2)
        try:
            minutes = float(sys.argv[2])
        except ValueError:
            print(f"invalid minutes: {sys.argv[2]}", file=sys.stderr)
            sys.exit(2)
        cmd_pause(minutes)
    else:
        print(
            f"usage: {sys.argv[0]} {{status|unblock [minutes]|pause <minutes>|block}}",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
