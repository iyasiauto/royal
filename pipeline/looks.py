"""
Named visual looks.

A documentary's grade should not be welded into the renderer: archival biography
wants grain and a vignette, a cooking or nature film wants neither. Each look is
a small bundle of FFmpeg filter fragments that the render engine splices in.

Pick one by name (`"look": "clean"` in a topic config, or --look clean), or
override individual fields alongside it.
"""

LOOKS = {
    # Grainy, vignetted, desaturated - archival biography and true crime.
    "vintage": {
        "grade": ("noise=alls=20:allf=t+u,vignette=PI/4,"
                  "eq=gamma=0.96:gamma_r=1.08:gamma_b=0.92:"
                  "saturation=0.88:contrast=1.08"),
        "postcard_eq": ("eq=gamma_r=1.12:gamma_b=0.88:"
                        "saturation=0.82:contrast=1.10"),
        "graphic_grade": "noise=alls=10:allf=t+u",
        "border_color": "0xdc2626",
        "fill_mode": "blur",
    },
    # No grain, no vignette, faithful colour - nature, travel, food, science.
    "clean": {
        "grade": "eq=saturation=1.04:contrast=1.02",
        "postcard_eq": "",
        "graphic_grade": "",
        "border_color": "0x1d4ed8",
        "fill_mode": "blur",
    },
    # Gentle warmth and lift, no texture - lifestyle and profile pieces.
    "warm": {
        "grade": ("eq=gamma=1.02:gamma_r=1.06:gamma_b=0.96:"
                  "saturation=1.06:contrast=1.03"),
        "postcard_eq": "",
        "graphic_grade": "",
        "border_color": "0xd97706",
        "fill_mode": "blur",
    },
    # High contrast monochrome - investigative and historical.
    "noir": {
        "grade": ("hue=s=0,noise=alls=14:allf=t+u,vignette=PI/3.5,"
                  "eq=gamma=0.94:contrast=1.22"),
        "postcard_eq": "eq=contrast=1.15",
        "graphic_grade": "hue=s=0",
        "border_color": "0xe5e5e5",
        "fill_mode": "blur",
    },
    # Nothing at all - deliver the source exactly as shot.
    "none": {
        "grade": "",
        "postcard_eq": "",
        "graphic_grade": "",
        "border_color": "0xdc2626",
        "fill_mode": "blur",
    },

    # ---------------------------------------------------------------- effects
    # These are the reusable named looks (RULE 16). Each is a full grade
    # bundle — pick with --look <name> or "look": "<name>" in the topic config.

    # Soft, even film grain. No color shift, no vignette. Modern documentary.
    "noise_soft": {
        "grade": "noise=alls=12:allf=t+u,eq=contrast=1.03",
        "postcard_eq": "",
        "graphic_grade": "noise=alls=6:allf=t+u",
        "border_color": "0x9ca3af",
        "fill_mode": "blur",
    },

    # Heavy grain concentrated in dark tones + crushed blacks. Grimy vintage.
    "black_noise": {
        "grade": ("noise=alls=28:allf=t+u,"
                  "eq=gamma=0.90:contrast=1.20:brightness=-0.03,"
                  "vignette=PI/4.5"),
        "postcard_eq": "eq=gamma=0.92:contrast=1.15",
        "graphic_grade": "noise=alls=16:allf=t+u,eq=gamma=0.92",
        "border_color": "0x111111",
        "fill_mode": "blur",
    },

    # Strong cinematic 16mm-style grain, subtle warmth. Matches Dolly-warm ref.
    "grainy": {
        "grade": ("noise=alls=32:allf=t+u,"
                  "eq=gamma=0.98:gamma_r=1.05:gamma_b=0.95:"
                  "saturation=0.94:contrast=1.06,"
                  "vignette=PI/5"),
        "postcard_eq": "eq=gamma_r=1.06:gamma_b=0.94:saturation=0.90",
        "graphic_grade": "noise=alls=14:allf=t+u",
        "border_color": "0xb45309",
        "fill_mode": "blur",
    },

    # Moody, dark, heavy grain + steep vignette + desaturation. Somber tone.
    "gloom_grain": {
        "grade": ("noise=alls=26:allf=t+u,vignette=PI/3.2,"
                  "eq=gamma=0.88:saturation=0.72:contrast=1.14:brightness=-0.04,"
                  "curves=preset=darker"),
        "postcard_eq": "eq=gamma=0.90:saturation=0.70:contrast=1.10",
        "graphic_grade": "noise=alls=12:allf=t+u,eq=saturation=0.75",
        "border_color": "0x0f172a",
        "fill_mode": "blur",
    },

    # Faded, drained color — retro / bleached / cross-processed. Low sat + lifted blacks.
    "color_off": {
        "grade": ("noise=alls=8:allf=t+u,"
                  "eq=gamma=1.04:saturation=0.55:contrast=0.94:brightness=0.02,"
                  "colorbalance=rs=.05:gs=-.03:bs=-.06:"
                  "rm=-.02:gm=.02:bm=.02"),
        "postcard_eq": "eq=saturation=0.55:contrast=0.94",
        "graphic_grade": "eq=saturation=0.60",
        "border_color": "0x9ca3af",
        "fill_mode": "blur",
    },

    # Strong dark vignette, no grain, faithful color. Focus attention on the frame center.
    "vignette_only": {
        "grade": "vignette=PI/3.2,eq=contrast=1.06",
        "postcard_eq": "",
        "graphic_grade": "vignette=PI/4",
        "border_color": "0x1f2937",
        "fill_mode": "blur",
    },

    # High-contrast monochrome + grain + vignette. Archival/investigative — matches Elvis ref.
    "documentary_bw": {
        "grade": ("hue=s=0,noise=alls=22:allf=t+u,vignette=PI/3.5,"
                  "eq=gamma=0.92:contrast=1.28,curves=preset=increase_contrast"),
        "postcard_eq": "eq=contrast=1.20",
        "graphic_grade": "hue=s=0,noise=alls=12:allf=t+u",
        "border_color": "0xf3f4f6",
        "fill_mode": "blur",
    },

    # Warm cinematic — subtle grain, soft vignette, gentle amber lift.
    "cinematic_warm": {
        "grade": ("noise=alls=14:allf=t+u,vignette=PI/4.5,"
                  "eq=gamma=1.02:gamma_r=1.08:gamma_b=0.94:"
                  "saturation=1.02:contrast=1.06,"
                  "colorbalance=rs=.06:gs=.02:bs=-.06"),
        "postcard_eq": "eq=gamma_r=1.08:gamma_b=0.94:saturation=1.00",
        "graphic_grade": "noise=alls=8:allf=t+u",
        "border_color": "0xb45309",
        "fill_mode": "blur",
    },
}

