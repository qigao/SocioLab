"""Render aggregate case evidence with Matplotlib; no source records are read.

Matplotlib is a documentation-only dependency, not a SocioLab runtime addition.
The SVG uses text labels and a fixed metadata date for reproducible exports.
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


def render(report_path: Path, output: Path, preview: Path | None = None):
    report = json.loads(report_path.read_text())
    if report["kind"] != "RECORDED_CONTACT_CASE_STUDY":
        raise ValueError("expected the aggregate recorded-contact case report")
    scenarios = report["analysis"]["scenarios"]
    expected = ["primary_10h", "minimum_3_bins_10h", "window_12h"]
    if [item["scenario"] for item in scenarios] != expected:
        raise ValueError("unexpected scenario order")
    colors = ("#315775", "#C16D3C")
    labels = ["10 hours\n≥1 bin", "10 hours\n≥3 bins", "12 hours\n≥1 bin"]
    cross_key = "cross_between_primary_baseline_nonzero_record_nodes"
    values = [
        [[w["structure"]["binary_pair_count"] for w in s["windows"]] for s in scenarios],
        [[w["fixed_primary_baseline_cross_groups"]["pair_counts"][cross_key]
          for w in s["windows"]] for s in scenarios],
        [[w["fixed_reference_group"]["score"] for w in s["windows"]] for s in scenarios],
    ]
    titles = ["A  Qualifying recorded pairs", "B  Cross-group recorded pairs", "C  Fixed group's betweenness"]
    subtitles = ["All 113 archive nodes retained", "Between baseline recording nodes", "Same two members in every graph"]
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.edgecolor": "#BCC6CE",
        "svg.fonttype": "none", "svg.hashsalt": "sociolab-contact-case-v1",
    })
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 6.4))
    fig.patch.set_facecolor("#FFFFFF")
    x = np.arange(3)
    width = 0.33
    for index, (ax, vals) in enumerate(zip(axes, values)):
        array = np.asarray(vals)
        for window in range(2):
            bars = ax.bar(x + (window - 0.5) * width, array[:, window], width,
                          color=colors[window], label=["First window", "Second window"][window], zorder=3)
            formatted = [f"{v:.3f}" if index == 2 else f"{int(v):,}" for v in array[:, window]]
            ax.bar_label(bars, labels=formatted, padding=4, fontsize=10)
        ax.set_xticks(x, labels)
        ax.set_ylim(0, (1200, 740, 0.34)[index])
        ax.set_title(titles[index], loc="left", pad=40, fontsize=13, weight="bold", color="#183549")
        ax.text(0, 1.065, subtitles[index], transform=ax.transAxes, fontsize=10, color="#4F6170")
        ax.grid(axis="y", color="#E6EBEF", linewidth=0.8, zorder=0)
        ax.tick_params(axis="both", length=0, pad=8, labelcolor="#405361")
        ax.set_axisbelow(True)
    axes[2].set_yticks([0, 0.1, 0.2, 0.3], ["0.0", "0.1", "0.2", "0.3"])
    axes[1].text(1, 252, "181 → 172", ha="center", color="#933F29", fontsize=11, weight="bold")
    fig.text(0.055, 0.945, "More recorded links can coexist with a less central reference group",
             fontsize=19, weight="bold", color="#183549")
    fig.text(0.055, 0.895, "Hypertext 2009  •  Equal calendar windows; device exposure unknown  •  Three predeclared scenarios",
             fontsize=11, color="#4F6170")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="lower left", bbox_to_anchor=(0.05, 0.135),
               frameon=False, ncol=2, fontsize=11)
    fig.text(0.055, 0.105,
             "Cross-group counts hold the primary first-window Louvain partition fixed. The reference group uses the full archive, including later records.",
             fontsize=9.5, color="#4F6170")
    fig.text(0.055, 0.075,
             "Published-log topology only: no claim of complete physical contacts, social influence, causal effects, or time-respecting transmission.",
             fontsize=9.5, color="#4F6170")
    fig.text(0.055, 0.041,
             "Source: SocioPatterns / Isella et al. (2011), doi:10.1016/j.jtbi.2010.11.033. Dataset terms: CC BY-NC-SA 3.0. Analysis: SocioLab / NetworkX 3.7.",
             fontsize=8.5, color="#62717B")
    fig.subplots_adjust(left=0.055, right=0.98, bottom=0.30, top=0.70, wspace=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="svg", metadata={"Date": "2026-11-28", "Title": "SocioLab recorded-contact case",
        "Description": "Aggregate case report SHA-256: " + sha256(report_path.read_bytes()).hexdigest()})
    # Matplotlib leaves spaces at path-line ends; normalize source formatting.
    output.write_text("\n".join(line.rstrip() for line in output.read_text().splitlines()) + "\n")
    if preview is not None:
        fig.savefig(preview, dpi=150)
    plt.close(fig)
    print(json.dumps({"output": output.name, "sha256": sha256(output.read_bytes()).hexdigest(),
                      "report_sha256": sha256(report_path.read_bytes()).hexdigest(),
                      "matplotlib_version": matplotlib.__version__}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=HERE / "case-report.json")
    parser.add_argument("--output", type=Path, default=HERE / "case-figure.svg")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    render(args.report, args.output, args.preview)
