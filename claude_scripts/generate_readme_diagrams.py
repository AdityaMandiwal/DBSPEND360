"""
Regenerate the architecture and implementation-flow diagrams used in README.md.

Outputs:
    release/readme_images/architecture.png
    release/readme_images/implementation_flow.png

Run with:
    uv run --with matplotlib python claude_scripts/generate_readme_diagrams.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# -----------------------------------------------------------------------------
# Style / palette
# -----------------------------------------------------------------------------

PALETTE = {
    "source_fill": "#E8F1FA",
    "source_edge": "#1F77B4",
    "system_fill": "#EFE6F7",
    "system_edge": "#7E57C2",
    "task_fill": "#FFF1E0",
    "task_edge": "#FF6F1A",
    "table_fill": "#E6F4EA",
    "table_edge": "#2E7D32",
    "support_fill": "#FBE9E7",
    "support_edge": "#C62828",
    "consumer_fill": "#FFFDE7",
    "consumer_edge": "#F9A825",
    "llm_fill": "#E1F5FE",
    "llm_edge": "#0277BD",
    "lane_fill": "#F8F9FB",
    "lane_edge": "#CED4DA",
    "arrow": "#37474F",
    "arrow_dashed": "#78909C",
    "title": "#102A43",
    "subtitle": "#37474F",
}

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "release" / "readme_images"


# -----------------------------------------------------------------------------
# Drawing primitives
# -----------------------------------------------------------------------------


def draw_box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    subtitle: str | None = None,
    fill: str = "#FFFFFF",
    edge: str = "#37474F",
    title_color: str = "#102A43",
    subtitle_color: str = "#37474F",
    title_size: int = 11,
    subtitle_size: int = 9,
    rounding: float = 0.04,
    lw: float = 1.6,
):
    """Draw a rounded rectangle with a title and optional subtitle."""
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.01,rounding_size={rounding}",
        linewidth=lw,
        edgecolor=edge,
        facecolor=fill,
        zorder=2,
    )
    ax.add_patch(box)

    if subtitle:
        ax.text(
            x + w / 2,
            y + h * 0.62,
            title,
            ha="center",
            va="center",
            fontsize=title_size,
            fontweight="bold",
            color=title_color,
            zorder=3,
        )
        ax.text(
            x + w / 2,
            y + h * 0.30,
            subtitle,
            ha="center",
            va="center",
            fontsize=subtitle_size,
            color=subtitle_color,
            zorder=3,
        )
    else:
        ax.text(
            x + w / 2,
            y + h / 2,
            title,
            ha="center",
            va="center",
            fontsize=title_size,
            fontweight="bold",
            color=title_color,
            zorder=3,
        )


def draw_lane(ax, x, y, w, h, label, label_offset: float = 0.22):
    """Draw a soft background lane with the section label rendered ABOVE the lane.

    Placing the label outside the lane (rather than inside near the top edge)
    guarantees that boxes inside the lane never overlap the section heading.

    The label is rendered with a white bbox and high zorder so that any arrow
    travelling between lanes is masked behind the label text. The figure
    background is white, so the bbox is visually invisible - it just hides
    arrow segments that would otherwise cross the heading.
    """
    lane = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.01,rounding_size=0.05",
        linewidth=1.0,
        edgecolor=PALETTE["lane_edge"],
        facecolor=PALETTE["lane_fill"],
        zorder=1,
    )
    ax.add_patch(lane)
    ax.text(
        x + 0.25,
        y + h + label_offset,
        label,
        ha="left",
        va="center",
        fontsize=11.5,
        fontweight="bold",
        color=PALETTE["title"],
        bbox=dict(facecolor="white", edgecolor="none", pad=3),
        zorder=10,
    )


def arrow(
    ax,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str | None = None,
    style: str = "-",
    lw: float = 1.6,
    rad: float = 0.0,
):
    color = color or PALETTE["arrow"]
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=lw,
            color=color,
            linestyle=style,
            connectionstyle=f"arc3,rad={rad}",
            zorder=4,
        )
    )


# -----------------------------------------------------------------------------
# Diagram 1: Architecture
# -----------------------------------------------------------------------------


def render_architecture(path: Path):
    """Render the logical architecture diagram.

    Layout principles (top-down):
      * Title and subtitle render via ax.text so bbox_inches='tight' keeps
        them precisely centered on the content extent.
      * Each tier has the section label drawn ABOVE its lane (via draw_lane)
        so the heading can never collide with the boxes inside.
      * Arrows flow primarily downward (sources -> tasks -> tables -> app).
        Back-references from tier-3 tables to Task 3 were removed - the
        downward flow is enough to convey logical dependencies and removing
        the curved dashed arrows makes the diagram far easier to scan.
      * Audit / error logs sit on the right of the curated-tables lane with
        a small italic annotation. No criss-crossing arrow from every task.
    """
    fig_w, fig_h = 16, 11
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 11)
    ax.set_aspect("equal")
    ax.axis("off")

    # ---- Title + subtitle (ax.text -> centered when figure is tight-cropped)
    ax.text(
        8.0, 10.70,
        "DBSPEND360  -  Logical Architecture",
        ha="center", va="center",
        fontsize=18, fontweight="bold",
        color=PALETTE["title"],
    )
    ax.text(
        8.0, 10.20,
        "Cloud cost + Databricks DBU cost  ->  job-level spend  ->  dashboards & AI insights",
        ha="center", va="center",
        fontsize=11.5,
        color=PALETTE["subtitle"],
    )

    # ---- Lanes (labels drawn ABOVE each lane via draw_lane)
    # Vertical bookkeeping (top-down):
    #   subtitle    y=10.20
    #   label 1     y= 9.87  (= 9.65 + 0.22)
    #   Lane 1      y=8.30..9.65   (h=1.35)
    #   label 2     y= 8.12
    #   Lane 2      y=6.20..7.90   (h=1.70)
    #   label 3     y= 5.97
    #   Lane 3      y=3.40..5.75   (h=2.35)
    #   label 4     y= 3.22
    #   Lane 4      y=0.40..3.00   (h=2.60)
    #   footnote    y= 0.05
    draw_lane(ax, 0.3, 8.30, 15.4, 1.35, "1. Data Sources")
    draw_lane(ax, 0.3, 6.20, 15.4, 1.70, "2. DBSpend360 Pipeline  (Databricks Job)")
    draw_lane(ax, 0.3, 3.40, 15.4, 2.35, "3. Curated Delta Tables  (Unity Catalog)")
    draw_lane(ax, 0.3, 0.40, 15.4, 2.60, "4. Consumption")

    # ---- Tier 1: Sources
    src_y, src_h = 8.50, 1.00
    cloud_x, cloud_w = 0.9, 6.5
    sys_x, sys_w = 8.2, 6.9
    draw_box(
        ax, cloud_x, src_y, cloud_w, src_h,
        "Cloud Cost Explorer APIs",
        "AWS Cost Explorer   |   Azure Cost Management   |   GCP Cloud Billing*",
        fill=PALETTE["source_fill"], edge=PALETTE["source_edge"],
        title_size=12, subtitle_size=9.5,
    )
    draw_box(
        ax, sys_x, src_y, sys_w, src_h,
        "Databricks System Tables",
        "system.billing.usage   |   system.billing.list_prices   |   system.compute.clusters",
        fill=PALETTE["system_fill"], edge=PALETTE["system_edge"],
        title_size=12, subtitle_size=9.5,
    )

    # ---- Tier 2: Pipeline tasks
    task_y, task_h = 6.35, 1.40
    t1_x, t1_w = 0.7, 4.7
    t2_x, t2_w = 5.6, 4.6
    t3_x, t3_w = 10.4, 4.9

    draw_box(
        ax, t1_x, task_y, t1_w, task_h,
        "Task 1   -   cloud_cost_explorer",
        "<provider>_cloud_cost_explorer_app\n(aws | azure | gcp*)",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=12, subtitle_size=9.5,
    )
    draw_box(
        ax, t2_x, task_y, t2_w, task_h,
        "Task 2   -   dbspend360_dbu_costs",
        "dbspend360_dbu_cost_app",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=12, subtitle_size=9.5,
    )
    draw_box(
        ax, t3_x, task_y, t3_w, task_h,
        "Task 3   -   databricks_job_spends",
        "databricks_job_spends_app\n(joins cloud + DBU)",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=12, subtitle_size=9.5,
    )

    # ---- Source -> Task arrows
    # Cloud APIs feed Task 1
    arrow(ax, cloud_x + cloud_w / 2, src_y, t1_x + t1_w / 2, task_y + task_h, lw=1.8)
    # System Tables feed Task 2 (DBU cost computation)
    arrow(ax, sys_x + sys_w * 0.20, src_y, t2_x + t2_w / 2, task_y + task_h, lw=1.8)
    # System Tables also feed Task 3 (cluster / job metadata)
    arrow(ax, sys_x + sys_w * 0.80, src_y, t3_x + t3_w / 2, task_y + task_h, lw=1.8)

    # ---- Task chaining (depends_on)
    arrow(ax, t1_x + t1_w, task_y + task_h / 2, t2_x, task_y + task_h / 2, lw=2.0)
    arrow(ax, t2_x + t2_w, task_y + task_h / 2, t3_x, task_y + task_h / 2, lw=2.0)

    # ---- Tier 3: Curated tables
    table_y, table_h = 3.75, 1.55
    cce_x, cce_w = 0.7, 3.0
    ocb_x, ocb_w = 3.85, 3.0
    dbu_x, dbu_w = 7.00, 2.8
    tjs_x, tjs_w = 9.95, 3.0
    audit_x, audit_w = 13.15, 2.20

    draw_box(
        ax, cce_x, table_y, cce_w, table_h,
        "dbspend360_\ncloud_cost_explorer",
        "per cluster / day\ncompute | storage | network | other",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10.5, subtitle_size=9,
    )
    draw_box(
        ax, ocb_x, table_y, ocb_w, table_h,
        "dbspend360_\nother_cost_breakdown",
        "per-service detail of\nthe `other` cost bucket",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10.5, subtitle_size=9,
    )
    draw_box(
        ax, dbu_x, table_y, dbu_w, table_h,
        "dbspend360_\ndbu_cost",
        "DBU $ per\ncluster / job / run / day",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10.5, subtitle_size=9,
    )
    draw_box(
        ax, tjs_x, table_y, tjs_w, table_h,
        "dbspend360_\ntotal_job_spends",
        "single source of truth\njob-level cost (cloud + DBU)",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10.5, subtitle_size=9,
    )

    # ---- Supporting tables (stacked on the right, aligned with main row)
    support_h = 0.70
    draw_box(
        ax, audit_x, table_y + table_h - support_h, audit_w, support_h,
        "dbspend360_audit_log",
        "per-task SUCCESS / FAILED",
        fill=PALETTE["support_fill"], edge=PALETTE["support_edge"],
        title_size=10, subtitle_size=8.5,
    )
    draw_box(
        ax, audit_x, table_y, audit_w, support_h,
        "dbspend360_error_log",
        "cloud <-> DBU mismatches",
        fill=PALETTE["support_fill"], edge=PALETTE["support_edge"],
        title_size=10, subtitle_size=8.5,
    )
    ax.text(
        audit_x + audit_w / 2,
        table_y + table_h + 0.05,
        "(written by every task)",
        ha="center", va="bottom",
        fontsize=8.5, style="italic",
        color=PALETTE["subtitle"],
    )

    # ---- Task -> Table arrows (forward only - no curved back-references)
    arrow(ax, t1_x + t1_w * 0.30, task_y, cce_x + cce_w / 2, table_y + table_h, lw=1.6)
    arrow(ax, t1_x + t1_w * 0.75, task_y, ocb_x + ocb_w / 2, table_y + table_h, lw=1.6)
    arrow(ax, t2_x + t2_w / 2, task_y, dbu_x + dbu_w / 2, table_y + table_h, lw=1.6)
    arrow(ax, t3_x + t3_w / 2, task_y, tjs_x + tjs_w / 2, table_y + table_h, lw=1.6)

    # ---- Tier 4: Consumption
    sys_lf_x, sys_lf_w, sys_lf_h = 0.7, 3.2, 1.10
    sys_lf_y = 1.10
    app_x, app_w, app_h = 4.4, 5.4, 1.55
    app_y = 0.85
    llm_x, llm_w, llm_h = 10.2, 5.0, 1.55

    draw_box(
        ax, sys_lf_x, sys_lf_y, sys_lf_w, sys_lf_h,
        "system.lakeflow.jobs",
        "joined at query time\nto resolve job names",
        fill=PALETTE["system_fill"], edge=PALETTE["system_edge"],
        title_size=10.5, subtitle_size=9,
    )
    draw_box(
        ax, app_x, app_y, app_w, app_h,
        "DBSPEND360 Databricks App",
        "FastAPI + React   |   cost dashboards, drill-downs,\ngrouped / job / cluster views",
        fill=PALETTE["consumer_fill"], edge=PALETTE["consumer_edge"],
        title_size=12, subtitle_size=9.5,
    )
    draw_box(
        ax, llm_x, app_y, llm_w, llm_h,
        "Foundation Model\ndatabricks-claude-sonnet-4",
        "AI cost & cluster recommendations\nvia Databricks Model Serving",
        fill=PALETTE["llm_fill"], edge=PALETTE["llm_edge"],
        title_size=12, subtitle_size=9.5,
    )

    # ---- Table -> App arrows
    # total_job_spends -> App (primary feed)
    arrow(ax, tjs_x + tjs_w * 0.40, table_y, app_x + app_w * 0.60, app_y + app_h, lw=1.6)
    # other_cost_breakdown -> App (drill-down, dashed)
    arrow(
        ax, ocb_x + ocb_w / 2, table_y,
        app_x + app_w * 0.25, app_y + app_h,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.2,
    )
    # system.lakeflow.jobs -> App (enrichment, dashed)
    arrow(
        ax, sys_lf_x + sys_lf_w, sys_lf_y + sys_lf_h * 0.55,
        app_x, app_y + app_h * 0.45,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.2,
    )
    # App -> LLM (queries foundation model)
    arrow(ax, app_x + app_w, app_y + app_h / 2, llm_x, app_y + app_h / 2, lw=1.8)

    # ---- Footnote
    ax.text(
        8.0, 0.05,
        "* GCP cost explorer notebook is a stub; AWS and Azure are functional end-to-end today.",
        ha="center", va="center",
        fontsize=8.5, style="italic",
        color=PALETTE["subtitle"],
    )

    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Diagram 2: Implementation Flow
# -----------------------------------------------------------------------------


def render_implementation_flow(path: Path):
    """Strictly centered single-column flow.

    Layout principles:
      * The diagram is a single vertical column with `cx` as the centerline.
      * Every box's horizontal center sits exactly on `cx`.
      * The two output tables of Task 1 are placed symmetrically left and
        right of `cx` so the column stays balanced.
      * Supporting tables (audit + error) live in a soft banner directly
        under the subtitle - this keeps the right margin clean and lets
        `bbox_inches="tight"` produce a horizontally centered crop.
      * The App box's subtitle documents the `other_cost_breakdown`
        drill-down explicitly, so no separate side-arrow is needed
        (an earlier version had one and it broke the centering).
    """
    fig_w, fig_h = 13, 16
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    ax.set_xlim(0, 13)
    ax.set_ylim(-0.6, 15.4)
    ax.set_aspect("equal")
    ax.axis("off")

    cx = 6.5  # canvas centerline -> everything centered uses this

    # Title rendered as ax.text (instead of fig.suptitle) so its horizontal
    # position is tied to the axes content extent, which guarantees centering
    # when bbox_inches="tight" trims the figure.
    ax.text(
        cx, 15.05,
        "DBSPEND360  -  Implementation Flow",
        ha="center", va="center",
        fontsize=18, fontweight="bold",
        color=PALETTE["title"],
    )
    ax.text(
        cx, 14.45,
        "End-to-end ordering of DBSpend360 job tasks, the tables they produce, and the consuming app",
        ha="center", va="center",
        fontsize=11,
        color=PALETTE["subtitle"],
    )

    # Supporting-tables banner (centered under subtitle, drawn as a real
    # rounded rectangle so it reads as a first-class element rather than an
    # afterthought)
    draw_box(
        ax, 1.8, 13.3, 9.4, 0.85,
        "Supporting tables  -  written by every task",
        "dbspend360_audit_log  (per-task SUCCESS / FAILED)   |   "
        "dbspend360_error_log  (cloud <-> DBU mismatches)",
        fill=PALETTE["support_fill"], edge=PALETTE["support_edge"],
        title_size=10.5, subtitle_size=9,
        rounding=0.05, lw=1.2,
    )

    # ---- Centered single-column flow
    # Cloud Provider config
    draw_box(
        ax, 3.0, 11.7, 7.0, 1.0,
        "Cloud Provider selected in config/app.<env>.config",
        "platform = AWS  |  Azure  |  GCP*    ->    drives cloud_provider job parameter",
        fill=PALETTE["source_fill"], edge=PALETTE["source_edge"],
        title_size=11, subtitle_size=9,
    )

    # Task 1
    draw_box(
        ax, 3.0, 9.9, 7.0, 1.4,
        "Task 1   -   cloud_cost_explorer",
        "Runs <cloud_provider>_cloud_cost_explorer_app\n"
        "Reads the cloud's cost API and classifies into compute / storage / network / other",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=12,
    )

    # Two output tables of Task 1 - symmetric left/right of cx
    # Each box width = 5.2; left runs 0.7..5.9, right runs 7.1..12.3
    # -> distance from cx for both inner edges = 0.6, outer edges = 5.8
    draw_box(
        ax, 0.7, 8.2, 5.2, 1.3,
        "dbspend360_cloud_cost_explorer",
        "per cluster / day cloud cost\n(compute, storage, network, other)",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10.5,
    )
    draw_box(
        ax, 7.1, 8.2, 5.2, 1.3,
        "dbspend360_other_cost_breakdown",
        "per-service detail of the\n`other` cost bucket",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10.5,
    )

    # Task 2
    draw_box(
        ax, 3.0, 6.4, 7.0, 1.4,
        "Task 2   -   Dbspend360dbu_costs",
        "Runs dbspend360_dbu_cost_app\n"
        "Joins system.billing.usage + list_prices + system.compute.clusters",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=12,
    )

    # dbu_cost
    draw_box(
        ax, 3.5, 4.9, 6.0, 1.2,
        "dbspend360_dbu_cost",
        "DBU $ per cluster / job / run / day",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=11,
    )

    # Task 3
    draw_box(
        ax, 3.0, 3.2, 7.0, 1.4,
        "Task 3   -   databricks_job_spends",
        "Runs databricks_job_spends_app\n"
        "Inner-joins cloud_cost_explorer with dbu_cost on (cluster_id, date)",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=12,
    )

    # total_job_spends
    draw_box(
        ax, 3.5, 1.7, 6.0, 1.2,
        "dbspend360_total_job_spends",
        "Single source of truth: cloud_cost + databricks_cost = total_cost",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=11,
    )

    # App + AI Insights (full-width final row, centered on cx)
    # Width 9.4 -> x = 1.8..11.2, mirroring the supporting-tables banner above
    draw_box(
        ax, 1.8, 0.0, 9.4, 1.4,
        "DBSPEND360 Databricks App  +  AI Insights",
        "FastAPI + React dashboards on dbspend360_total_job_spends   |   "
        "drill-downs on dbspend360_other_cost_breakdown\n"
        "AI cost & cluster recommendations via databricks-claude-sonnet-4 (Model Serving)",
        fill=PALETTE["consumer_fill"], edge=PALETTE["consumer_edge"],
        title_size=12,
    )

    # ---- Arrows (all centered on cx)
    arrow(ax, cx, 11.7, cx, 11.3, lw=2.2)         # config -> Task 1
    arrow(ax, 5.0, 9.9, 3.4, 9.5, lw=1.8)         # Task 1 -> cloud_cost (left split)
    arrow(ax, 8.0, 9.9, 9.6, 9.5, lw=1.8)         # Task 1 -> other_cost (right split)
    arrow(ax, 3.4, 8.2, 5.4, 7.8, lw=1.8)         # cloud_cost -> Task 2
    arrow(ax, 9.6, 8.2, 7.6, 7.8, lw=1.8)         # other_cost -> Task 2  (joins back to centerline)
    arrow(ax, cx, 6.4, cx, 6.1, lw=2.0)           # Task 2 -> dbu_cost
    arrow(ax, cx, 4.9, cx, 4.6, lw=2.0)           # dbu_cost -> Task 3
    arrow(ax, cx, 3.2, cx, 2.9, lw=2.0)           # Task 3 -> total_job_spends
    arrow(ax, cx, 1.7, cx, 1.4, lw=2.2)           # total_job_spends -> App

    # Footnote (centered)
    ax.text(
        cx, -0.35,
        "* GCP cost explorer notebook is currently a stub; AWS and Azure are functional end-to-end.",
        ha="center", va="center",
        fontsize=8.5,
        style="italic",
        color=PALETTE["subtitle"],
    )

    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    arch_path = OUTPUT_DIR / "architecture.png"
    flow_path = OUTPUT_DIR / "implementation_flow.png"

    print(f"Writing {arch_path}")
    render_architecture(arch_path)

    print(f"Writing {flow_path}")
    render_implementation_flow(flow_path)

    print("Done.")


if __name__ == "__main__":
    main()
