"""
Gerador programático do ícone oficial do aplicativo (.ico e .png)
utilizando Pillow para garantir alta resolução em todas as escalas do Windows.
"""

from __future__ import annotations

import os
from pathlib import Path
from PIL import Image, ImageDraw

try:
    from config import APP_SLUG
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import APP_SLUG


def create_app_icon_image(
    size: int = 256,
    badge_color: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """
    Desenha o ícone moderno do Monitoramento de Pasta:
    - Fundo quadrado arredondado azul-escuro/petróleo (#0F172A -> #1E293B)
    - Pasta estilizada em azul-ciano (#38BDF8 / #0284C7)
    - Selo circular de checklist verde-esmeralda (#10B981) com check branco.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(2, int(size * 0.06))
    radius = max(4, int(size * 0.22))

    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=(15, 23, 42, 255),
        outline=(51, 65, 85, 255),
        width=max(1, int(size * 0.025)),
    )

    fx1 = int(size * 0.20)
    fy1 = int(size * 0.26)
    fx2 = int(size * 0.48)
    fy2 = int(size * 0.38)
    draw.rounded_rectangle(
        [fx1, fy1, fx2, fy2],
        radius=max(2, int(size * 0.04)),
        fill=(2, 132, 199, 255),
    )

    bx1 = int(size * 0.20)
    by1 = int(size * 0.33)
    bx2 = int(size * 0.80)
    by2 = int(size * 0.75)
    draw.rounded_rectangle(
        [bx1, by1, bx2, by2],
        radius=max(3, int(size * 0.06)),
        fill=(14, 165, 233, 255),
    )

    lx1 = int(size * 0.30)
    lx2 = int(size * 0.65)
    line_h = max(2, int(size * 0.035))
    for idx, frac_y in enumerate((0.45, 0.54, 0.63)):
        ly = int(size * frac_y)
        end_x = lx2 if idx < 2 else int(size * 0.52)
        draw.rounded_rectangle(
            [lx1, ly, end_x, ly + line_h],
            radius=max(1, line_h // 2),
            fill=(224, 242, 254, 235),
        )

    circle_color = badge_color or (16, 185, 129, 255)
    cx1 = int(size * 0.54)
    cy1 = int(size * 0.54)
    cx2 = int(size * 0.86)
    cy2 = int(size * 0.86)
    draw.ellipse(
        [cx1, cy1, cx2, cy2],
        fill=circle_color,
        outline=(15, 23, 42, 255),
        width=max(1, int(size * 0.03)),
    )

    p1 = (int(size * 0.63), int(size * 0.70))
    p2 = (int(size * 0.68), int(size * 0.76))
    p3 = (int(size * 0.78), int(size * 0.64))
    stroke_w = max(2, int(size * 0.045))
    draw.line([p1, p2, p3], fill=(255, 255, 255, 255), width=stroke_w, joint="curve")

    return img


def ensure_icon_files(assets_dir: Path) -> Path:
    """
    Garante que `icon.ico` e `icon.png` existam.
    Caso o diretório de instalação esteja protegido, utiliza fallback em `%LOCALAPPDATA%`.
    """
    ico_path = assets_dir / "icon.ico"
    png_path = assets_dir / "icon.png"
    if ico_path.exists() and ico_path.stat().st_size > 0:
        return ico_path

    base_img = create_app_icon_image(256)
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        base_img.save(png_path, format="PNG")
        base_img.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        return ico_path
    except OSError:
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        fallback_dir = Path(local_app_data) / APP_SLUG / "assets"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fb_ico = fallback_dir / "icon.ico"
        fb_png = fallback_dir / "icon.png"
        base_img.save(fb_png, format="PNG")
        base_img.save(
            fb_ico,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        return fb_ico


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    target = Path(__file__).resolve().parent
    out = ensure_icon_files(target)
    print(f"Icon generated at: {out}")
