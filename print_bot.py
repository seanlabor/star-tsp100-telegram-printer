#!/usr/bin/env python3
"""Print Telegram messages on a Star TSP143 (TSP100 futurePRNT) over port 9100.

The TSP100 family is raster-only: it ignores ESC/POS and Star Line Mode text,
so every message is rendered to a 1-bit bitmap and sent as Star raster data.

Env:
  TELEGRAM_TOKEN     bot token from @BotFather           (required)
  TELEGRAM_ALLOWED   comma-separated Telegram user IDs   (required)
  PRINTER_HOST       default 192.168.1.50
  PRINTER_PORT       default 9100
  PRINTER_FONT       default /System/Library/Fonts/Menlo.ttc
  PRINTER_FONT_SIZE  default 24

Usage: print_bot.py [--selftest | --test-print | --diagnose]
"""
import io, json, os, socket, sys, textwrap, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps

API = "https://api.telegram.org/bot{}/{}"
DOTS = 576                      # 80mm paper at 203dpi
STRIDE = DOTS // 8
# ESC @ init, ESC * r A enter raster, ESC * r P '0' NUL = page length 0 = continuous.
# Without the page-length command the printer ejects its stored default form (21cm!)
# on every job, whatever the content. The '0' is ASCII 0x30, not an integer 0.
RASTER_ON = b"\x1b@" b"\x1b*rA" b"\x1b*rP0\x00"
RASTER_OFF = b"\x1b\x0c\x00" b"\x1b*rB"      # ESC FF NUL form feed, then leave raster mode
# ponytail: ESC d 3 already feeds to the cutter. Extra feed lines are pure waste —
# raise PRINTER_FEED only if the last line comes out clipped.
CUT = b"\n" * int(os.environ.get("PRINTER_FEED", "0")) + b"\x1bd\x03"

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ALLOWED = {int(x) for x in os.environ.get("TELEGRAM_ALLOWED", "").replace(",", " ").split()}
HOST = os.environ.get("PRINTER_HOST", "192.168.1.50")
PORT = int(os.environ.get("PRINTER_PORT", "9100"))

