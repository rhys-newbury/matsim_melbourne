#!/usr/bin/env python3
"""
Differentiable optimization of road-policy placement to minimize overloaded roads.

Greedily selects K roads. At each round, it optimizes a differentiable soft
road-selection vector through a frozen MATSim GNN surrogate, then commits the
best road with argmax and repeats.

Objective:
    Minimize a smooth approximation of the number of overloaded links:

        overload_i = predicted_volume_i / capacity_i - threshold
        soft_count = sum(sigmoid(sharpness * overload_i))

After each committed road, the script records the hard overloaded-road count:

        hard_count = sum(predicted_volume_i / capacity_i > threshold)

This is usually more meaningful than minimizing total predicted volume change,
because it directly targets network bottlenecks.

Example:
    python optimize.py \
        --run-path data/TR-C_Benchmarks/te_gnn_2_3_pos \
        --data-index 0 \
        --policy-feature-idx 0 \
        --base-volume-feature-idx 3 \
        --capacity-feature-idx 4 \
        --policy-value -0.5 \
        --num-roads 10 \
        --output-csv optimized_overloaded_roads.csv \
        --output-plot overloaded_roads_over_time.png

Important:
    - --policy-feature-idx is the feature column modified by the intervention,
      e.g. capacity_reduction.
    - --base-volume-feature-idx should point to the baseline car-volume feature.
    - --capacity-feature-idx should point to the physical road-capacity feature.
    - The script assumes the surrogate output is predicted car-volume CHANGE.
      If your model outputs absolute car volume, pass --model-output absolute_volume.
"""

from __future__ import annotations

import argparse
import copy
import os
from dataclasses import dataclass
from typing import Optional

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

try:
    from torch_geometric.profile import count_parameters
except Exception:  # pragma: no cover
    count_parameters = None

from ml_surrogates.gnn.models.trans_encoder import TransEncoder


