#!/usr/bin/env python3
"""
Mini log analyzer for Loghub-style raw log files.

Usage:
    python log_analyzer.py <logfile>
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig


def build_miner(sim_th: float = 0.5, depth: int = 4) -> TemplateMiner:
    config = TemplateMinerConfig()
    config.drain_sim_th = sim_th
    config.drain_depth = depth
    return TemplateMiner(config=config)


def parse_timestamp(line: str) -> pd.Timestamp:
    parts = line.split()
    if len(parts) < 2:
        return pd.NaT

    # BGL format:
    # label epoch date node timestamp node RAS component severity message
    if len(parts) >= 6 and parts[1].isdigit() and len(parts[1]) == 10:
        return pd.to_datetime(int(parts[1]), unit="s")

    # HDFS format:
    # yymmdd HHMMSS pid level component: message
    if len(parts) >= 2 and len(parts[0]) == 6 and len(parts[1]) == 6:
        ts = pd.to_datetime(parts[0] + parts[1], format="%y%m%d%H%M%S", errors="coerce")
        if pd.notna(ts):
            return ts

    return pd.NaT


def parse_logs(lines: list[str], sim_th: float = 0.5) -> tuple[pd.DataFrame, pd.DataFrame]:
    miner = build_miner(sim_th=sim_th)
    rows = []

    for line_no, line in enumerate(lines, start=1):
        result = miner.add_log_message(line)
        rows.append(
            {
                "line_no": line_no,
                "timestamp": parse_timestamp(line),
                "template_id": result["cluster_id"],
                "log_line": line,
            }
        )

    template_df = pd.DataFrame(
        [
            {
                "template_id": cluster.cluster_id,
                "template": cluster.get_template(),
                "count": cluster.size,
            }
            for cluster in miner.drain.clusters
        ]
    ).sort_values("count", ascending=False)

    template_lookup = dict(zip(template_df["template_id"], template_df["template"]))
    log_df = pd.DataFrame(rows)
    log_df["template"] = log_df["template_id"].map(template_lookup)

    return log_df, template_df.reset_index(drop=True)


def find_last_hour_spikes(log_df: pd.DataFrame, template_lookup: dict[int, str]) -> pd.DataFrame:
    timed_df = log_df.dropna(subset=["timestamp"]).copy()
    if timed_df.empty:
        return pd.DataFrame()

    timed_df["hour"] = timed_df["timestamp"].dt.floor("h")
    last_hour = timed_df["hour"].max()
    baseline_df = timed_df[timed_df["hour"] < last_hour]

    if baseline_df.empty:
        return pd.DataFrame()

    hourly_counts = (
        timed_df.groupby(["hour", "template_id"]).size().unstack(fill_value=0).sort_index()
    )
    baseline_counts = hourly_counts.loc[hourly_counts.index < last_hour]
    last_counts = hourly_counts.loc[last_hour]

    rows = []
    for template_id, last_count in last_counts.items():
        if last_count <= 0:
            continue

        baseline = baseline_counts[template_id].astype(float)
        mean = baseline.mean()
        std = baseline.std(ddof=0)
        threshold = mean + 3 * std

        if std == 0:
            is_spike = last_count > mean and last_count >= 3
            z_score = None
        else:
            is_spike = last_count > threshold
            z_score = (last_count - mean) / std

        if is_spike:
            rows.append(
                {
                    "template_id": template_id,
                    "template": template_lookup.get(template_id, ""),
                    "last_hour_count": int(last_count),
                    "baseline_mean": round(float(mean), 3),
                    "baseline_std": round(float(std), 3),
                    "threshold": round(float(threshold), 3),
                    "z_score": None if z_score is None else round(float(z_score), 3),
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "template_id",
                "template",
                "last_hour_count",
                "baseline_mean",
                "baseline_std",
                "threshold",
                "z_score",
            ]
        )

    return pd.DataFrame(rows).sort_values("last_hour_count", ascending=False)


def find_new_templates_last_hour(log_df: pd.DataFrame, template_lookup: dict[int, str]) -> pd.DataFrame:
    timed_df = log_df.dropna(subset=["timestamp"]).copy()
    if timed_df.empty:
        return pd.DataFrame()

    last_hour_start = timed_df["timestamp"].max().floor("h")
    first_seen = timed_df.groupby("template_id")["timestamp"].min()
    new_ids = first_seen[first_seen >= last_hour_start].index

    rows = []
    for template_id in new_ids:
        rows.append(
            {
                "template_id": template_id,
                "first_seen": first_seen.loc[template_id],
                "template": template_lookup.get(template_id, ""),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["template_id", "first_seen", "template"])

    return pd.DataFrame(rows).sort_values("first_seen")


def print_report(logfile: Path, sim_th: float = 0.5) -> None:
    lines = logfile.read_text(encoding="utf-8", errors="ignore").splitlines()
    log_df, template_df = parse_logs(lines, sim_th=sim_th)
    template_lookup = dict(zip(template_df["template_id"], template_df["template"]))

    total_lines = len(lines)
    unique_templates = len(template_df)

    print(f"Log file: {logfile}")
    print(f"Total lines: {total_lines:,}")
    print(f"Unique templates: {unique_templates:,}")
    print()

    print("Top-5 templates:")
    for _, row in template_df.head(5).iterrows():
        pct = (row["count"] / total_lines * 100) if total_lines else 0
        print(f"- [{int(row['template_id'])}] count={int(row['count']):,} ({pct:.2f}%): {row['template']}")
    print()

    spike_df = find_last_hour_spikes(log_df, template_lookup)
    print("Templates spiking in the latest hour:")
    if spike_df.empty:
        print("- None detected")
    else:
        for _, row in spike_df.head(10).iterrows():
            z = "n/a" if pd.isna(row["z_score"]) else row["z_score"]
            print(
                f"- [{int(row['template_id'])}] last_hour_count={int(row['last_hour_count'])}, "
                f"baseline_mean={row['baseline_mean']}, z={z}: {row['template']}"
            )
    print()

    new_df = find_new_templates_last_hour(log_df, template_lookup)
    print("New templates in the latest hour:")
    if new_df.empty:
        print("- None detected")
    else:
        for _, row in new_df.head(10).iterrows():
            print(f"- [{int(row['template_id'])}] first_seen={row['first_seen']}: {row['template']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mini Drain3 log analyzer")
    parser.add_argument("logfile", type=Path, help="Path to a raw log file")
    parser.add_argument("--sim-th", type=float, default=0.5, help="Drain3 similarity threshold")
    args = parser.parse_args()

    if not args.logfile.exists():
        raise SystemExit(f"File not found: {args.logfile}")

    print_report(args.logfile, sim_th=args.sim_th)


if __name__ == "__main__":
    main()
