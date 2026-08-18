# star-tsp100-telegram-printer

Print Telegram messages and photos on a **Star TSP100 / TSP143 thermal receipt printer**
over the network. The bot needs Python and Pillow. It does not need the futurePRNT
driver, CUPS, or a print queue. It runs on Debian, Raspberry Pi, and macOS.

Send a message to your bot. The printer prints it. Send a photo to your bot. The printer
prints that too.

## Why this exists

The TSP100 family — TSP100, TSP100LAN, TSP143, TSP143IIILAN, "futurePRNT" — is a
**raster-only** printer. It does **not** implement ESC/POS or Star Line Mode text.
If you open a socket to port 9100 and send plain text, the printer accepts every byte
and prints nothing. Windows therefore needs the futurePRNT driver. That driver
rasterizes the page on the PC and sends bitmaps.

This script does the same work in about 140 lines. It renders text with Pillow. It
dithers the result to 1 bit. It sends Star raster rows to port 9100.

## Symptoms this repo solves

If you found this by searching for one of these, you are in the right place:

- **TSP100 accepts data on port 9100 but nothing prints** — the printer is raster-only.
  It discards plain text.
- **Every receipt is exactly the same length (~21cm) no matter the content** — the job
  does not contain `ESC * r P '0' NUL`. The printer therefore ejects its stored default
  form length.
- **Small print jobs work, larger ones silently vanish** — the printer discards the data
  it has not consumed when the socket closes. You must wait before you close the socket.
- **Printer is invisible on the network** — the printer probably holds a static IP
  address from a previous router. Its configuration is a **telnet server on port 23**.
  The default login is `root` / `public`.
- **Text prints as garbage or not at all after a driver install** — the printer is
  raster-only.

## Install

    git clone https://github.com/seanlabor/star-tsp100-telegram-printer
    cd star-tsp100-telegram-printer
    python3 -m venv .venv
    .venv/bin/pip install pillow

Debian also needs a monospace font. Install one with `sudo apt install fonts-dejavu-core`.

## Run

    export TELEGRAM_TOKEN=...      # from @BotFather
    export TELEGRAM_ALLOWED=...    # your Telegram user ID, from @userinfobot
    export PRINTER_HOST=192.168.1.50
    .venv/bin/python print_bot.py

Only the user IDs in `TELEGRAM_ALLOWED` can print. The bot ignores every other user.

| Flag | What it does |
|------|--------------|
| `--selftest` | Runs assertions only. Prints nothing. |
| `--test-print` | Prints one test receipt. |
| `--image FILE` | Prints any image file. |
| `--diagnose` | Shows the bot identity, the webhook status, and pending updates. |

## Printing pictures

    .venv/bin/python print_bot.py --image examples/donkey.png

Or send the photo to your bot. The bot processes each image in four steps:

1. It composites the image onto white. A transparent PNG then prints as blank paper,
   not as a black block.
2. It applies autocontrast.
3. It scales the image to the full 576-dot width.
4. It applies Floyd-Steinberg dithering. This step makes a photo readable on a 1-bit
   thermal head.

![example: dithered for a 1-bit thermal head](examples/donkey-dithered.png)

The bot prints the caption above the image. If an image is taller than `PRINTER_MAX_MM`,
the bot scales the image to fit. This keeps the bot from unrolling the whole paper roll.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `TELEGRAM_TOKEN` | — | Bot token from @BotFather |
| `TELEGRAM_ALLOWED` | — | Telegram user IDs that can print, separated by commas |
| `PRINTER_HOST` | `192.168.1.50` | Printer IP address |
| `PRINTER_PORT` | `9100` | Raw print port |
| `PRINTER_FONT` | auto | Menlo on macOS, DejaVu Sans Mono on Debian |
| `PRINTER_FONT_SIZE` | `24` | The column count follows. 24 pt gives 41 columns on 80 mm paper. |
| `PRINTER_MARGIN_MM` | `20` | Blank paper after each receipt |
| `PRINTER_MAX_MM` | `200` | The bot scales taller images to fit |
| `PRINTER_FEED` | `0` | Extra feed lines before the cut. Raise this if the last line is clipped. |

### Fonts

`fonts/Cabin-Regular.ttf` ships with this repository under the SIL Open Font License.
See `fonts/OFL.txt`. Cabin is drawn after Eric Gill's and Edward Johnston's work.

The ticket design was drawn in Gill Sans Nova. Monotype licenses that font, so this
repository cannot redistribute it. You can get it in two ways:

- Microsoft 365 installs Gill Sans Nova together with Office.
- Monotype sells it at [myfonts.com](https://www.myfonts.com) and
  [fonts.com](https://www.fonts.com).

Point `PRINTER_FONT` at your own copy to use it:

    export PRINTER_FONT="/path/to/Gill Sans Nova Light.ttf"

## Finding and configuring the printer

The printer keeps its network configuration in a **telnet utility on port 23**:

    telnet <printer-ip>
    # login root / password public   <- change this

`1) IP Parameters` -> `2) Dynamic` -> enable DHCP -> `98) Save & Restart`.

If you cannot reach the printer, it is probably on a different subnet. It probably holds
a static IP address from another router. Its MAC address starts with `00:11:62`, which
belongs to Star Micronics. You can find the printer in two ways:

- Look in your router's DHCP client list.
- Hold **FEED** and switch the printer on. The self-test slip shows the IP address, the
  subnet, and the MAC address.

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

`EnvironmentFile` takes bare `KEY=value` lines. Do not use `export`. Do not use quotes.

## Protocol notes

The bot sends this job structure to port 9100:

    ESC @            initialise
    ESC * r A        enter raster mode
    ESC * r P '0'    page length 0 = continuous   <- omit this and every receipt is 21cm
    b <nL> <nH> ...  one raster row, 72 bytes for 80mm paper at 203dpi
    ESC FF NUL       form feed
    ESC * r B        leave raster mode
    ESC d 3          cut

203 dpi gives 8 dots/mm, and 576 dots across 80 mm paper. A set bit means ink. This is
the inverse of Pillow's 1-bit convention, so the code inverts the packed rows.

Every receipt starts with a blank strip about 20 mm long. This is the physical gap
between the print head and the cutter. You cannot remove it in software.

## Licence

MIT
