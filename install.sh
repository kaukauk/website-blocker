#!/usr/bin/env bash
#
# Install the social-blocker script, the `sblock` wrapper, and the watchdog service.
# Safe to re-run any time — it temporarily unlocks files and overwrites them.
# Run with: sudo ./install.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Re-running with sudo..."
    exec sudo -- "$0" "$@"
fi

# Unlock any previously immutable files
echo "==> Unlocking target paths"
chattr -i /usr/local/bin/social-blocker /usr/local/bin/sblock /etc/systemd/system/social-blocker.service 2>/dev/null || true

echo "==> Installing /usr/local/bin/social-blocker"
install -m 755 "$REPO_DIR/blocker.py" /usr/local/bin/social-blocker

echo "==> Installing /usr/local/bin/sblock wrapper"
cat > /usr/local/bin/sblock <<'EOF'
#!/usr/bin/env bash
exec sudo /usr/local/bin/social-blocker "$@"
EOF
chmod 755 /usr/local/bin/sblock

# Clean up any legacy pause files
rm -f /var/lib/social-blocker/pause_until 2>/dev/null || true

echo "==> Configuring sudoers for sblock"
cat > /etc/sudoers.d/social-blocker <<'EOF'
ALL ALL=(root) NOPASSWD: /usr/local/bin/social-blocker status, /usr/local/bin/social-blocker block, /usr/local/bin/social-blocker unblock, /usr/local/bin/social-blocker unblock *
EOF
chmod 440 /etc/sudoers.d/social-blocker

echo "==> Installing systemd watchdog service"
install -m 644 "$REPO_DIR/social-blocker.service" /etc/systemd/system/social-blocker.service
systemctl daemon-reload
systemctl enable social-blocker.service
if systemctl is-active --quiet social-blocker.service; then
    systemctl kill -s SIGTERM social-blocker.service
else
    systemctl start social-blocker.service
fi

echo "==> Applying initial block"
/usr/local/bin/social-blocker init

echo "==> Locking files with immutability (+i)"
chattr +i /usr/local/bin/social-blocker /usr/local/bin/sblock /etc/systemd/system/social-blocker.service 2>/dev/null || true

echo "Done. Try: sblock status"