@dataclass
class PickResult:
    round_id: int
    road_idx: int
    soft_overloaded_count: float
    hard_overloaded_count: int
    max_volume_capacity_ratio: float
    mean_volume_capacity_ratio: float
    logit_score: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--run-path", required=True)
    p.add_argument("--model-path", default=None)
    p.add_argument("--data-path", default=None)
    p.add_argument("--scaler-x-path", default=None)
    p.add_argument("--data-index", type=int, default=0)

    # Feature indices in data.x.
    p.add_argument("--policy-feature-idx", type=int, default=2)
    p.add_argument("--base-volume-feature-idx", type=int, default=0)
    p.add_argument("--capacity-feature-idx", type=int, default=1)

    p.add_argument("--policy-value", type=float, default=-0.5)
    p.add_argument("--baseline-policy-value", type=float, default=0.0)
    p.add_argument("--num-roads", type=int, default=10)

    p.add_argument(
        "--model-output",
        choices=["change", "absolute_volume"],
        default="change",
        help="Whether model(data) predicts volume change or absolute volume.",
    )
    p.add_argument(
        "--overload-threshold",
        type=float,
        default=1.0,
        help="A road is overloaded when predicted_volume / capacity > this value.",
    )
    p.add_argument(
        "--sigmoid-sharpness",
        type=float,
        default=30.0,
        help="Higher values make the soft overload count closer to the hard count.",
    )
    p.add_argument("--capacity-eps", type=float, default=1e-6)

    p.add_argument("--steps", type=int, default=400)
    p.add_argument("--lr", type=float, default=0.05)
    p.add_argument("--temperature", type=float, default=0.10)
    p.add_argument("--entropy-weight", type=float, default=1e-4)
    p.add_argument("--seed", type=int, default=42)

    p.add_argument("--candidate-indices-csv", default=None)
    p.add_argument("--metadata-csv", default=None)
    p.add_argument("--candidate-highways", nargs="*", default=None)

    # Model hyperparameters. Match these to the trained checkpoint.
    p.add_argument("--embed-dim", type=int, default=192)
    p.add_argument("--ff-dim", type=int, default=768)
    p.add_argument("--num-layers", type=int, default=3)
    p.add_argument("--use-pos", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument(
        "--use-graph-conv", action=argparse.BooleanOptionalAction, default=True
    )
    p.add_argument("--num-graph-conv-layers", type=int, default=2)

    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--output-csv", default="optimized_overloaded_roads.csv")
    p.add_argument("--output-plot", default="overloaded_roads_over_time.png")
    return p.parse_args()


def load_model(args: argparse.Namespace, device: torch.device) -> torch.nn.Module:
    model = TransEncoder(
        embed_dim=args.embed_dim,
        ff_dim=args.ff_dim,
        num_layers=args.num_layers,
        use_pos=args.use_pos,
        use_graph_conv=args.use_graph_conv,
        num_graph_conv_layers=args.num_graph_conv_layers,
    )
    model_path = args.model_path or os.path.join(
        args.run_path, "trained_model", "model.pth"
    )
    state = torch.load(model_path, map_location=device)
    model.load_state_dict(state)
    model.to(device).eval()
    for param in model.parameters():
        param.requires_grad_(False)
    if count_parameters is not None:
        print(f"Loaded model with {count_parameters(model) / 1e6:.2f}M parameters.")
    return model


def load_graph(args: argparse.Namespace, device: torch.device):
    data_path = args.data_path or os.path.join(
        args.run_path, "data_created_during_training", "test_dl.pt"
    )
    dataset = torch.load(data_path, map_location="cpu")
    data = copy.deepcopy(dataset[args.data_index])
    return data.to(device)


def scaled_feature_value(scaler, feature_idx: int, raw_value: float) -> float:
    if hasattr(scaler, "mean_") and hasattr(scaler, "scale_"):
        return float(
            (raw_value - scaler.mean_[feature_idx]) / scaler.scale_[feature_idx]
        )
    dummy = np.zeros((1, getattr(scaler, "n_features_in_", feature_idx + 1)))
    dummy[0, feature_idx] = raw_value
    return float(scaler.transform(dummy)[0, feature_idx])


def unscale_feature_tensor(
    x_scaled: torch.Tensor, scaler, feature_idx: int
) -> torch.Tensor:
    """Return one feature from data.x in raw units while preserving gradients where possible."""
    col = x_scaled[:, feature_idx]
    if hasattr(scaler, "mean_") and hasattr(scaler, "scale_"):
        mean = torch.as_tensor(
            float(scaler.mean_[feature_idx]),
            device=x_scaled.device,
            dtype=x_scaled.dtype,
        )
        scale = torch.as_tensor(
            float(scaler.scale_[feature_idx]),
            device=x_scaled.device,
            dtype=x_scaled.dtype,
        )
        return col * scale + mean
    raise ValueError(
        "Only StandardScaler-style scalers are supported for differentiable unscaling."
    )


def build_candidate_indices(args: argparse.Namespace, data) -> torch.Tensor:
    n = data.x.size(0)
    candidates = np.arange(n, dtype=np.int64)

    if args.candidate_indices_csv:
        df = pd.read_csv(args.candidate_indices_csv)
        if "road_idx" not in df.columns:
            raise ValueError("candidate-indices-csv must contain a 'road_idx' column.")
        candidates = df["road_idx"].to_numpy(dtype=np.int64)

    if args.metadata_csv and args.candidate_highways:
        meta = pd.read_csv(args.metadata_csv)
        if "road_idx" not in meta.columns:
            meta = meta.reset_index().rename(columns={"index": "road_idx"})
        if "highway" not in meta.columns:
            raise ValueError(
                "metadata-csv must contain a 'highway' column when using --candidate-highways."
            )
        keep = set(args.candidate_highways)
        highway_candidates = meta.loc[meta["highway"].isin(keep), "road_idx"].to_numpy(
            dtype=np.int64
        )
        candidates = np.intersect1d(candidates, highway_candidates)

    candidates = candidates[(candidates >= 0) & (candidates < n)]
    if len(candidates) == 0:
        raise ValueError("No candidate roads remain after filtering.")
    return torch.tensor(candidates, dtype=torch.long, device=data.x.device)


def apply_policy_to_x(
    base_x: torch.Tensor,
    policy_idx: int,
    policy_scaled: float,
    baseline_scaled: float,
    selected_mask: torch.Tensor,
    soft_candidate_mask: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    x = base_x.clone()
    policy_mask = selected_mask.clone()
    if soft_candidate_mask is not None:
        policy_mask = torch.clamp(policy_mask + soft_candidate_mask, 0.0, 1.0)
    x[:, policy_idx] = baseline_scaled + policy_mask * (policy_scaled - baseline_scaled)
    return x


def predicted_volume(
    model: torch.nn.Module,
    data,
    base_x: torch.Tensor,
    scaler_x,
    args: argparse.Namespace,
) -> torch.Tensor:
    pred = model(data).view(-1)
    if args.model_output == "absolute_volume":
        return pred
    base_volume = unscale_feature_tensor(base_x, scaler_x, args.base_volume_feature_idx)
    return base_volume + pred


def overload_metrics(
    model: torch.nn.Module,
    data,
    base_x: torch.Tensor,
    scaler_x,
    args: argparse.Namespace,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    vol = predicted_volume(model, data, base_x, scaler_x, args)
    cap = unscale_feature_tensor(base_x, scaler_x, args.capacity_feature_idx).clamp_min(
        args.capacity_eps
    )
    vc_ratio = vol / cap
    overload_margin = vc_ratio - args.overload_threshold
    soft_count = torch.sigmoid(args.sigmoid_sharpness * overload_margin).sum()
    hard_count = (vc_ratio > args.overload_threshold).sum()
    return soft_count, hard_count, vc_ratio


def optimize_one_pick(
    model: torch.nn.Module,
    data,
    base_x: torch.Tensor,
    scaler_x,
    candidate_idx: torch.Tensor,
    already_selected: torch.Tensor,
    policy_idx: int,
    policy_scaled: float,
    baseline_scaled: float,
    args: argparse.Namespace,
) -> tuple[int, float, int, float, float, float]:
    available = candidate_idx[already_selected[candidate_idx] < 0.5]
    if available.numel() == 0:
        raise RuntimeError("No available candidate roads left to select.")

    logits = torch.zeros(available.numel(), device=base_x.device, requires_grad=True)
    opt = torch.optim.Adam([logits], lr=args.lr)

    best_loss = float("inf")
    best_logits = None

    for _ in range(args.steps):
        opt.zero_grad(set_to_none=True)
        probs = torch.softmax(logits / args.temperature, dim=0)
        soft_mask = torch.zeros(base_x.size(0), device=base_x.device)
        soft_mask.scatter_(0, available, probs)

        data.x = apply_policy_to_x(
            base_x,
            policy_idx,
            policy_scaled,
            baseline_scaled,
            already_selected,
            soft_mask,
        )
        soft_count, _, _ = overload_metrics(model, data, base_x, scaler_x, args)
        entropy = -(probs * probs.clamp_min(1e-12).log()).sum()
        total_loss = soft_count + args.entropy_weight * entropy
        total_loss.backward()
        opt.step()

        if float(soft_count.detach()) < best_loss:
            best_loss = float(soft_count.detach())
            best_logits = logits.detach().clone()

    assert best_logits is not None
    chosen_local = int(torch.argmax(best_logits).item())
    chosen_road = int(available[chosen_local].item())

    committed = already_selected.clone()
    committed[chosen_road] = 1.0
    data.x = apply_policy_to_x(
        base_x, policy_idx, policy_scaled, baseline_scaled, committed
    )

    with torch.no_grad():
        soft_count, hard_count, vc_ratio = overload_metrics(
            model, data, base_x, scaler_x, args
        )
        max_vc = float(vc_ratio.max().detach().cpu())
        mean_vc = float(vc_ratio.mean().detach().cpu())
        score = float(best_logits[chosen_local].detach().cpu())

    return (
        chosen_road,
        float(soft_count.detach().cpu()),
        int(hard_count.detach().cpu()),
        max_vc,
        mean_vc,
        score,
    )


def plot_overloaded_over_time(results: list[PickResult], output_path: str) -> None:
    df = pd.DataFrame([r.__dict__ for r in results])
    plt.figure(figsize=(8, 5))
    plt.plot(df["round_id"], df["hard_overloaded_count"], marker="o")
    plt.xlabel("Number of selected policy roads")
    plt.ylabel("Predicted overloaded roads")
    plt.title("Overloaded roads after greedy differentiable policy selection")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device(args.device)

    scaler_x_path = args.scaler_x_path or os.path.join(
        args.run_path, "data_created_during_training", "test_x_scaler.pkl"
    )
    scaler_x = joblib.load(scaler_x_path)

    model = load_model(args, device)
    data = load_graph(args, device)
    base_x = data.x.detach().clone()

    policy_scaled = scaled_feature_value(
        scaler_x, args.policy_feature_idx, args.policy_value
    )
    baseline_scaled = scaled_feature_value(
        scaler_x, args.policy_feature_idx, args.baseline_policy_value
    )

    candidates = build_candidate_indices(args, data)
    selected_mask = torch.zeros(data.x.size(0), dtype=torch.float32, device=device)

    # Baseline before selecting any road.
    data.x = apply_policy_to_x(
        base_x, args.policy_feature_idx, policy_scaled, baseline_scaled, selected_mask
    )
    with torch.no_grad():
        _, baseline_hard, baseline_vc = overload_metrics(
            model, data, base_x, scaler_x, args
        )
    print(f"Baseline overloaded roads: {int(baseline_hard.detach().cpu())}")
    print(f"Baseline max v/c ratio: {float(baseline_vc.max().detach().cpu()):.4f}")

    results: list[PickResult] = []
    with torch.enable_grad():
        for k in range(args.num_roads):
            (
                road_idx,
                soft_count,
                hard_count,
                max_vc,
                mean_vc,
                score,
            ) = optimize_one_pick(
                model=model,
                data=data,
                base_x=base_x,
                scaler_x=scaler_x,
                candidate_idx=candidates,
                already_selected=selected_mask,
                policy_idx=args.policy_feature_idx,
                policy_scaled=policy_scaled,
                baseline_scaled=baseline_scaled,
                args=args,
            )
            selected_mask[road_idx] = 1.0
            results.append(
                PickResult(
                    round_id=k + 1,
                    road_idx=road_idx,
                    soft_overloaded_count=soft_count,
                    hard_overloaded_count=hard_count,
                    max_volume_capacity_ratio=max_vc,
                    mean_volume_capacity_ratio=mean_vc,
                    logit_score=score,
                )
            )
            print(
                f"Round {k + 1:02d}: selected road_idx={road_idx}, "
                f"hard_overloaded={hard_count}, soft_overloaded={soft_count:.2f}, "
                f"max_vc={max_vc:.3f}, mean_vc={mean_vc:.3f}"
            )

    out = pd.DataFrame([r.__dict__ for r in results])
    if args.metadata_csv:
        meta = pd.read_csv(args.metadata_csv)
        if "road_idx" not in meta.columns:
            meta = meta.reset_index().rename(columns={"index": "road_idx"})
        out = out.merge(meta, on="road_idx", how="left")

    out.to_csv(args.output_csv, index=False)
    plot_overloaded_over_time(results, args.output_plot)
    print(f"Saved selected roads to {args.output_csv}")
    print(f"Saved overloaded-road plot to {args.output_plot}")


if __name__ == "__main__":
    main()
