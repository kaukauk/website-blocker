# social-blocker

A self-hosted blocker for distracting sites (YouTube, Instagram, Facebook,
Snapchat, Reddit). It blocks at two layers and gives you a small **rolling
time budget per clock hour** so you can take a quick look without losing the
whole afternoon.

- **DNS layer** — adds `0.0.0.0` entries to `/etc/hosts` for each site.
- **Firewall layer** — `iptables`/`ip6tables` rules that drop UDP/443 (kills
  QUIC) and drop TCP/443 packets whose TLS SNI matches a blocked domain or its
  CDN. This catches traffic that bypasses `/etc/hosts` (apps, hardcoded DNS).

The block is re-applied automatically at every boot via a systemd service.

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
3. installs + enables the boot service (`social-blocker.service`)
4. applies the block immediately

The installed copies are **independent of this folder** — once installed you
can move, rename, or delete this repo without breaking anything.

### Updating after you edit `blocker.py`

The system runs the installed *copy*, not the file in this folder. After
editing, re-run the installer to push your changes:

```bash
sudo ./install.sh
```

---

## Usage

Use the `sblock` wrapper from anywhere (it handles `sudo` for you):

```bash
sblock status            # show block state, budget used/remaining, reset time
sblock unblock           # open sites for ALL remaining budget this hour
sblock unblock 3         # open for 3 minutes (capped by remaining budget)
sblock pause 60          # open for 60 min, IGNORING the budget (survives reboot)
sblock block             # re-block immediately and end any open session
```

Equivalent without the wrapper: `sudo social-blocker <command>`.

### How the time budget works

- You get **5 minutes of access per clock hour** (`BUDGET_SECONDS = 300`).
- The budget resets at the top of each hour (e.g. 2:00, 3:00).
- `unblock` opens the sites and starts a background daemon that **auto-blocks**
  again when your granted time runs out (or when the hour ends, whichever is
  first).
- `pause <minutes>` is the escape hatch: it opens access for an arbitrary
  duration and **ignores the hourly budget**. It also persists across reboots —
  if you reboot mid-pause, the boot service honours the remaining pause time
  instead of re-blocking.

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

Edit `blocker.py`, then re-run `sudo ./install.sh`.

- **`SITES`** — domains written into `/etc/hosts`.
- **`SNI_PATTERNS`** — substrings matched in TLS ClientHello (domains + CDNs).
- **`BUDGET_SECONDS`** — per-hour budget in seconds (default `300` = 5 min).

---

## How it works under the hood

| Path | Purpose |
|------|---------|
| `/usr/local/bin/social-blocker` | the installed script |
| `/usr/local/bin/sblock` | wrapper that runs the script via `sudo` |
| `/etc/systemd/system/social-blocker.service` | re-blocks at boot (`init`) |
| `/etc/hosts` (between `# >>> social-blocker >>>` markers) | DNS block |
| `iptables` chain `SOCIAL_BLOCKER` | firewall block (rebuilt each `init`) |
| `/var/lib/social-blocker/` | runtime state (usage log, pid, pause file) |

The `iptables` rules live in kernel memory and are **not** persisted across
reboots — that's intentional. The boot service re-applies them every time it
runs `init`, so there's no dependency on an iptables-save mechanism.

### Commands

| Command | What it does |
|---------|--------------|
| `init` | Boot entrypoint. Honours an active `pause`, otherwise blocks. |
| `status` | Print block state and budget. |
| `unblock [min]` | Open sites within the hourly budget; auto-block on expiry. |
| `pause <min>` | Open sites ignoring the budget; survives reboots. |
| `block` | Re-block now; kill any active session. |

---

## Uninstall

```bash
sudo social-blocker block                       # ensure sites are blocked/clean state
sudo systemctl disable --now social-blocker.service
sudo rm /etc/systemd/system/social-blocker.service
sudo systemctl daemon-reload
sudo rm /usr/local/bin/social-blocker /usr/local/bin/sblock
sudo rm -rf /var/lib/social-blocker
```

`social-blocker block` rewrites `/etc/hosts` without the managed block and
flushes the firewall chain, so removing the files afterwards leaves a clean
system.
