# social-blocker

A self-hosted blocker for distracting sites (YouTube, Instagram, Facebook,
Snapchat, Reddit). It blocks at two layers and gives you a small **rolling
time budget per clock hour** so you can take a quick look without losing the
whole afternoon.

- **DNS layer** — adds `0.0.0.0` entries to `/etc/hosts` for each site.
- **Firewall layer** — `iptables`/`ip6tables` rules that drop UDP/443 (kills
  QUIC) and drop TCP/443 packets whose TLS SNI matches a blocked domain or its
  CDN. This catches traffic that bypasses `/etc/hosts` (apps, hardcoded DNS).
- **Self-healing watchdog service** — a persistent background systemd service
  monitors DNS and firewall rules every 5 seconds, auto-restoring the block if
  rules or hosts are tampered with.

> **Platform:** Linux with `systemd`, `iptables`/`ip6tables`, and
> `resolvectl` (systemd-resolved). Requires root (the commands self-`sudo`).

---

## Install

From this folder:

```bash
sudo ./install.sh
```

That script:

1. copies `blocker.py` → `/usr/local/bin/social-blocker`
2. installs the `sblock` convenience wrapper → `/usr/local/bin/sblock`
3. installs + enables the persistent watchdog service (`social-blocker.service`)
4. applies the block immediately
5. sets up filesystem immutability and AI agent safety guardrails

The installed service is **completely independent of this folder** — once installed,
the repository can be removed so the blocker lives entirely as a protected background system service.

---

## Usage

Use the `sblock` wrapper from anywhere (it handles `sudo` for you):

```bash
sblock status            # show block state, budget used/remaining, reset time
sblock unblock           # open sites for ALL remaining budget this hour
sblock unblock 3         # open for 3 minutes (capped by remaining budget)
sblock block             # re-block immediately and end any open session
```

Equivalent without the wrapper: `sudo social-blocker <command>`.

### How the time budget works

- You get **5 minutes of access per clock hour** (`BUDGET_SECONDS = 300`).
- The budget resets at the top of each hour (e.g. 2:00, 3:00).
- `unblock` opens the sites and starts a background daemon that **auto-blocks**
  again when your granted time runs out (or when the hour ends, whichever is
  first).
- The background daemon enforces this limit: if the unblock session ends or exceeds
  the budget, sites are immediately re-blocked.

### Example

```
$ sblock status
sites:      BLOCKED
used:       0m00s / 5m00s (this hour)
remaining:  5m00s
resets in:  41m12s

$ sblock unblock 2
Unblocked for 2m00s. Will auto-block when time runs out.
```

---

## Configuration

- **`SITES`** — domains written into `/etc/hosts`.
- **`SNI_PATTERNS`** — substrings matched in TLS ClientHello (domains + CDNs).
- **`BUDGET_SECONDS`** — per-hour budget in seconds (default `300` = 5 min).

---

## How it works under the hood

| Path | Purpose |
|------|---------|
| `/usr/local/bin/social-blocker` | the installed script |
| `/usr/local/bin/sblock` | wrapper that runs the script via `sudo` |
| `/etc/systemd/system/social-blocker.service` | persistent self-healing watchdog daemon |
| `/etc/hosts` (between `# >>> social-blocker >>>` markers) | DNS block |
| `iptables` chain `SOCIAL_BLOCKER` | firewall block (re-checked continuously) |
| `/var/lib/social-blocker/` | runtime state (usage log, session start/pid) |

### Commands

| Command | What it does |
|---------|--------------|
| `daemon` | Background watchdog daemon running continuously under systemd. |
| `status` | Print block state and budget. |
| `unblock [min]` | Open sites within the hourly budget; auto-block on expiry. |
| `block` | Re-block now; kill any active session. |
| `init` | Immediate block enforcer. |

---

## Maintenance & Updates

To modify or update the installed script if immutability (`chattr +i`) is enabled:

```bash
# Temporarily allow edits:
sudo chattr -i /usr/local/bin/social-blocker /usr/local/bin/sblock /etc/systemd/system/social-blocker.service

# Make changes / re-run install:
sudo ./install.sh

# Re-lock:
sudo chattr +i /usr/local/bin/social-blocker /usr/local/bin/sblock /etc/systemd/system/social-blocker.service
```
