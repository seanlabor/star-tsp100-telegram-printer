#!/usr/bin/env python3
"""Draw the example donkey and its dithered form. Original art, no third-party rights.

    ../.venv/bin/python make_example.py
"""
from PIL import Image, ImageDraw, ImageFilter

W = 600
img = Image.new("L", (W, W), 255)
d = ImageDraw.Draw(img)


def ear(cx, cy, tilt):
    """Ear on its own canvas so it can be rotated, with a real binary paste mask."""
    e, m = Image.new("L", (150, 330), 255), Image.new("L", (150, 330), 0)
    ed, md = ImageDraw.Draw(e), ImageDraw.Draw(m)
    ed.ellipse((12, 12, 138, 318), fill=115)      # outer ear
    md.ellipse((12, 12, 138, 318), fill=255)      # mask: shape only, not shading
    ed.ellipse((42, 55, 108, 265), fill=210)      # inner ear
    e = e.rotate(tilt, resample=Image.BICUBIC, expand=True, fillcolor=255)
    m = m.rotate(tilt, resample=Image.BICUBIC, expand=True, fillcolor=0)
    img.paste(e, (cx - e.width // 2, cy - e.height // 2), m)


ear(196, 168, 20)
ear(404, 168, -20)
d.ellipse((205, 175, 395, 300), fill=105)         # forelock
d.ellipse((196, 200, 404, 480), fill=140)         # long face
d.ellipse((228, 360, 372, 552), fill=205)         # muzzle
d.ellipse((232, 286, 276, 328), fill=30)          # eyes, set wide like a donkey's
d.ellipse((324, 286, 368, 328), fill=30)
d.ellipse((243, 293, 257, 307), fill=250)         # catchlights
d.ellipse((335, 293, 349, 307), fill=250)
d.ellipse((266, 442, 292, 478), fill=65)          # nostrils
d.ellipse((308, 442, 334, 478), fill=65)
d.arc((262, 486, 338, 524), 15, 165, fill=85, width=5)   # mouth

img = img.filter(ImageFilter.GaussianBlur(2))     # soft gradients so dithering shows
img.save("donkey.png")
img.resize((576, 576), Image.LANCZOS).convert("1").save("donkey-dithered.png")
print("wrote donkey.png and donkey-dithered.png")
