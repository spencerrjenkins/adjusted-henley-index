"""Chart theme: palette slots, matplotlib styling, and shared mark helpers.

Colours are the validated reference palette, used unchanged. The ordering is the
safety mechanism rather than a preference, so slots are consumed in order and
never cycled: forms where every series can sit next to every other (scatter,
choropleth) are capped at the first three slots, which are the ones that clear
the all-pairs gates in both modes.

Every figure is rendered twice, once per mode, and the README pairs them in a
`<picture>` element so the charts follow the reader's theme instead of burning a
white rectangle into a dark page.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib as mpl
import matplotlib.pyplot as plt


@dataclass(frozen=True)
class Mode:
    name: str
    surface: str
    plane: str
    ink: str
    ink_secondary: str
    ink_muted: str
    grid: str
    axis: str
    series: tuple[str, ...]
    sequential: tuple[str, ...]
    diverging: tuple[str, str, str]   # (low pole, neutral, high pole)
    deemphasis: str


LIGHT = Mode(
    name="light",
    surface="#fcfcfb", plane="#f9f9f7",
    ink="#0b0b0b", ink_secondary="#52514e", ink_muted="#898781",
    grid="#e1e0d9", axis="#c3c2b7",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    sequential=("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"),
    diverging=("#e34948", "#f0efec", "#2a78d6"),
    deemphasis="#d8d7d0",
)

DARK = Mode(
    name="dark",
    surface="#1a1a19", plane="#0d0d0d",
    ink="#ffffff", ink_secondary="#c3c2b7", ink_muted="#898781",
    grid="#2c2c2a", axis="#383835",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    sequential=("#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"),
    diverging=("#e66767", "#383835", "#3987e5"),
    deemphasis="#3a3a37",
)

MODES = (LIGHT, DARK)

# Status palette is fixed across modes and never impersonates a series.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

FONT_STACK = ["system-ui", "-apple-system", "Segoe UI", "Helvetica Neue",
              "Helvetica", "Arial", "DejaVu Sans", "sans-serif"]


def apply(mode: Mode) -> None:
    mpl.rcParams.update({
        "figure.facecolor": mode.surface,
        "axes.facecolor": mode.surface,
        "savefig.facecolor": mode.surface,
        "axes.edgecolor": mode.axis,
        "axes.labelcolor": mode.ink_secondary,
        "axes.titlecolor": mode.ink,
        "text.color": mode.ink,
        "xtick.color": mode.ink_muted,
        "ytick.color": mode.ink_muted,
        "xtick.labelcolor": mode.ink_secondary,
        "ytick.labelcolor": mode.ink_secondary,
        "grid.color": mode.grid,
        "grid.linewidth": 0.8,
        "font.family": "sans-serif",
        "font.sans-serif": FONT_STACK,
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": 600,
        "axes.labelsize": 10,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "lines.linewidth": 2.0,
        "lines.markersize": 6,
        "figure.dpi": 110,
        "savefig.dpi": 200,
        "svg.fonttype": "none",
    })


def frame(ax, mode: Mode, keep=("bottom",), grid_axis: str | None = "y") -> None:
    """Strip chartjunk down to a baseline and a recessive grid."""
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)
        if side in keep:
            ax.spines[side].set_color(mode.axis)
            ax.spines[side].set_linewidth(1.0)
    if grid_axis:
        ax.grid(axis=grid_axis, color=mode.grid, linewidth=0.8)
        ax.set_axisbelow(True)
    ax.tick_params(length=0, pad=6)


def title(ax, mode: Mode, headline: str, subtitle: str | None = None) -> None:
    """Left-aligned headline with an optional explanatory second line.

    The subtitle carries the units and the caveat; a chart that needs a caption
    to be honest should have that caption attached to it, not in a paragraph the
    reader may never scroll to.
    """
    ax.set_title(headline, loc="left", color=mode.ink, fontsize=13, fontweight=600,
                 pad=26 if subtitle else 12)
    if subtitle:
        ax.annotate(subtitle, xy=(0, 1), xycoords="axes fraction", xytext=(0, 12),
                    textcoords="offset points", ha="left", va="bottom",
                    fontsize=9.5, color=mode.ink_secondary)


def sequential_color(mode: Mode, t: float) -> str:
    """Pick a step from the sequential ramp for t in [0, 1]."""
    ramp = mode.sequential
    idx = min(int(round(t * (len(ramp) - 1))), len(ramp) - 1)
    return ramp[max(idx, 0)]


def diverging_color(mode: Mode, value: float, scale: float) -> str:
    """Two poles and a neutral midpoint; never a hue at the middle."""
    low, mid, high = mode.diverging
    if abs(value) < scale * 0.05:
        return mid
    return high if value > 0 else low


def ring(artist, mode: Mode, width: float = 2.0) -> None:
    """2px surface ring so overlapping marks stay separable."""
    artist.set_path_effects([])
    artist.set_edgecolor(mode.surface)
    artist.set_linewidth(width)


def save(fig, name: str, mode: Mode, directory) -> None:
    fig.savefig(directory / f"{name}.{mode.name}.png", bbox_inches="tight",
                facecolor=mode.surface, dpi=200)
    plt.close(fig)
