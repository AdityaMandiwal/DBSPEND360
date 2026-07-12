"""
Regenerate the architecture and implementation-flow diagrams used in README.md.

Outputs:
    release/readme_images/architecture_pipeline.png
    release/readme_images/architecture_data_app.png
    release/readme_images/implementation_flow.png

Run with:
    uv run --no-project --with matplotlib python claude_scripts/generate_readme_diagrams.py
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
    "rollup_fill": "#D4EDDA",
    "rollup_edge": "#1B5E20",
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
    "branch_job": "#FF6F1A",
    "branch_ap": "#1565C0",
    "branch_pool": "#2E7D32",
    "branch_pipeline": "#6A1B9A",
}

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "release" / "readme_images"

BRANCHES = [
    {
        "label": "Job Clusters",
        "tab": "Job Clusters",
        "color": PALETTE["branch_job"],
        "dbu_task": "Dbspend360dbu_costs",
        "rollup_task": "databricks_job_spends",
        "dbu_table": "dbspend360_\ndbu_cost",
        "rollup_table": "dbspend360_\ntotal_job_spends",
        "cloud_dep": True,
        "cloud_source": "cluster",
    },
    {
        "label": "All-Purpose",
        "tab": "All-Purpose",
        "color": PALETTE["branch_ap"],
        "dbu_task": "Dbspend360_all_purpose_dbu_costs",
        "rollup_task": "all_purpose_spends",
        "dbu_table": "dbspend360_all_purpose_\ndbu_cost",
        "rollup_table": "dbspend360_total_\nall_purpose_spends",
        "cloud_dep": True,
        "cloud_source": "cluster",
    },
    {
        "label": "Instance Pools",
        "tab": "Instance Pools",
        "color": PALETTE["branch_pool"],
        "dbu_task": "Dbspend360_pool_dbu_costs",
        "rollup_task": "pool_spends",
        "dbu_table": "dbspend360_\npool_dbu_cost",
        "rollup_table": "dbspend360_\ntotal_pool_spends",
        "cloud_dep": True,
        "cloud_source": "pool",
    },
    {
        "label": "Pipeline Compute",
        "tab": "Pipeline",
        "color": PALETTE["branch_pipeline"],
        "dbu_task": "Dbspend360_pipeline_dbu_costs",
        "rollup_task": "pipeline_spends",
        "dbu_table": "dbspend360_\npipeline_dbu_cost",
        "rollup_table": "dbspend360_\ntotal_pipeline_spends",
        "cloud_dep": False,
        "rollup_cloud_dep": True,
        "cloud_source": "cluster",
    },
]


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


def draw_lane(
    ax,
    x,
    y,
    w,
    h,
    label: str | None,
    label_position: str = "above",
    label_offset: float = 0.22,
):
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
    if not label:
        return
    if label_position == "inside":
        label_y = y + h - 0.30
        label_va = "top"
    else:
        label_y = y + h + label_offset
        label_va = "center"
    ax.text(
        x + 0.25,
        label_y,
        label,
        ha="left",
        va=label_va,
        fontsize=11.5,
        fontweight="bold",
        color=PALETTE["title"],
        bbox=dict(facecolor="white", edgecolor="none", pad=3),
        zorder=10,
    )


def draw_branch_column(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    color: str,
    label_gap: float = 0.70,
    show_label: bool = True,
):
    """Tinted column lane; optional branch label rendered above the lane top."""
    lane = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.01,rounding_size=0.04",
        linewidth=1.4,
        edgecolor=color,
        facecolor="#FFFFFF",
        alpha=0.55,
        zorder=1,
    )
    ax.add_patch(lane)
    if show_label:
        ax.text(
            x + w / 2,
            y + h + label_gap,
            label,
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            color=color,
            bbox=dict(facecolor="white", edgecolor="none", pad=2),
            zorder=10,
        )


def draw_branch_heading(ax, x: float, y: float, text: str, color: str, va: str = "bottom"):
    """Standalone branch heading; default anchors the bottom edge at *y*."""
    ax.text(
        x,
        y,
        text,
        ha="center",
        va=va,
        fontsize=10,
        fontweight="bold",
        color=color,
        bbox=dict(facecolor="white", edgecolor=color, boxstyle="round,pad=0.22", linewidth=1.2),
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


def draw_tab_pill(ax, x: float, y: float, w: float, h: float, label: str, color: str):
    """Small colored tab chip used in the consumption layer."""
    pill = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.01,rounding_size=0.03",
        linewidth=1.8,
        edgecolor=color,
        facecolor="#FFFFFF",
        zorder=3,
    )
    ax.add_patch(pill)
    ax.text(
        x + w / 2,
        y + h / 2,
        label,
        ha="center",
        va="center",
        fontsize=8,
        fontweight="bold",
        color=color,
        zorder=4,
    )


def draw_legend(ax, x: float, y: float, items: list[tuple[str, str, str]]):
    """Compact line-style legend: [(label, linestyle, color), ...]."""
    for i, (label, style, color) in enumerate(items):
        ly = y - i * 0.28
        ax.plot([x, x + 0.55], [ly, ly], color=color, linestyle=style, linewidth=1.6, zorder=5)
        ax.text(
            x + 0.65,
            ly,
            label,
            ha="left",
            va="center",
            fontsize=8,
            color=PALETTE["subtitle"],
            zorder=5,
        )


# -----------------------------------------------------------------------------
# Diagram 1a: Pipeline architecture (sources + 9-task DAG)
# -----------------------------------------------------------------------------


def render_architecture_pipeline(path: Path):
    """Sources and the nine-task / four-branch pipeline DAG."""
    fig_w, fig_h = 20, 13
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 13)
    ax.set_aspect("equal")
    ax.axis("off")

    cx = 10.0
    margin = 0.5
    lane_w = fig_w - 2 * margin
    lane_x = margin

    # Center the four branch columns on the canvas.
    col_w = 4.4
    col_gap = 0.35
    col_span = len(BRANCHES) * col_w + (len(BRANCHES) - 1) * col_gap
    col_x0 = (fig_w - col_span) / 2

    # Center the two source boxes with a fixed gap between them.
    src_w_left, src_w_right = 8.5, 8.7
    src_gap = 1.0
    src_span = src_w_left + src_gap + src_w_right
    src_x_left = (fig_w - src_span) / 2
    src_x_right = src_x_left + src_w_left + src_gap

    ax.text(
        cx,
        12.55,
        "DBSPEND360  -  Pipeline Architecture",
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=PALETTE["title"],
    )
    ax.text(
        cx,
        12.05,
        "Data sources and the nine-task Databricks Job DAG (four independent branches)",
        ha="center",
        va="center",
        fontsize=11,
        color=PALETTE["subtitle"],
    )

    # Section 1 label sits above the lane; section 2 label stays inside (no overlap there).
    src_lane_y, src_lane_h = 10.35, 1.18
    pipe_lane_y, pipe_lane_h = 1.45, 8.45

    draw_lane(ax, lane_x, src_lane_y, lane_w, src_lane_h, "1. Data Sources", label_position="above", label_offset=0.14)
    draw_lane(
        ax,
        lane_x,
        pipe_lane_y,
        lane_w,
        pipe_lane_h,
        "2. DBSpend360 Pipeline",
        label_position="inside",
    )

    src_y, src_h = src_lane_y + 0.14, src_lane_h - 0.22
    draw_box(
        ax, src_x_left, src_y, src_w_left, src_h,
        "Cloud Cost Explorer APIs",
        "AWS  |  Azure  |  GCP Cloud Billing*",
        fill=PALETTE["source_fill"], edge=PALETTE["source_edge"],
        title_size=11, subtitle_size=9,
    )
    draw_box(
        ax, src_x_right, src_y, src_w_right, src_h,
        "Databricks System Tables",
        "billing.usage  |  list_prices  |  compute.clusters",
        fill=PALETTE["system_fill"], edge=PALETTE["system_edge"],
        title_size=11, subtitle_size=9,
    )

    cloud_w, cloud_h = 7.5, 1.05
    cloud_x = cx - cloud_w / 2
    cloud_y = 8.85
    draw_box(
        ax, cloud_x, cloud_y, cloud_w, cloud_h,
        "cloud_cost_explorer",
        "<provider>_cloud_cost_explorer_app",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=11, subtitle_size=9,
    )

    task_h = 1.05
    heading_y = 7.55
    dbu_y = 5.55
    rollup_y = 3.85
    lane_y = rollup_y
    lane_h = dbu_y + task_h - rollup_y

    col_centers: list[float] = []
    for i, branch in enumerate(BRANCHES):
        col_x = col_x0 + i * (col_w + col_gap)
        col_cx = col_x + col_w / 2
        col_centers.append(col_cx)

        draw_branch_heading(ax, col_cx, heading_y, branch["label"], branch["color"], va="center")
        draw_branch_column(
            ax, col_x, lane_y, col_w, lane_h, branch["label"], branch["color"], show_label=False,
        )
        draw_box(
            ax, col_x, dbu_y, col_w, task_h,
            branch["dbu_task"], "DBU notebook",
            fill=PALETTE["task_fill"], edge=branch["color"],
            title_size=9.5, subtitle_size=8, lw=2.0,
        )
        draw_box(
            ax, col_x, rollup_y, col_w, task_h,
            branch["rollup_task"], "rollup notebook",
            fill=PALETTE["task_fill"], edge=branch["color"],
            title_size=9.5, subtitle_size=8, lw=2.0,
        )
        arrow(ax, col_cx, dbu_y, col_cx, rollup_y + task_h, lw=1.6)

    # Source -> cloud_cost_explorer
    arrow(ax, src_x_left + src_w_left / 2, src_y, cx, cloud_y + cloud_h, lw=1.6)
    arrow(
        ax, src_x_right + src_w_right / 2, src_y, cx, cloud_y + cloud_h,
        lw=1.6, rad=-0.12,
    )

    # cloud_cost_explorer -> three cloud-dependent DBU tasks
    for i in range(3):
        arrow(ax, cx, cloud_y, col_centers[i], dbu_y + task_h, lw=1.5, rad=0.06 * (i - 1))

    # cloud_cost_explorer -> pipeline_spends (rollup only)
    arrow(
        ax, cx + cloud_w * 0.35, cloud_y, col_centers[3], rollup_y + task_h,
        lw=1.4, rad=-0.12,
    )

    # system tables -> pipeline_dbu_costs (independent DBU task)
    arrow(
        ax, src_x_right + src_w_right / 2, src_y, col_centers[3], dbu_y + task_h,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.3, rad=0.18,
    )

    draw_legend(
        ax,
        lane_x + 0.05,
        2.55,
        [
            ("task dependency", "-", PALETTE["arrow"]),
            ("reads system tables (no upstream task)", (0, (4, 3)), PALETTE["arrow_dashed"]),
        ],
    )

    ax.text(
        col_centers[3],
        rollup_y - 0.22,
        "Pipeline branch: DBU task has no cloud_cost_explorer dependency;\n"
        "rollup notebook joins cloud_cost_explorer output.",
        ha="center",
        va="top",
        fontsize=7.5,
        color=PALETTE["branch_pipeline"],
        bbox=dict(facecolor="white", edgecolor=PALETTE["branch_pipeline"], boxstyle="round,pad=0.25", linewidth=1.0),
        zorder=5,
    )

    ax.text(
        cx,
        0.55,
        "* GCP cost explorer notebook is a stub; AWS and Azure are functional end-to-end today.",
        ha="center",
        va="center",
        fontsize=8.5,
        style="italic",
        color=PALETTE["subtitle"],
    )
    ax.text(
        cx,
        1.05,
        "Branches are independent — a failure in one does not block the others.",
        ha="center",
        va="center",
        fontsize=9,
        color=PALETTE["subtitle"],
    )

    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Diagram 1b: Data tables + app consumption
# -----------------------------------------------------------------------------


def render_architecture_data_app(path: Path):
    """Curated Delta tables and how the four-tab app consumes them."""
    fig_w, fig_h = 20, 13.5
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 13.5)
    ax.set_aspect("equal")
    ax.axis("off")

    cx = 10.0
    ax.text(
        cx,
        13.05,
        "DBSPEND360  -  Data & Consumption",
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=PALETTE["title"],
    )
    ax.text(
        cx,
        12.55,
        "Curated Unity Catalog tables and the four-tab Databricks App + AI insights",
        ha="center",
        va="center",
        fontsize=11,
        color=PALETTE["subtitle"],
    )

    draw_lane(ax, 0.4, 9.55, 19.2, 2.15, "1. Shared tables  (from cloud_cost_explorer)", label_offset=0.20)
    draw_lane(ax, 0.4, 5.85, 19.2, 3.45, "2. Branch tables  (one pair + rollup per tab)", label_offset=0.20)
    draw_lane(ax, 0.4, 0.45, 19.2, 5.15, "3. Consumption", label_offset=0.20)

    shared_y, tbl_h = 9.85, 1.35
    cluster_cloud_x, cluster_cloud_w = 0.6, 5.8
    pool_cloud_x, pool_cloud_w = 6.9, 5.8
    other_x, other_w = 13.2, 5.8

    draw_box(
        ax, cluster_cloud_x, shared_y, cluster_cloud_w, tbl_h,
        "dbspend360_\ncloud_cost_explorer", "ClusterId tag\nJob / AP / Pipeline",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10, subtitle_size=8.5,
    )
    draw_box(
        ax, pool_cloud_x, shared_y, pool_cloud_w, tbl_h,
        "dbspend360_pool_\ncloud_cost_explorer", "InstancePoolId tag\nInstance Pools",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10, subtitle_size=8.5,
    )
    draw_box(
        ax, other_x, shared_y, other_w, tbl_h,
        "dbspend360_\nother_cost_breakdown", "per-service `other`\ndrill-down",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=10, subtitle_size=8.5,
    )

    ax.text(
        10.0, 9.62,
        "dbspend360_audit_log  +  dbspend360_error_log  (written by every task)",
        ha="center", va="center", fontsize=8.5, style="italic", color=PALETTE["subtitle"],
    )

    branch_tbl_y = 7.45
    col_w = 4.4
    col_gap = 0.35
    col_x0 = 0.55
    tbl_pair_h = 1.10
    rollup_tbl_y = 6.15

    branch_centers: list[float] = []
    rollup_positions: list[tuple[float, float, float, dict]] = []
    for i, branch in enumerate(BRANCHES):
        col_x = col_x0 + i * (col_w + col_gap)
        col_cx = col_x + col_w / 2
        branch_centers.append(col_cx)

        draw_branch_heading(ax, col_cx, 8.95, branch["label"], branch["color"], va="center")
        draw_branch_column(
            ax, col_x, 6.0, col_w, 2.80, branch["label"], branch["color"], show_label=False,
        )
        draw_box(
            ax, col_x, branch_tbl_y, col_w, tbl_pair_h,
            branch["dbu_table"], None,
            fill=PALETTE["table_fill"], edge=branch["color"],
            title_size=8.5, lw=1.6,
        )
        draw_box(
            ax, col_x, rollup_tbl_y, col_w, tbl_pair_h,
            branch["rollup_table"], "rollup table",
            fill=PALETTE["rollup_fill"], edge=branch["color"],
            title_size=8.5, subtitle_size=7.5, lw=2.0,
        )
        rollup_positions.append((col_cx, rollup_tbl_y, col_w, branch))

        cloud_src = branch.get("cloud_source")
        if cloud_src == "pool":
            arrow(
                ax, pool_cloud_x + pool_cloud_w / 2, shared_y, col_cx, rollup_tbl_y + tbl_pair_h,
                color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.1, rad=0.08,
            )
        elif cloud_src == "cluster":
            arrow(
                ax, cluster_cloud_x + cluster_cloud_w / 2, shared_y, col_cx, rollup_tbl_y + tbl_pair_h,
                color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.0, rad=0.05 * (i - 1.5),
            )

    # --- Consumption layer ---
    pill_w = 3.55
    pill_h = 0.55
    pill_y = 4.35
    app_x, app_w, app_h = 4.35, 11.3, 1.45
    app_y = 2.05
    app_top = app_y + app_h

    for col_cx, _ry, col_w_actual, branch in rollup_positions:
        pill_x = col_cx - pill_w / 2
        draw_tab_pill(ax, pill_x, pill_y, pill_w, pill_h, branch["tab"], branch["color"])
        arrow(ax, col_cx, rollup_tbl_y, col_cx, pill_y + pill_h, lw=1.4)
        arrow(ax, col_cx, pill_y, col_cx, app_top, lw=1.4)

    draw_box(
        ax, app_x, app_y, app_w, app_h,
        "DBSPEND360 Databricks App",
        "SQL warehouse queries  |  four cost tabs  |  dashboards  |  drill-down panels",
        fill=PALETTE["consumer_fill"], edge=PALETTE["consumer_edge"],
        title_size=12, subtitle_size=9,
    )

    enrich_x, enrich_w, enrich_h = 0.55, 3.45, 2.35
    enrich_y = 1.55
    draw_box(
        ax, enrich_x, enrich_y, enrich_w, enrich_h,
        "Query-time enrichment",
        "system.lakeflow.jobs  |  system.compute.clusters\n"
        "system.compute.instance_pools  |  system.lakeflow.pipelines",
        fill=PALETTE["system_fill"], edge=PALETTE["system_edge"],
        title_size=9.5, subtitle_size=7.5,
    )
    arrow(
        ax, enrich_x + enrich_w, enrich_y + enrich_h / 2, app_x, app_y + app_h * 0.55,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.2,
    )

    drill_w, drill_h = 2.8, 0.62
    drill_x = 16.55
    drill_y = 3.55
    draw_box(
        ax, drill_x, drill_y, drill_w, drill_h,
        "other\ndrill-down", None,
        fill="#FFFFFF", edge=PALETTE["table_edge"],
        title_size=8, lw=1.4,
    )
    arrow(
        ax, other_x + other_w / 2, shared_y, drill_x + drill_w / 2, drill_y + drill_h,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.0, rad=-0.15,
    )
    arrow(
        ax, drill_x, drill_y + drill_h / 2, app_x + app_w, app_y + app_h * 0.72,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.0,
    )

    llm_x, llm_w = 16.15, 3.55
    draw_box(
        ax, llm_x, app_y, llm_w, app_h,
        "Foundation Model\ndatabricks-claude-sonnet-4",
        "AI recommendations\nvia Model Serving",
        fill=PALETTE["llm_fill"], edge=PALETTE["llm_edge"],
        title_size=11, subtitle_size=9,
    )
    arrow(ax, app_x + app_w, app_y + app_h / 2, llm_x, app_y + app_h / 2, lw=1.8)

    draw_legend(
        ax,
        0.55,
        0.95,
        [
            ("rollup table -> app tab", "-", PALETTE["arrow"]),
            ("cloud explorer join / drill-down / enrichment", (0, (4, 3)), PALETTE["arrow_dashed"]),
        ],
    )

    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Diagram 2: Implementation Flow
# -----------------------------------------------------------------------------


def render_implementation_flow(path: Path):
    """Nine-task / four-branch DAG consumed by the four-tab app."""
    fig_w, fig_h = 20, 16
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    ax.set_xlim(0, 20)
    ax.set_ylim(0, fig_h)
    ax.set_aspect("equal")
    ax.axis("off")

    cx = 10.0

    # Uniform vertical rhythm — top-down placement keeps title flush with content.
    V_GAP = 0.28
    TASK_H = 1.05
    TBL_H = 0.95
    CLOUD_H = 1.10
    CONFIG_H = 0.85
    SUPPORT_H = 0.70
    APP_H = 1.45
    HEADING_H = 0.38

    title_y = fig_h - 0.45
    subtitle_y = fig_h - 0.95

    support_y = subtitle_y - 0.40 - SUPPORT_H
    config_y = support_y - V_GAP - CONFIG_H
    cloud_y = config_y - V_GAP - CLOUD_H
    tbl_y = cloud_y - V_GAP - TBL_H
    heading_y = tbl_y - V_GAP - HEADING_H  # bottom edge of heading pill, va="bottom"
    dbu_y = heading_y - V_GAP - TASK_H
    dbu_top = dbu_y + TASK_H
    rollup_task_y = dbu_y - V_GAP - TASK_H
    dbu_tbl_y = rollup_task_y - V_GAP - TBL_H
    rollup_tbl_y = dbu_tbl_y - V_GAP - TBL_H
    app_y = rollup_tbl_y - V_GAP - APP_H
    app_top = app_y + APP_H

    lane_y = rollup_tbl_y
    lane_h = dbu_top - rollup_tbl_y

    ax.text(
        cx, title_y,
        "DBSPEND360  -  Implementation Flow",
        ha="center", va="center",
        fontsize=17, fontweight="bold", color=PALETTE["title"],
    )
    ax.text(
        cx, subtitle_y,
        "Nine job tasks, shared cloud ingest, four rollup tables for the app tabs",
        ha="center", va="center",
        fontsize=10, color=PALETTE["subtitle"],
    )

    draw_box(
        ax, 2.5, support_y, 15.0, SUPPORT_H,
        "Supporting tables  -  written by every task",
        "dbspend360_audit_log  |  dbspend360_error_log",
        fill=PALETTE["support_fill"], edge=PALETTE["support_edge"],
        title_size=10, subtitle_size=9, rounding=0.05, lw=1.2,
    )
    draw_box(
        ax, 4.0, config_y, 12.0, CONFIG_H,
        "Cloud Provider in config/app.<env>.config",
        "platform = AWS | Azure | GCP*  ->  cloud_provider job parameter",
        fill=PALETTE["source_fill"], edge=PALETTE["source_edge"],
        title_size=10.5, subtitle_size=9,
    )
    draw_box(
        ax, 5.5, cloud_y, 9.0, CLOUD_H,
        "cloud_cost_explorer",
        "Runs <cloud_provider>_cloud_cost_explorer_app\n"
        "writes cloud_cost_explorer + pool_cloud_cost_explorer + other_cost_breakdown",
        fill=PALETTE["task_fill"], edge=PALETTE["task_edge"],
        title_size=11.5, subtitle_size=9,
    )

    tbl_w = 5.5
    draw_box(
        ax, 0.5, tbl_y, tbl_w, TBL_H,
        "dbspend360_cloud_cost_explorer", "ClusterId tag",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=9.5, subtitle_size=8.5,
    )
    draw_box(
        ax, 7.25, tbl_y, tbl_w, TBL_H,
        "dbspend360_pool_cloud_cost_explorer", "DatabricksInstancePoolId tag",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=9.5, subtitle_size=8.5,
    )
    draw_box(
        ax, 14.0, tbl_y, tbl_w, TBL_H,
        "dbspend360_other_cost_breakdown", "per-service `other` bucket",
        fill=PALETTE["table_fill"], edge=PALETTE["table_edge"],
        title_size=9.5, subtitle_size=8.5,
    )

    col_w = 4.5
    col_gap = 0.35
    col_x0 = 0.5

    branch_centers: list[float] = []
    for branch in BRANCHES:
        col_x = col_x0 + len(branch_centers) * (col_w + col_gap)
        col_cx = col_x + col_w / 2
        branch_centers.append(col_cx)

        draw_branch_heading(ax, col_cx, heading_y, branch["label"], branch["color"])
        draw_branch_column(
            ax, col_x, lane_y, col_w, lane_h, branch["label"], branch["color"], show_label=False,
        )
        draw_box(
            ax, col_x, dbu_y, col_w, TASK_H,
            branch["dbu_task"], "DBU notebook",
            fill=PALETTE["task_fill"], edge=branch["color"],
            title_size=9, subtitle_size=8, lw=2.0,
        )
        draw_box(
            ax, col_x, rollup_task_y, col_w, TASK_H,
            branch["rollup_task"], "rollup notebook",
            fill=PALETTE["task_fill"], edge=branch["color"],
            title_size=9, subtitle_size=8, lw=2.0,
        )
        draw_box(
            ax, col_x, dbu_tbl_y, col_w, TBL_H,
            branch["dbu_table"], None,
            fill=PALETTE["table_fill"], edge=branch["color"],
            title_size=8, lw=1.6,
        )
        draw_box(
            ax, col_x, rollup_tbl_y, col_w, TBL_H,
            branch["rollup_table"], "rollup table",
            fill=PALETTE["rollup_fill"], edge=branch["color"],
            title_size=8, subtitle_size=7.5, lw=2.0,
        )

    draw_box(
        ax, 1.5, app_y, 17.0, APP_H,
        "DBSPEND360 Databricks App  +  AI Insights",
        "Four tabs: Job Clusters | All-Purpose Clusters | Instance Pools | Pipeline Compute\n"
        "each reads its rollup table; other_cost_breakdown for drill-down; "
        "databricks-claude-sonnet-4 for recommendations",
        fill=PALETTE["consumer_fill"], edge=PALETTE["consumer_edge"],
        title_size=11.5, subtitle_size=9,
    )

    # Arrows — endpoints derived from the same layout constants
    arrow(ax, cx, config_y, cx, cloud_y + CLOUD_H, lw=2.0)
    arrow(ax, cx, cloud_y, cx, tbl_y + TBL_H, lw=2.0)
    arrow(ax, 7.5, cloud_y, 3.25, tbl_y + TBL_H, lw=1.5)
    arrow(ax, 10.0, cloud_y, 10.0, tbl_y + TBL_H, lw=1.5)
    arrow(ax, 12.5, cloud_y, 16.75, tbl_y + TBL_H, lw=1.5)

    for i in range(3):
        arrow(ax, 10.0, cloud_y, branch_centers[i], dbu_top, lw=1.5, rad=0.05 * (i - 1))

    ax.text(18.6, dbu_y + 0.35, "system\nbilling", ha="center", fontsize=7.5, color=PALETTE["system_edge"])
    arrow(
        ax, 18.6, dbu_y + 0.55, branch_centers[3], dbu_top,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.3, rad=-0.2,
    )

    for col_cx in branch_centers:
        arrow(ax, col_cx, dbu_y, col_cx, rollup_task_y + TASK_H, lw=1.5)
        arrow(ax, col_cx, rollup_task_y, col_cx, dbu_tbl_y + TBL_H, lw=1.5)
        arrow(ax, col_cx, dbu_tbl_y, col_cx, rollup_tbl_y + TBL_H, lw=1.5)

    arrow(ax, 10.0, cloud_y, branch_centers[3], rollup_task_y + TASK_H, lw=1.4, rad=-0.15)
    arrow(
        ax, 10.0, tbl_y, branch_centers[2], rollup_task_y + TASK_H,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.2, rad=0.1,
    )

    for col_cx in branch_centers:
        arrow(ax, col_cx, rollup_tbl_y, col_cx, app_top, lw=1.5)
    arrow(
        ax, 16.75, tbl_y, 15.5, app_top,
        color=PALETTE["arrow_dashed"], style=(0, (4, 3)), lw=1.1, rad=0.2,
    )

    footnote_y = app_y - 0.30
    ax.text(
        cx, footnote_y,
        "Branches are independent — a failure in one does not block the others.",
        ha="center", va="center", fontsize=9, color=PALETTE["subtitle"],
    )
    ax.text(
        cx, footnote_y - 0.38,
        "* GCP cost explorer notebook is currently a stub; AWS and Azure are functional end-to-end.",
        ha="center", va="center", fontsize=8.5, style="italic", color=PALETTE["subtitle"],
    )

    # Crop axes to content so the title sits at the top and footnotes hug the bottom.
    ax.set_ylim(footnote_y - 0.55, fig_h)
    ax.set_xlim(0.2, 19.8)

    fig.savefig(path, bbox_inches="tight", pad_inches=0.12, facecolor="white")
    plt.close(fig)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pipeline_path = OUTPUT_DIR / "architecture_pipeline.png"
    data_app_path = OUTPUT_DIR / "architecture_data_app.png"
    flow_path = OUTPUT_DIR / "implementation_flow.png"

    print(f"Writing {pipeline_path}")
    render_architecture_pipeline(pipeline_path)

    print(f"Writing {data_app_path}")
    render_architecture_data_app(data_app_path)

    print(f"Writing {flow_path}")
    render_implementation_flow(flow_path)

    print("Done.")


if __name__ == "__main__":
    main()
