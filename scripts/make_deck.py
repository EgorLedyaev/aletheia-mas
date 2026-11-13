"""Render docs/deck.md to docs/deck.pdf and one PNG per slide.

Layout is computed before drawing, and the font scale is reduced until the slide fits: a bullet
silently cut off at the bottom of a slide was a real defect in the previous version of this deck.
If a slide still does not fit at the smallest scale, this script exits non-zero.
"""
from __future__ import annotations

import json
import os
import re
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG, FG, DIM, ACC = "#ffffff", "#141821", "#5d6675", "#2b6cb0"
SCALES = (1.0, 0.94, 0.88, 0.82, 0.76, 0.70, 0.64)


TOKEN = re.compile(r"\{\{([a-z_]+)\}\}")


def substitute(raw: str) -> str:
    """Replace {{token}} with a measured value from eval/deck_stats.json.

    A slide may not state a pass rate that no run produced: an unresolved token is a build error.
    """
    path = os.path.join(HERE, "eval", "deck_stats.json")
    stats = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            stats = json.load(fh)
    missing = sorted({m.group(1) for m in TOKEN.finditer(raw)} - set(stats))
    if missing:
        raise SystemExit(f"deck.md references measured values that do not exist in "
                         f"eval/deck_stats.json: {missing} (run scripts/deck_stats.py)")
    return TOKEN.sub(lambda m: str(stats[m.group(1)]), raw)


def parse(md_path):
    with open(md_path, encoding="utf-8") as fh:
        raw = substitute(fh.read())
    raw = re.sub(r"^---\nmarp.*?\n---\n", "", raw, flags=re.S)
    return [s.strip() for s in raw.split("\n---\n") if s.strip()]


def layout(slide, scale):
    """Return (ops, final_y, floor). An op is (x, y, text, fontsize, colour, kwargs)."""
    ops = []
    y = 0.90
    img = re.search(r"!\[[^\]]*\]\(([^)]+)\)", slide)
    floor = 0.56 if img else 0.10
    for ln in slide.splitlines():
        s = ln.rstrip()
        if not s:
            y -= 0.018 * scale
            continue
        if s.startswith("!["):
            continue
        if s.startswith("> *"):
            ops.append((0.03, 0.055, s.strip("> ").strip("*"), 8, DIM,
                        {"style": "italic", "va": "bottom"}))
            continue
        if s.startswith("### "):
            ops.append((0.03, y, s[4:], 17 * scale, ACC, {}))
            y -= 0.085 * scale
        elif s.startswith("## "):
            ops.append((0.03, y, s[3:], 19 * scale, FG, {"weight": "semibold"}))
            y -= 0.105 * scale
        elif s.startswith("# "):
            ops.append((0.03, y, s[2:], 30 * scale, FG, {"weight": "semibold"}))
            y -= 0.14 * scale
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            txt = re.sub(r"[`*]", "", "   ".join(c for c in cells if c))
            for seg in textwrap.wrap(txt, int(118 / scale)) or [""]:
                ops.append((0.045, y, seg, 8.6 * scale, FG, {"family": "monospace"}))
                y -= 0.036 * scale
        elif s.startswith("```"):
            continue
        else:
            bullet = s.startswith(("* ", "- ", "1. ", "2. ", "3. ", "4. ", "5. "))
            body = re.sub(r"^[*\-]\s+", "", s)
            body = re.sub(r"^\d+\.\s+", "", body)
            body = re.sub(r"[`*]", "", body)
            prefix = "\u2022  " if bullet else ""
            for i, seg in enumerate(textwrap.wrap(body, int(104 / scale)) or [""]):
                ops.append((0.045 if bullet else 0.03, y, (prefix if i == 0 else "   ") + seg,
                            11 * scale, FG if not s.startswith(">") else DIM, {}))
                y -= 0.047 * scale
            y -= 0.012 * scale
    return ops, y, floor


def render(slide, ax, scale):
    ax.axis("off")
    ops, _, _ = layout(slide, scale)
    for x, y, text, size, colour, kw in ops:
        ax.text(x, y, text, fontsize=size, color=colour, transform=ax.transAxes,
                va=kw.pop("va", "top"), **kw)
    img = re.search(r"!\[[^\]]*\]\(([^)]+)\)", slide)
    if img:
        p = os.path.normpath(os.path.join(HERE, "docs", img.group(1)))
        if os.path.exists(p):
            im = mpimg.imread(p)
            h, w = im.shape[:2]
            # a slide carrying only a title and a caption gives the figure the whole slide;
            # one with bullets keeps the figure below them.
            has_text = any(ln.startswith(("- ", "|", "**")) for ln in slide.splitlines())
            box_bottom, box_top = 0.09, (0.52 if has_text else 0.80)
            avail_h = box_top - box_bottom
            disp_h, disp_w = avail_h, avail_h * (w / h) * (9 / 16)
            if disp_w > 0.92:
                disp_w = 0.92
                disp_h = disp_w * (h / w) * (16 / 9)
            iax = ax.figure.add_axes([(1 - disp_w) / 2, box_bottom + (avail_h - disp_h) / 2,
                                      disp_w, disp_h])
            iax.imshow(im)
            iax.axis("off")


def fit_scale(slide):
    """Largest scale at which the slide's text clears the floor; None if none fits."""
    for sc in SCALES:
        _, y, floor = layout(slide, sc)
        if y >= floor:
            return sc
    return None


def main() -> int:
    slides = parse(os.path.join(HERE, "docs", "deck.md"))
    out = os.path.join(HERE, "docs", "deck.pdf")
    png_dir = os.path.join(HERE, "figures", "deck")
    os.makedirs(png_dir, exist_ok=True)
    # only the rendered slides: this directory also holds the source figures the slides embed,
    # and an earlier version of this loop deleted them one step before they were needed.
    for f in os.listdir(png_dir):
        if re.fullmatch(r"slide_\d+\.png", f):
            os.remove(os.path.join(png_dir, f))
    overflow, shrunk = [], []
    with PdfPages(out) as pdf:
        for i, s in enumerate(slides, 1):
            sc = fit_scale(s)
            if sc is None:
                overflow.append(i)
                sc = SCALES[-1]
            elif sc < 1.0:
                shrunk.append((i, sc))
            fig = plt.figure(figsize=(13.333, 7.5), facecolor=BG)
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_facecolor(BG)
            render(s, ax, sc)
            if i > 1:
                ax.text(0.97, 0.035, f"{i}/{len(slides)}", fontsize=9, color=DIM,
                        transform=ax.transAxes, ha="right")
                ax.text(0.03, 0.035, "Aletheia \u2014 \u0421\u0418\u041d\u0422\u0415\u0417 2026,"
                        " \u041a\u0435\u0439\u0441 1", fontsize=8.5, color=DIM,
                        transform=ax.transAxes)
            pdf.savefig(fig, facecolor=BG)
            fig.savefig(os.path.join(png_dir, f"slide_{i:02d}.png"), dpi=96, facecolor=BG)
            plt.close(fig)
    print(f"{out}: {len(slides)} slides, {len(slides)} PNGs in figures/deck/")
    if shrunk:
        print("auto-shrunk: " + ", ".join(f"slide {i} x{sc:.2f}" for i, sc in shrunk))
    if overflow:
        print(f"OVERFLOW (content cut off): slides {overflow}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
