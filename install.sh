#!/usr/bin/env bash
#
# Install the social-blocker script, the `sblock` wrapper, and the boot service.
# Safe to re-run any time (e.g. after editing blocker.py) — it just overwrites
# the installed copies. Run with: sudo ./install.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Re-running with sudo..."
    exec sudo -- "$0" "$@"
fi

echo "==> Installing /usr/local/bin/social-blocker"
install -m 755 "$REPO_DIR/blocker.py" /usr/local/bin/social-blocker

echo "==> Installing /usr/local/bin/sblock wrapper"
cat > /usr/local/bin/sblock <<'EOF'
#!/usr/bin/env bash
exec sudo /usr/local/bin/social-blocker "$@"
EOF
chmod 755 /usr/local/bin/sblock

echo "==> Installing systemd unit"
install -m 644 "$REPO_DIR/social-blocker.service" /etc/systemd/system/social-blocker.service
systemctl daemon-reload
systemctl enable social-blocker.service

echo "==> Applying block now"
/usr/local/bin/social-blocker init

echo "Done. Try: sblock status"