DEFAULT_LOOK = "vintage"

# Every field a look may define, with the value used when it is absent.
FIELDS = {
    "grade": "",
    "postcard_eq": "",
    "graphic_grade": "",
    "border_color": "0xdc2626",
    "fill_mode": "blur",      # blur | black | crop
    "fill_blur": 22,          # gaussian sigma for the blurred backdrop
    "fill_dim": 0.12,         # how far the backdrop is darkened, 0-1
    "fill_downscale": 6,      # blur a 1/N thumbnail instead of the full frame
    "fade_s": 0.25,
    "zoom_per_sec": 0.015,
}


def resolve(look=None, overrides=None):
    """Merge a named look with any explicit overrides into a full spec."""
    spec = dict(FIELDS)

    if isinstance(look, dict):
        spec.update({k: v for k, v in look.items() if k in FIELDS})
    elif look:
        name = str(look).lower()
        if name not in LOOKS:
            raise ValueError(
                f"Unknown look {look!r}. Available: {', '.join(sorted(LOOKS))}")
        spec.update(LOOKS[name])
    else:
        spec.update(LOOKS[DEFAULT_LOOK])

    for k, v in (overrides or {}).items():
        if k in FIELDS and v is not None:
            spec[k] = v
    return spec


def names():
    return sorted(LOOKS)
