"""One-shot: renders motionlab.ico (lime M mark on near-black rounded square)."""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
BG = (19, 20, 16, 255)        # near-black, lime-tinted
LIME = (198, 255, 46, 255)    # acid lime


def draw_mark(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size * 0.22
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)
    # M as three strokes: two verticals + V in the middle
    w = max(2, round(size * 0.085))
    x0, x1 = size * 0.27, size * 0.73
    ytop, ybot = size * 0.30, size * 0.72
    xm = size * 0.5
    ymid = size * 0.58
    for seg in [
        ((x0, ybot), (x0, ytop)),
        ((x0, ytop), (xm, ymid)),
        ((xm, ymid), (x1, ytop)),
        ((x1, ytop), (x1, ybot)),
    ]:
        d.line([seg[0], seg[1]], fill=LIME, width=w)
    # square joints
    for x, y in [(x0, ytop), (x1, ytop), (x0, ybot), (x1, ybot), (xm, ymid)]:
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=LIME)
    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [draw_mark(s) for s in sizes]
    out = HERE / "motionlab.ico"
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
