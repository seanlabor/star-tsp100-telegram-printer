#!/usr/bin/env python3
"""Print Telegram messages on a Star TSP143 (TSP100 futurePRNT) over port 9100.

The TSP100 family is raster-only. It ignores ESC/POS text and Star Line Mode
text. The bot therefore renders every message to a 1-bit bitmap. It sends that
bitmap to the printer as Star raster data.

Env:
  TELEGRAM_TOKEN     bot token from @BotFather           (required)
  TELEGRAM_ALLOWED   comma-separated Telegram user IDs   (required)
  PRINTER_HOST       default 192.168.1.50
  PRINTER_PORT       default 9100
  PRINTER_FONT       default fonts/Cabin-Regular.ttf next to this script
  PRINTER_FONT_SIZE  body size in points, default 32; title and footer follow

Usage: print_bot.py [--selftest | --test-print | --image FILE | --diagnose]
"""
import io, json, os, socket, sys, time
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

# The ticket layout is proportional, so the bundled Cabin comes first. The
# monospace faces remain as a fallback for a checkout without fonts/.
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = [os.environ.get("PRINTER_FONT", ""),
         os.path.join(HERE, "fonts", "Cabin-Regular.ttf"),
         "/usr/local/share/fonts/Cabin-Regular.ttf",
         "/System/Library/Fonts/Menlo.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]
FONT_PATH = next((f for f in FONTS if f and os.path.exists(f)), None)
if FONT_PATH is None:
    sys.exit(f"No font found. The bot tried these paths: {FONTS[1:]}. "
             f"Restore fonts/Cabin-Regular.ttf from the repository. "
             f"Or set PRINTER_FONT to the path of a font file.")
# one knob: the body size. The title and the footer are derived from it.
BODY_PT = int(os.environ.get("PRINTER_FONT_SIZE", "32"))
TITLE_PT = round(BODY_PT * 1.5)
META_PT = round(BODY_PT * 0.75)
BODY = ImageFont.truetype(FONT_PATH, BODY_PT)
TITLE = ImageFont.truetype(FONT_PATH, TITLE_PT)
META = ImageFont.truetype(FONT_PATH, META_PT)
BODY_H = round(BODY_PT * 1.25)          # line pitch, not glyph height
TITLE_H = round(TITLE_PT * 1.25)
META_H = round(META_PT * 1.4)
PAD = 8                                 # left and right margin, in dots
USABLE = DOTS - 2 * PAD
RULE = 4                                # thickness of the rule under the title
GAP = 20                                # blank dots above and below the rule
# bottom margin so the last line is not flush with the cut, in mm (203dpi = 8 dots/mm)
MARGIN = int(os.environ.get("PRINTER_MARGIN_MM", "20")) * 8
# a panorama would otherwise unroll metres of paper; scale it down to fit instead
MAX_DOTS = int(os.environ.get("PRINTER_MAX_MM", "200")) * 8


def wrap_px(text, font, max_px=USABLE):
    """Wrap on measured width. A character count means nothing on a proportional face."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if font.getlength(trial) <= max_px:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while font.getlength(word) > max_px:      # one word wider than the paper
            n = 1
            while n < len(word) and font.getlength(word[:n + 1] + "-") <= max_px:
                n += 1
            lines.append(word[:n] + "-")
            word = word[n:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def layout(message):
    """message -> (title lines, body lines). The first line is the title."""
    head, _, rest = message.partition("\n")
    title = wrap_px(head, TITLE) or [""]
    body = [l for para in rest.split("\n") for l in (wrap_px(para, BODY) or [""])]
    while body and not body[-1]:              # a trailing blank line is paper for nothing
        body.pop()
    return title, body


def stamp(when):
    return f"Erstellt: {when.strftime('%d.%m.%Y %H:%M')}"


def pack(img):
    """1-bit image -> Star raster rows. Bit set = ink, so invert PIL's white=1."""
    raw = img.tobytes()                    # MSB first, bit set = white
    out = bytearray()
    for y in range(img.height):
        row = raw[y * STRIDE:(y + 1) * STRIDE]
        out += b"\x62" + bytes([STRIDE, 0]) + bytes(255 - b for b in row)   # invert
    return bytes(out)


def rasterize_ticket(message, when, margin=MARGIN):
    title, body = layout(message)
    height = PAD + len(title) * TITLE_H
    if body:
        height += GAP + RULE + GAP + len(body) * BODY_H
    height += GAP + META_H + margin

    img = Image.new("1", (DOTS, height), 1)                   # 1 = white
    draw = ImageDraw.Draw(img)
    y = PAD
    for i, line in enumerate(title):
        draw.text((PAD, y + i * TITLE_H), line, font=TITLE, fill=0)
    y += len(title) * TITLE_H
    if body:
        y += GAP
        draw.rectangle([PAD, y, DOTS - PAD - 1, y + RULE - 1], fill=0)
        y += RULE + GAP
        for i, line in enumerate(body):
            draw.text((PAD, y + i * BODY_H), line, font=BODY, fill=0)
        y += len(body) * BODY_H
    draw.text((PAD, y + GAP), stamp(when), font=META, fill=0)
    return pack(img)


def rasterize_caption(text, margin=8):
    """A photo prints bare: the caption is plain body text, with no rule and no footer."""
    lines = [l for para in text.split("\n") for l in (wrap_px(para, BODY) or [""])]
    img = Image.new("1", (DOTS, PAD + len(lines) * BODY_H + margin), 1)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((PAD, PAD + i * BODY_H), line, font=BODY, fill=0)
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


def emit_image(src, caption=None):
    rows = rasterize_caption(caption) if caption else b""
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
    send(RASTER_ON + rasterize_ticket(text, when or datetime.now()) + RASTER_OFF + CUT)


# leading underscore: "timeout" is also a getUpdates parameter and must reach **params
def api(method, _timeout=40, **params):
    url = API.format(TOKEN, method) + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=_timeout) as r:
        return json.load(r)


