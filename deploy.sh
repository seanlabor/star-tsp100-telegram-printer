#!/usr/bin/env bash
# Deploy print_bot.py to a Debian host over SSH. Safe to re-run: this is the
# redeploy path after a code change, not just the first install.
#
#   ./deploy.sh crawler@192.168.1.240
#   PRINT_BOT_TARGET=crawler@192.168.1.240 ./deploy.sh
#
# The target needs passwordless sudo. If sudo asks for a password, run the
# script through a TTY instead:  ssh -t "$TARGET" ... (or configure NOPASSWD).
#
# What it will never do: overwrite /etc/telegram-printer.env. That file holds
# the bot token, so it is created once with empty values and left alone after.
set -euo pipefail

DEST=/opt/telegram-printer
UNIT=telegram-printer.service

usage() { echo "usage: $0 [user@host]" >&2; exit 2; }
case "${1:-}" in -h|--help) usage ;; esac
TARGET="${1:-${PRINT_BOT_TARGET:-}}"
[ -n "$TARGET" ] || usage

cd "$(dirname "$0")"
for f in print_bot.py "$UNIT" fonts/Cabin-Regular.ttf fonts/OFL.txt; do
    [ -f "$f" ] || { echo "missing $f -- run this from the repository root" >&2; exit 1; }
done

echo "==> shipping code and font to $TARGET:$DEST"
tar czf - print_bot.py "$UNIT" fonts/ |
    ssh "$TARGET" "sudo mkdir -p $DEST && sudo tar xzf - -C $DEST"

echo "==> installing on $TARGET"
ssh "$TARGET" "DEST=$DEST bash -s" <<'REMOTE'
set -euo pipefail
ENVFILE=/etc/telegram-printer.env

# Debian 12+ refuses a system-wide pip install (PEP 668), so the bot gets its
# own virtualenv. Created once, then only refreshed.
if [ ! -x "$DEST/.venv/bin/python" ]; then
    python3 -c 'import ensurepip' 2>/dev/null ||
        { echo "python3-venv is missing: sudo apt install python3-venv" >&2; exit 1; }
    sudo python3 -m venv "$DEST/.venv"
fi
sudo "$DEST/.venv/bin/pip" install --quiet --disable-pip-version-check --upgrade pillow

# The config holds a credential. Create it empty once; never touch it again.
if [ ! -f "$ENVFILE" ]; then
    sudo tee "$ENVFILE" >/dev/null <<'EOF'
TELEGRAM_TOKEN=
TELEGRAM_ALLOWED=
PRINTER_HOST=192.168.1.50
EOF
    sudo chmod 600 "$ENVFILE"
    echo "    created $ENVFILE (empty)"
fi

sudo install -m 644 "$DEST/telegram-printer.service" /etc/systemd/system/
sudo systemctl daemon-reload

# Gate: never restart the service onto code that fails its own self-test. If
# this exits non-zero the running service is left alone on its old code, and
# the new code sits on disk unused until the next successful deploy.
echo "==> self-test"
sudo "$DEST/.venv/bin/python" "$DEST/print_bot.py" --selftest

sudo systemctl enable --quiet telegram-printer

# Starting without a token means a crash loop every RestartSec, so check first.
if sudo grep -qE '^TELEGRAM_TOKEN=.+' "$ENVFILE" &&
   sudo grep -qE '^TELEGRAM_ALLOWED=.+' "$ENVFILE"; then
    sudo systemctl restart telegram-printer
    sleep 2
    systemctl is-active --quiet telegram-printer &&
        echo "==> running: $(systemctl show -p ActiveState --value telegram-printer)" ||
        { echo "==> FAILED to stay up, last log lines:" >&2
          journalctl -u telegram-printer -n 15 --no-pager >&2; exit 1; }
else
    echo "==> enabled for boot, NOT started"
    echo "    TELEGRAM_TOKEN or TELEGRAM_ALLOWED is empty in $ENVFILE."
    echo "    Fill it in, then: sudo systemctl start telegram-printer"
fi
REMOTE

echo "==> done. Logs: ssh $TARGET 'journalctl -u telegram-printer -f'"
