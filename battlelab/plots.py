"""Standard figures. Kept separate so the core never imports matplotlib."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def shapley_bars(tables: dict[str, pd.DataFrame], titles: dict[str, str], path: str):
    fig, axes = plt.subplots(1, len(tables), figsize=(6.5 * len(tables), 4.4))
    axes = np.atleast_1d(axes)
    for ax, (key, t) in zip(axes, tables.items()):
        t = t.sort_values("shapley", key=np.abs)
        err = np.vstack([t.shapley - t.lo90, t.hi90 - t.shapley])
        colors = ["#2166ac" if v >= 0 else "#b2182b" for v in t.shapley]
        ax.barh(t.factor, t.shapley, xerr=err, color=colors, alpha=0.85, capsize=3)
        ax.axvline(0, color="k", lw=0.8)
        ax.set_title(titles[key], fontsize=10)
        ax.set_xlabel("Shapley contribution to change in P(outcome)")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def sweep_heatmap(df: pd.DataFrame, x: str, y: str, path: str, title: str = ""):
    piv = df.pivot_table(index=y, columns=x, values="p")
    fig, ax = plt.subplots(figsize=(7, 5.2))
    im = ax.pcolormesh(piv.columns, piv.index, piv.values, shading="nearest",
                       cmap="viridis", vmin=0, vmax=1)
    cs = ax.contour(piv.columns, piv.index, piv.values, levels=[0.25, 0.5, 0.75],
                    colors="white", linewidths=0.8)
    ax.clabel(cs, fmt="%.2f", fontsize=8)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.set_title(title or "P(outcome)")
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def anchors_bar(tables: dict[str, pd.DataFrame], path: str):
    fig, axes = plt.subplots(1, len(tables), figsize=(6.5 * len(tables), 3.8))
    axes = np.atleast_1d(axes)
    for ax, (key, t) in zip(axes, tables.items()):
        err = np.vstack([t.share - t.lo95, t.hi95 - t.share])
        ax.barh(t.anchor, t.share, xerr=err, color="#5aae61", capsize=3)
        ax.set_xlim(0, 1)
        ax.invert_yaxis()
        ax.set_title(f"{key}: share of runs reproducing each historical fact", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
