"""Color-vision simulation for the preview (Machado, Oliveira & Fernandes 2009, full severity, applied in sRGB):
how the theme looks to people with red-, green- or blue-blindness, or with no color vision at all. Contrast
checks can't catch an accent and a warning color that turn into the same color."""
from __future__ import annotations

MODES = {   # key -> (label, 3x3 matrix on RGB)
    "protanopia": ("Red-blind (protanopia)", ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216),
                                              (-0.003882, -0.048116, 1.051998))),
    "deuteranopia": ("Green-blind (deuteranopia)", ((0.367322, 0.860646, -0.227968),
                                                    (0.280085, 0.672501, 0.047413),
                                                    (-0.011820, 0.042940, 0.968881))),
    "tritanopia": ("Blue-blind (tritanopia)", ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602),
                                               (0.004733, 0.691367, 0.303900))),
    "achromatopsia": ("No color (achromatopsia)", ((0.299, 0.587, 0.114),) * 3),
}


def available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def simulate_rgb(rgb: tuple[int, int, int], mode: str) -> tuple[int, int, int]:
    """One color as seen with `mode`."""
    m = MODES[mode][1]
    return tuple(max(0, min(255, round(sum(m[r][c] * rgb[c] for c in range(3))))) for r in range(3))


def simulate_image(data: bytes, size: tuple[int, int], stride: int, mode: str) -> bytes:
    """Packed RGB888 rows (with `stride` bytes per row) -> packed RGB888 (3 * width per row), as seen with `mode`."""
    from PIL import Image
    m = MODES[mode][1]
    im = Image.frombuffer("RGB", size, data, "raw", "RGB", stride, 1)
    return im.convert("RGB", (*m[0], 0, *m[1], 0, *m[2], 0)).tobytes()
