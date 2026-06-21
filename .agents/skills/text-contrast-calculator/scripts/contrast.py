import json
import sys


def parse_color(c):
    if c.startswith("#"):
        c = c.lstrip("#")
        if len(c) == 3:
            c = "".join([x * 2 for x in c])
        return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))
    # Para simplificar el demo asumimos formato rgb(R, G, B)
    if c.startswith("rgb"):
        parts = c.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")
        if len(parts) >= 3:
            return (int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))
    return (0, 0, 0)


def luminance(r, g, b):
    a = [v / 255.0 for v in [r, g, b]]
    a = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in a]
    return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722


def contrast_ratio(l1, l2):
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(json.dumps({"error": "Usage: contrast.py <fg_color> <bg_color>"}))
        sys.exit(1)

    fg = sys.argv[1]
    bg = sys.argv[2]

    fg_rgb = parse_color(fg)
    bg_rgb = parse_color(bg)

    l1 = luminance(*fg_rgb)
    l2 = luminance(*bg_rgb)

    ratio = contrast_ratio(l1, l2)

    print(
        json.dumps(
            {
                "fg_color": fg,
                "bg_color": bg,
                "ratio": round(ratio, 2),
                "passes_normal": ratio >= 4.5,
                "passes_large": ratio >= 3.0,
            },
            indent=2,
        )
    )
