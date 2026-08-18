# star-tsp100-telegram-printer

Print Telegram messages and photos on a **Star TSP100 / TSP143 thermal receipt printer**
over the network. Pure Python + Pillow, no futurePRNT driver, no CUPS, no print queue.
Runs on Debian / Raspberry Pi / macOS.

Send your bot a message, it comes out of the printer. Send it a photo, that prints too.

## Why this exists

The TSP100 family — TSP100, TSP100LAN, TSP143, TSP143IIILAN, "futurePRNT" — is a
**raster-only** printer. It does **not** implement ESC/POS or Star Line Mode text.
If you open a socket to port 9100 and send plain text, the printer accepts every byte
and prints nothing. That is why Windows needs the futurePRNT driver: the driver
rasterizes on the PC and ships bitmaps.

This script does the same thing in ~140 lines: renders text with Pillow, dithers it to
1-bit, and sends Star raster rows to port 9100.

## Symptoms this repo solves

If you found this by searching for one of these, you are in the right place:

- **TSP100 accepts data on port 9100 but nothing prints** — it is raster-only, plain text is discarded.
- **Every receipt is exactly the same length (~21cm) no matter the content** — the job is
  missing `ESC * r P '0' NUL`, so the printer ejects its stored default form length.
- **Small print jobs work, larger ones silently vanish** — the printer discards whatever it
  has not consumed when the socket closes. You must wait before closing.
- **Printer is invisible on the network** — it is probably holding a static IP from a previous
  router. Its config is a **telnet server on port 23**, default login `root` / `public`.
- **Text prints as garbage or not at all after a driver install** — again, raster only.

## Install

    git clone https://github.com/seanlabor/star-tsp100-telegram-printer
    cd star-tsp100-telegram-printer
    python3 -m venv .venv
    .venv/bin/pip install pillow

Debian also needs a monospace font: `sudo apt install fonts-dejavu-core`.

## Run

    export TELEGRAM_TOKEN=...      # from @BotFather
    export TELEGRAM_ALLOWED=...    # your Telegram user ID, from @userinfobot
    export PRINTER_HOST=192.168.1.50
    .venv/bin/python print_bot.py

Only user IDs in `TELEGRAM_ALLOWED` can print. Everyone else is ignored.

| Flag | What it does |
|------|--------------|
| `--selftest` | Assertions only, prints nothing |
| `--test-print` | One test receipt |
| `--image FILE` | Print any image file |
| `--diagnose` | Bot identity, webhook status, pending updates |

## Printing pictures

    .venv/bin/python print_bot.py --image examples/donkey.png

Or just send the photo to your bot. Images are composited onto white (so transparent
PNGs print as blank paper, not a black block), autocontrasted, scaled to the full
576-dot width, and Floyd-Steinberg dithered — which is what makes a photo readable on
a 1-bit thermal head.

![example: dithered for a 1-bit thermal head](examples/donkey-dithered.png)

Captions print above the image. Images taller than `PRINTER_MAX_MM` are scaled down to
fit rather than unrolling the whole roll.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `TELEGRAM_TOKEN` | — | Bot token from @BotFather |
| `TELEGRAM_ALLOWED` | — | Comma-separated Telegram user IDs allowed to print |
| `PRINTER_HOST` | `192.168.1.50` | Printer IP |
| `PRINTER_PORT` | `9100` | Raw print port |
| `PRINTER_FONT` | auto | Menlo on macOS, DejaVu Sans Mono on Debian |
| `PRINTER_FONT_SIZE` | `24` | Column count follows automatically (24pt = 41 cols on 80mm) |
| `PRINTER_MARGIN_MM` | `20` | Blank paper after each receipt |
| `PRINTER_MAX_MM` | `200` | Tall images are scaled to fit rather than unrolling the roll |
| `PRINTER_FEED` | `0` | Extra feed lines before the cut, if the last line is clipped |

## Finding and configuring the printer

The printer's network config lives in a **telnet utility on port 23**:

    telnet <printer-ip>
    # login root / password public   <- change this

`1) IP Parameters` -> `2) Dynamic` -> enable DHCP -> `98) Save & Restart`.

If you cannot reach the printer at all, it is likely on a different subnet with a static
IP left over from another router. Its MAC starts with `00:11:62` (Star Micronics), so you
can find it in your router's DHCP client list, or by holding **FEED** while powering the
printer on — the self-test slip prints its IP, subnet, and MAC.

## Run as a service (Debian)

    sudo mkdir -p /opt/telegram-printer
    sudo cp print_bot.py /opt/telegram-printer/
    sudo python3 -m venv /opt/telegram-printer/.venv
    sudo /opt/telegram-printer/.venv/bin/pip install pillow

    sudo tee /etc/telegram-printer.env >/dev/null <<'EOF'
    TELEGRAM_TOKEN=...
    TELEGRAM_ALLOWED=...
    PRINTER_HOST=192.168.1.50
    EOF
    sudo chmod 600 /etc/telegram-printer.env

    sudo cp telegram-printer.service /etc/systemd/system/
    sudo systemctl enable --now telegram-printer
    journalctl -u telegram-printer -f

`EnvironmentFile` takes bare `KEY=value` lines — no `export`, no quotes.

## Protocol notes

Job structure sent to port 9100:

    ESC @            initialise
    ESC * r A        enter raster mode
    ESC * r P '0'    page length 0 = continuous   <- omit this and every receipt is 21cm
    b <nL> <nH> ...  one raster row, 72 bytes for 80mm paper at 203dpi
    ESC FF NUL       form feed
    ESC * r B        leave raster mode
    ESC d 3          cut

203 dpi = 8 dots/mm, 576 dots across on 80mm paper. Bit set = ink, which is the inverse
of Pillow's 1-bit convention, so the packed rows are inverted.

The ~20mm blank strip at the top of every receipt is the physical gap between the print
head and the cutter. It cannot be removed in software.

## Licence

MIT
