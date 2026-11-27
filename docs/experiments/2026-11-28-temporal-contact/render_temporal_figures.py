"""Render aggregate temporal study figures with documentation-only Matplotlib.

No participant-level data or path lists are read. Reporting deadlines are
samples of cumulative reachability, not exact times of the intervening changes.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
COLORS = {"static": "#BCC7CF", "strict": "#315775", "nonstrict": "#C16D3C"}
LABELS = {"static": "Static graph", "strict": "Strict bin order", "nonstrict": "Same-bin relay allowed"}


def save(fig, path, report_hash, preview):
    fig.savefig(path, format="svg", metadata={
        "Date": "2026-11-28", "Title": "SocioLab recorded-bin temporal reachability",
        "Description": "Aggregate report SHA-256: " + report_hash,
    })
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")
    if preview is not None:
        preview.mkdir(parents=True, exist_ok=True)
        fig.savefig(preview / (path.stem + ".png"), dpi=150)
    plt.close(fig)


def render(report_path, output, preview=None):
    data = report_path.read_bytes()
    report_hash = sha256(data).hexdigest()
    report = json.loads(data)
    if report["kind"] != "RECORDED_CONTACT_TEMPORAL_STUDY":
        raise ValueError("expected a recorded-contact temporal study")
    scenarios = report["scenarios"]
    if [s["scenario"] for s in scenarios] != ["primary_10h", "minimum_3_bins_10h", "window_12h"]:
        raise ValueError("unexpected scenario definitions")
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.edgecolor": "#BCC6CE",
        "svg.fonttype": "none", "svg.hashsalt": "sociolab-temporal-contact-v1",
    })
    output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 6.4))
    fig.text(0.06, 0.94, "Static connectivity and contact-bin order answer different questions",
             fontsize=19, weight="bold", color="#183549")
    fig.text(0.06, 0.89, "Hypertext 2009  •  Same 113 archive IDs  •  Denominator: 12,656 ordered, nonself node pairs",
             fontsize=11, color="#4F6170")
    titles = ["10 hours · ≥1 recorded bin", "10 hours · ≥3 recorded bins", "12 hours · ≥1 recorded bin"]
    for ax, scenario, title in zip(axes, scenarios, titles):
        x, width = np.arange(2), 0.24
        for i, mode in enumerate(("static", "strict", "nonstrict")):
            values = [100 * w[mode]["reachable_ordered_pair_fraction"] for w in scenario["windows"]]
            bars = ax.bar(x + (i - 1) * width, values, width, color=COLORS[mode], label=LABELS[mode], zorder=3)
            ax.bar_label(bars, labels=[f"{value:.2f}" for value in values], padding=5, fontsize=9)
        ax.set_title(title, loc="left", pad=20, fontsize=12.5, weight="bold", color="#183549")
        ax.set_xticks(x, ["June 29\nFirst window", "June 30\nSecond window"])
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
        ax.grid(axis="y", color="#E6EBEF", linewidth=0.8, zorder=0)
        ax.tick_params(axis="both", length=0, pad=8, labelcolor="#405361")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.055, 0.18), ncol=3, frameon=False)
    fig.text(0.06, 0.135,
             "Each source is analyzed separately from the window start, with unlimited waiting. Two relay conventions use the same recorded contacts.",
             fontsize=9.5, color="#4F6170")
    fig.text(0.06, 0.102,
             "The ≥3-bin filter uses each pair's whole-window count, including later records. These comparisons do not bound actual transmission.",
             fontsize=9.5, color="#4F6170")
    fig.text(0.06, 0.058,
             "Source: SocioPatterns / Isella et al. (2011), doi:10.1016/j.jtbi.2010.11.033. Dataset terms: CC BY-NC-SA 3.0. Paths: original NetworkX 3.7.",
             fontsize=8.5, color="#62717B")
    fig.subplots_adjust(left=0.06, right=0.98, bottom=0.34, top=0.75, wspace=0.24)
    save(fig, output / "temporal-reachability.svg", report_hash, preview)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.5), sharey=True)
    fig.text(0.065, 0.94, "Reachability by elapsed reporting deadline", fontsize=19, weight="bold", color="#183549")
    fig.text(0.065, 0.89, "Primary 10-hour windows · ≥1 recorded bin per pair · each source initialized at the window start",
             fontsize=11, color="#4F6170")
    for ax, window, title in zip(axes, scenarios[0]["windows"], ["June 29, 2009 · first window", "June 30, 2009 · second window"]):
        for mode in ("strict", "nonstrict"):
            deadlines = window[mode]["deadlines"]
            hours = [0] + [row["seconds_from_window_start"] / 3600 for row in deadlines]
            values = [0] + [100 * row["reachable_ordered_pair_fraction"] for row in deadlines]
            ax.plot(hours, values, marker="o" if mode == "strict" else "s", markersize=5,
                    color=COLORS[mode], label=LABELS[mode], linewidth=2,
                    linestyle="-" if mode == "strict" else "--")
        ax.set_title(title, loc="left", fontsize=12.5, weight="bold", color="#183549", pad=17)
        ax.set_xlim(-0.15, 10.15)
        ax.set_xticks([0, 1, 2, 4, 6, 8, 10])
        ax.set_xlabel("Hours after window start", labelpad=10, color="#405361")
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
        ax.grid(axis="y", color="#E6EBEF", linewidth=0.8)
        ax.tick_params(axis="both", length=0, pad=8, labelcolor="#405361")
    axes[0].set_ylabel("Share of all 12,656 ordered node pairs", labelpad=12, color="#405361")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.06, 0.16), ncol=2, frameon=False)
    fig.text(0.065, 0.115,
             "Lines connect predeclared reporting deadlines; they do not locate exact times of intervening changes. Arrival uses bin-endpoint labels.",
             fontsize=9, color="#4F6170")
    fig.text(0.065, 0.085,
             "No actual delivery, device uptime, attendance, retention or continuous transfer latency is established by these curves.",
             fontsize=9, color="#4F6170")
    fig.text(0.065, 0.048,
             "Source: SocioPatterns / Isella et al. (2011). Dataset terms: CC BY-NC-SA 3.0. Analysis: SocioLab / original NetworkX 3.7.",
             fontsize=8.5, color="#62717B")
    fig.subplots_adjust(left=0.085, right=0.97, bottom=0.34, top=0.75, wspace=0.18)
    save(fig, output / "temporal-arrivals.svg", report_hash, preview)
    print(json.dumps({"report_sha256": report_hash, "matplotlib_version": matplotlib.__version__,
                      "figures": {p.name: sha256(p.read_bytes()).hexdigest()
                                  for p in (output / "temporal-reachability.svg", output / "temporal-arrivals.svg")}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=HERE / "temporal-report.json")
    parser.add_argument("--output", type=Path, default=HERE)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    render(args.report, args.output, args.preview)