def main():
    if not TOKEN or not ALLOWED:
        sys.exit("Set TELEGRAM_TOKEN to your bot token from @BotFather. "
                 "Set TELEGRAM_ALLOWED to one or more Telegram user IDs. "
                 "Separate the user IDs with commas.")
    print(f"The bot prints to {HOST}:{PORT}. It renders with "
          f"{os.path.basename(FONT_PATH)} at {BODY_PT} pt. "
          f"The bot accepts messages from these user IDs: {sorted(ALLOWED)}.",
          file=sys.stderr)
    offset = 0
    while True:
        try:
            updates = api("getUpdates", offset=offset, timeout=30)["result"]
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):               # bad token: retrying cannot fix it
                sys.exit(f"Telegram rejected the bot token. The HTTP status was "
                         f"{e.code}. Check TELEGRAM_TOKEN. The current token ends "
                         f"with {TOKEN[-6:]!r}.")
            print(f"The request to Telegram failed: {e}", file=sys.stderr)
            time.sleep(5)
            continue
        except Exception as e:                     # network blip, bad gateway, ...
            print(f"The request to Telegram failed: {e}", file=sys.stderr)
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
                if sender not in ALLOWED:
                    why = (f"User {sender} is not in TELEGRAM_ALLOWED. "
                           f"These user IDs can print: {sorted(ALLOWED)}.")
                else:
                    why = (f"The message has no text and no image. "
                           f"It contains these fields: {sorted(msg)}.")
                print(f"The bot ignored a message. {why}", file=sys.stderr)
                continue
            try:
                if file_id:
                    print(f"The bot prints an image from user {sender}.", file=sys.stderr)
                    emit_image(download(file_id), msg.get("caption"))
                else:
                    print(f"The bot prints a message from user {sender}. "
                          f"The message has {len(text)} characters.", file=sys.stderr)
                    emit(text)
            except OSError as e:                   # printer off, out of paper, unplugged
                print(f"The bot could not send the job to the printer: {e}", file=sys.stderr)
                try:
                    api("sendMessage", _timeout=10, chat_id=msg["chat"]["id"],
                        text=f"The bot could not print your message. "
                             f"The error was: {e}")
                except Exception:
                    pass


def diagnose():
    print("getMe       :", json.dumps(api("getMe", _timeout=10))[:300])
    print("webhookInfo :", json.dumps(api("getWebhookInfo", _timeout=10))[:300])
    print("pending     :", json.dumps(api("getUpdates", _timeout=10))[:2000])


def selftest():
    when = datetime(2026, 8, 18, 9, 5)
    # the first line is the title, everything after it is the body
    assert layout("Have fun\nYou look cute.") == (["Have fun"], ["You look cute."])
    # a one-line message is all title and has no body, so it gets no rule
    assert layout("Have fun")[1] == []
    # blank lines are how people space a note; keep the shape they sent
    assert layout("t\na\n\nb")[1] == ["a", "", "b"]
    # a trailing blank line is paper spent on nothing
    assert layout("t\na\n\n\n")[1] == ["a"]
    # No line may overflow the paper, however it was typed. This replaces the old
    # character count, which only held while the face was monospace.
    for para in ["x " * 300, "e" * 200, "Trans" + "kalibrierung " * 20]:
        for font in (TITLE, BODY, META):
            assert all(font.getlength(l) <= USABLE for l in wrap_px(para, font))
    # a word wider than the paper is broken with a hyphen, not left to run off it
    broken = wrap_px("e" * 200, BODY)
    assert len(broken) > 1 and all(l.endswith("-") for l in broken[:-1])
    # the footer carries the creation time
    assert stamp(when) == "Erstellt: 18.08.2026 09:05"
    # the long-poll timeout must reach Telegram, not urlopen, or this busy-loops into a 429
    import inspect
    assert "timeout" not in inspect.signature(api).parameters
    # every raster row must carry the exact header the printer expects, or it prints nothing
    rows = rasterize_ticket("hi\nthere", when)
    assert len(rows) % (STRIDE + 3) == 0
    assert all(rows[i] == 0x62 and rows[i + 1] == STRIDE
               for i in range(0, len(rows), STRIDE + 3))
    # the bottom margin must actually reach the paper, not just the bitmap
    assert len(rows) // (STRIDE + 3) >= MARGIN
    # the margin must be a knob, not baked into the middle of the receipt
    assert len(rasterize_ticket("hi\nthere", when, margin=0)) < len(rows)
    # ink is bit-set: an all-white page must be all-zero bits
    blank = pack(Image.new("1", (DOTS, 8), 1))
    assert not any(blank[i + 3:i + 3 + STRIDE].strip(b"\x00")
                   for i in range(0, len(blank), STRIDE + 3))
    print(f"Self-test passed. The bot renders with {os.path.basename(FONT_PATH)} "
          f"at {BODY_PT} pt across {USABLE} usable dots.")


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
        print(f"The bot sent an image {len(rows)//(STRIDE+3)/8:.0f} mm long.")
    elif arg == "--test-print":
        emit("test print\numlauts: äöüß\nlong line " + "abcdefghij " * 8)
    else:
        main()