# first monospace face that exists; macOS then Debian. PRINTER_FONT overrides.
FONTS = [os.environ.get("PRINTER_FONT", ""),
         "/System/Library/Fonts/Menlo.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]
FONT_PATH = next((f for f in FONTS if f and os.path.exists(f)), None)
if FONT_PATH is None:
    sys.exit(f"no monospace font found, tried {FONTS[1:]} - "
             f"apt install fonts-dejavu-core, or set PRINTER_FONT")
# ponytail: knob for paper width / legibility — bump the size and COLS follows
FONT = ImageFont.truetype(FONT_PATH, int(os.environ.get("PRINTER_FONT_SIZE", "24")))
COLS = int(DOTS // FONT.getlength("M"))
LINE_H = FONT.size + 2
PAD = 2
# bottom margin so the last line is not flush with the cut, in mm (203dpi = 8 dots/mm)
MARGIN = int(os.environ.get("PRINTER_MARGIN_MM", "20")) * 8
# a panorama would otherwise unroll metres of paper; scale it down to fit instead
MAX_DOTS = int(os.environ.get("PRINTER_MAX_MM", "200")) * 8


def render(text, when):
    body = "\n".join(
        line
        for para in text.split("\n")
        for line in (textwrap.wrap(para, COLS) or [""])
    )
    return f"{when.strftime('%a %d %b  %H:%M')}\n{'-' * COLS}\n{body}"


def pack(img):
    """1-bit image -> Star raster rows. Bit set = ink, so invert PIL's white=1."""
    raw = img.tobytes()                    # MSB first, bit set = white
    out = bytearray()
    for y in range(img.height):
        row = raw[y * STRIDE:(y + 1) * STRIDE]
        out += b"\x62" + bytes([STRIDE, 0]) + bytes(255 - b for b in row)   # invert
    return bytes(out)


def rasterize(payload, margin=MARGIN):
    lines = payload.split("\n")
    img = Image.new("1", (DOTS, LINE_H * len(lines) + PAD + margin), 1)    # 1 = white
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((0, i * LINE_H), line, font=FONT, fill=0)
    return pack(img)


def rasterize_image(path, margin=MARGIN):
    src = Image.open(path).convert("RGBA")
    # composite onto white: a transparent background must print as blank paper,
    # not as the solid black block RGBA->L would otherwise give
    flat = Image.alpha_composite(Image.new("RGBA", src.size, "WHITE"), src).convert("L")
    flat = ImageOps.autocontrast(flat)
    w, h = DOTS, round(flat.height * DOTS / flat.width)
    if h > MAX_DOTS:                               # too tall: fit the height, centre it
        w, h = round(flat.width * MAX_DOTS / flat.height), MAX_DOTS
    flat = flat.resize((w, h), Image.LANCZOS)
    page = Image.new("1", (DOTS, h + margin), 1)
    page.paste(flat.convert("1"), ((DOTS - w) // 2, 0))   # convert("1") = Floyd-Steinberg
    return pack(page)


def emit_image(src, caption=None, when=None):
    rows = rasterize(render(caption, when or datetime.now()), margin=8) if caption else b""
    rows += rasterize_image(src)
    send(RASTER_ON + rows + RASTER_OFF + CUT, wait=15)


def download(file_id):
    info = api("getFile", _timeout=20, file_id=file_id)["result"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return io.BytesIO(r.read())


def send(job, wait=None):
    with socket.create_connection((HOST, PORT), timeout=60) as s:
        s.sendall(job)
        # ponytail: the TSP143 drops whatever it has not consumed when the socket closes,
        # which silently loses any job over ~5KB. Prints at roughly 90KB/s; the 2s floor
        # covers short jobs. Raise the divisor if long messages ever come out truncated.
        time.sleep(wait if wait else max(2.0, len(job) / 50_000))


def emit(text, when=None):
    send(RASTER_ON + rasterize(render(text, when or datetime.now())) + RASTER_OFF + CUT)


# leading underscore: "timeout" is also a getUpdates parameter and must reach **params
def api(method, _timeout=40, **params):
    url = API.format(TOKEN, method) + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=_timeout) as r:
        return json.load(r)


def main():
    if not TOKEN or not ALLOWED:
        sys.exit("set TELEGRAM_TOKEN and TELEGRAM_ALLOWED")
    print(f"printing to {HOST}:{PORT} at {COLS} cols for {sorted(ALLOWED)}", file=sys.stderr)
    offset = 0
    while True:
        try:
            updates = api("getUpdates", offset=offset, timeout=30)["result"]
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):               # bad token: retrying cannot fix it
                sys.exit(f"telegram rejected the token ({e.code}) - "
                         f"check TELEGRAM_TOKEN, it ends ...{TOKEN[-6:]!r}")
            print("telegram:", e, file=sys.stderr)
            time.sleep(5)
            continue
        except Exception as e:                     # network blip, bad gateway, ...
            print("telegram:", e, file=sys.stderr)
            time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1          # only advance once fetched
            msg = upd.get("message") or {}
            text, sender = msg.get("text"), msg.get("from", {}).get("id")
            photo, doc = msg.get("photo") or [], msg.get("document") or {}
            # phone photos arrive as "photo" (largest last); desktop "send as file" as document
            file_id = (photo[-1]["file_id"] if photo
                       else doc.get("file_id")
                       if doc.get("mime_type", "").startswith("image/") else None)
            if sender not in ALLOWED or not (text or file_id):
                # silence here is why a dropped message looks like a broken printer
                print(f"skip: from={sender} allowed={sorted(ALLOWED)} keys={sorted(msg)}",
                      file=sys.stderr)
                continue
            try:
                if file_id:
                    print(f"print: image from={sender}", file=sys.stderr)
                    emit_image(download(file_id), msg.get("caption"))
                else:
                    print(f"print: from={sender} {len(text)} chars", file=sys.stderr)
                    emit(text)
            except OSError as e:                   # printer off, out of paper, unplugged
                print("printer:", e, file=sys.stderr)
                try:
                    api("sendMessage", _timeout=10, chat_id=msg["chat"]["id"],
                        text=f"could not print: {e}")
                except Exception:
                    pass


def diagnose():
    print("getMe       :", json.dumps(api("getMe", _timeout=10))[:300])
    print("webhookInfo :", json.dumps(api("getWebhookInfo", _timeout=10))[:300])
    print("pending     :", json.dumps(api("getUpdates", _timeout=10))[:2000])


def selftest():
    when = datetime(2026, 8, 18, 9, 5)
    assert render("hallo", when).startswith("Tue 18 Aug  09:05\n" + "-" * COLS + "\n")
    # a message must never overflow the paper, however it was typed
    assert all(len(l) <= COLS for l in render("x " * 200, when).splitlines())
    # blank lines are how people space a note; keep the shape they sent
    assert render("a\n\nb", when).endswith("a\n\nb")
    # a trailing blank line is 3mm of paper per receipt, every receipt
    assert not render("hi", when).endswith("\n")
    # the long-poll timeout must reach Telegram, not urlopen, or this busy-loops into a 429
    import inspect
    assert "timeout" not in inspect.signature(api).parameters
    # every raster row must carry the exact header the printer expects, or it prints nothing
    rows = rasterize("hi")
    assert len(rows) % (STRIDE + 3) == 0
    # the bottom margin must actually reach the paper, not just the bitmap
    assert len(rows) // (STRIDE + 3) >= MARGIN
    # a caption must not drag its own margin into the middle of the receipt
    assert len(rasterize("hi", margin=0)) < len(rows)
    assert all(rows[i] == 0x62 and rows[i + 1] == STRIDE
               for i in range(0, len(rows), STRIDE + 3))
    # ink is bit-set: an all-white page must be all-zero bits
    blank = rasterize(" ")
    assert not any(blank[i + 3:i + 3 + STRIDE].strip(b"\x00")
                   for i in range(0, len(blank), STRIDE + 3))
    print(f"ok ({COLS} cols)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--diagnose":
        diagnose()
    elif arg == "--selftest":
        selftest()
    elif arg == "--image":
        rows = rasterize_image(sys.argv[2])
        # dense photos print far slower than text, so wait generously before closing
        send(RASTER_ON + rows + RASTER_OFF + CUT, wait=15)
        print(f"sent {len(rows)//(STRIDE+3)/8:.0f}mm of image")
    elif arg == "--test-print":
        emit("test print\nUmlaute: äöüß\nlange zeile " + "abcdefghij " * 8)
    else:
        main()
