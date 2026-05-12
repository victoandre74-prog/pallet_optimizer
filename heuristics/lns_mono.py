"""
LNS — mono-client pass (Phase 2).

Cost function:
    cost = cost_mono_pallet_count * pallet_count
         + cost_mono_last_pallet_filling * min_fill_ratio

Primary goal:  reduce the number of pallets.
Secondary goal: minimise the fill ratio on the least-filled pallet so it
                becomes a good candidate for merging during Phase 3/4.

Destroy strategy (per iteration):
    1. Destroy the least-filled pallet entirely — all its boxes enter the pool.
    2. Extract every box with volume < lns_mono_small_box_volume from the
       surviving pallets — those boxes also enter the pool.
    Surviving pallets that become empty after extraction are discarded.

Repair strategy:
    The pool is shuffled randomly.  Priority-1 boxes are sorted before
    priority-2 boxes to respect the placement order constraint.
    Each box is placed using a perturbed placement: all valid (EP, orientation)
    combinations are collected, sorted by score, and one is chosen randomly
    from the top-k (lns_mono_repair_top_k).  This lets the search escape
    deterministic local optima while remaining guided by the score.
    New pallets are opened only when no existing pallet can accept the box.
"""

import copy
import random
import time
from typing import Callable, List, Optional, Tuple

from models.box import Box
from models.placed_box import PlacedBox
from models.pallet import Pallet
from config.parameters import OptimizationParameters
from core.placement_engine import (
    find_best_placement, make_placed_box,
    generate_extreme_points, find_support_z, is_valid_placement,
    _compute_residual_area,
)
from heuristics.lns_utils import make_pool_box, get_next_pallet_id


# ── Cost function ──────────────────────────────────────────────────────────────

def compute_cost_mono(pallets: List[Pallet], params: OptimizationParameters) -> float:
    """
    Evaluates a mono-client solution.

    Lower cost = better solution.

    Formula:
        cost = cost_mono_pallet_count        * pallet_count
             + cost_mono_last_pallet_filling * min_fill_ratio

    The second term penalises a high fill ratio on the least-filled pallet
    (reward = lower cost when that pallet is emptier, making it easier to
    merge with boxes from another client in Phase 3/4).
    """
    if not pallets:
        return 0.0

    pallet_count = len(pallets)
    min_fill = min(p.volumetric_fill_ratio for p in pallets)

    return (params.cost_mono_pallet_count * pallet_count
            + params.cost_mono_last_pallet_filling * min_fill)


# ── Pool helpers ───────────────────────────────────────────────────────────────
# make_pool_box and get_next_pallet_id are imported from lns_utils
_make_pool_box    = make_pool_box
_get_next_pallet_id = get_next_pallet_id


# ── Perturbed repair ───────────────────────────────────────────────────────────

def _find_placement_top_k(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
    rng: random.Random,
    top_k: int,
) -> Optional[Tuple[float, float, float, object]]:
    """
    Like find_best_placement but picks randomly from the top-k valid positions.

    Collects every valid (EP, orientation) candidate, scores them identically
    to find_best_placement, sorts ascending, then returns a randomly chosen
    candidate from the top-k.  When top_k=1 this degenerates to the
    deterministic best placement.

    Returns (x, y, z, orientation) or None if no valid position exists.
    """
    from models.orientation import get_oriented_dimensions

    candidates = []

    ep_candidates = generate_extreme_points(pallet)

    for orientation in box.allowed_orientations:
        length, width, height = get_oriented_dimensions(
            box.length, box.width, box.height, orientation
        )
        for (cx, cy) in ep_candidates:
            z = find_support_z(cx, cy, length, width, height, pallet.boxes)
            if is_valid_placement(box, cx, cy, z, orientation,
                                  length, width, height, pallet, params):
                stackable    = box.is_stackable_in(orientation)
                height_score = (z + height) if stackable else 0.0
                residual     = _compute_residual_area(cx, cy, length, width, pallet)
                score        = (z, cx, cy, height_score, -residual)
                candidates.append((score, cx, cy, z, orientation))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0])
    k      = min(top_k, len(candidates))
    chosen = rng.choice(candidates[:k])
    _, cx, cy, z, orientation = chosen
    return cx, cy, z, orientation


def _repair_with_perturbation(
    pool_boxes: List[Box],
    surviving_pallets: List[Pallet],
    params: OptimizationParameters,
    rng: random.Random,
    next_pallet_id: int,
    allow_multi_client: bool,
) -> List[Pallet]:
    """
    Repairs the pool onto surviving pallets using perturbed placement.

    For each box in the pool:
        1. Try each existing pallet — pick a random position from its top-k
           valid candidates (lns_mono_repair_top_k).  Use the first pallet
           that offers at least one valid position (First Fit, but with
           intra-pallet position perturbation).
        2. If no existing pallet accepts the box, open a new pallet and
           place deterministically (best position — no benefit in perturbing
           an empty pallet since all EPs collapse to the origin).

    Boxes that cannot be placed on any pallet (too large/heavy) are skipped
    with a warning, consistent with FFD behaviour.
    """
    top_k   = params.lns_mono_repair_top_k
    pallets = list(surviving_pallets)
    counter = next_pallet_id

    for box in pool_boxes:
        placed = False

        for pallet in pallets:
            if not allow_multi_client and pallet.boxes:
                if any(pb.client_id != box.client_id for pb in pallet.boxes):
                    continue

            result = _find_placement_top_k(box, pallet, params, rng, top_k)
            if result is not None:
                x, y, z, orientation = result
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = len(pallet.boxes) + 1
                pallet.boxes.append(pb)
                placed = True
                break

        if not placed:
            new_pallet = Pallet(
                id=counter,
                length=params.pallet_length,
                width=params.pallet_width,
                max_height=params.pallet_max_height,
                max_weight=params.pallet_max_weight,
            )
            counter += 1
            result = find_best_placement(box, new_pallet, params)
            if result is not None:
                x, y, z, orientation = result
                pb          = make_placed_box(box, x, y, z, orientation)
                pb.sequence = 1
                new_pallet.boxes.append(pb)
                pallets.append(new_pallet)
            else:
                print(f"[LNS-mono] WARNING: Box {box.id!r} could not be placed "
                      f"(dims {box.length}×{box.width}×{box.height}). Skipping.")

    return pallets


# ── Single-pass LNS ────────────────────────────────────────────────────────────

def _lns_pass(
    initial_pallets: List[Pallet],
    box_lookup: dict,
    params: OptimizationParameters,
    rng: random.Random,
    time_limit: float,
    max_iterations: int,
    allow_multi_client: bool,
    label: str,
    cost_fn: Callable,
) -> List[Pallet]:
    """
    Runs one LNS pass on the given pallets using the mono destroy strategy.

    Each iteration:
        Destroy  — remove the least-filled pallet entirely + all small boxes
                   (volume < lns_mono_small_box_volume) from surviving pallets.
        Randomise — shuffle pool order, force a random orientation per box,
                    then sort P1 before P2.
        Repair   — repack the pool onto surviving pallets with FFD.
        Accept   — keep the new solution only if cost strictly improves.

    Args:
        initial_pallets:    Pallets to optimise.
        box_lookup:         Mapping box_id → original Box.
        params:             Optimization parameters.
        rng:                Shared random state.
        time_limit:         Wall-clock budget for this pass (seconds).
        max_iterations:     Maximum iterations for this pass.
        allow_multi_client: When False, repair cannot mix clients on a pallet.
        label:              Log prefix (e.g. "[LNS-mono|client=1]").
        cost_fn:            Cost function (pallets, params) → float.

    Returns:
        Best pallet list found within the budget.
    """
    if not initial_pallets:
        print(f"{label} No pallets to optimise — skipping.")
        return initial_pallets

    best_pallets = copy.deepcopy(initial_pallets)
    best_cost    = cost_fn(best_pallets, params)

    start_time            = time.time()
    iteration             = 0
    improvement_count     = 0
    last_improvement_iter = 0

    print(f"{label} Starting. Cost: {best_cost:.2f}, pallets: {len(best_pallets)}")

    while (iteration < max_iterations and
           time.time() - start_time < time_limit):

        iteration += 1

        # ── Destroy ────────────────────────────────────────────────────────────
        current = copy.deepcopy(best_pallets)

        # 1. Identify the least-filled pallet by index
        least_idx = min(
            range(len(current)),
            key=lambda i: current[i].volumetric_fill_ratio,
        )

        pool_pbs: List[PlacedBox]   = []
        surviving_pallets: List[Pallet] = []

        for i, pallet in enumerate(current):
            if i == least_idx:
                # Destroy entirely — all boxes go to pool
                pool_pbs.extend(pallet.boxes)
                continue

            # Extract small boxes from this pallet
            small = [pb for pb in pallet.boxes
                     if pb.volume < params.lns_mono_small_box_volume]
            if small:
                pallet.boxes = [pb for pb in pallet.boxes
                                if pb.volume >= params.lns_mono_small_box_volume]
                # Close sequence gaps so len(pallet.boxes)+1 stays unique
                for _seq_i, _pb in enumerate(pallet.boxes, 1):
                    _pb.sequence = _seq_i
                pool_pbs.extend(small)

            # Keep pallet only if it still has boxes
            if not pallet.is_empty():
                surviving_pallets.append(pallet)
            else:
                # Pallet emptied by small-box extraction — treat as destroyed
                pool_pbs.extend(pallet.boxes)  # already empty, no-op but explicit

        # ── Build and randomise pool ────────────────────────────────────────────
        if not pool_pbs:
            continue

        # Reconstruct Box objects (all orientations preserved)
        pool_boxes = [_make_pool_box(pb, box_lookup) for pb in pool_pbs]

        # Shuffle order (perturbation)
        rng.shuffle(pool_boxes)

        # Enforce P1 before P2 (stable sort preserves the random order within
        # each priority group)
        pool_boxes.sort(key=lambda b: b.priority)

        # ── Repair ─────────────────────────────────────────────────────────────
        next_id = _get_next_pallet_id(surviving_pallets)
        new_pallets = _repair_with_perturbation(
            pool_boxes, surviving_pallets, params, rng,
            next_pallet_id=next_id,
            allow_multi_client=allow_multi_client,
        )

        # ── Accept / reject ────────────────────────────────────────────────────
        # Count boxes in the reference solution and the new candidate.
        # Reject immediately if any box was lost (FFD silently skips boxes
        # that cannot be placed — accepting such a solution would lose data).
        boxes_before = sum(len(p.boxes) for p in best_pallets)
        boxes_after  = sum(len(p.boxes) for p in new_pallets)
        if boxes_after < boxes_before:
            continue

        new_cost = cost_fn(new_pallets, params)
        if new_cost < best_cost:
            best_cost             = new_cost
            best_pallets          = copy.deepcopy(new_pallets)
            improvement_count    += 1
            last_improvement_iter = iteration
            print(f"{label} iter {iteration:4d}: improved cost → {best_cost:.2f}, "
                  f"pallets: {len(best_pallets)}")

    elapsed    = time.time() - start_time
    stagnation = iteration - last_improvement_iter
    stag_pct   = stagnation / max(1, iteration) * 100
    print(
        f"{label} Done. {iteration} iters in {elapsed:.1f}s | "
        f"improvements: {improvement_count} | "
        f"stagnation: {stagnation} iters ({stag_pct:.0f}%) | "
        f"pallets: {len(initial_pallets)}→{len(best_pallets)}"
    )

    return best_pallets


# ── Entry point ────────────────────────────────────────────────────────────────

def lns_mono_client(
    pallets: List[Pallet],
    original_boxes: List[Box],
    params: OptimizationParameters,
) -> List[Pallet]:
    """
    Runs LNS independently on each mono-client group (one group per client_id).

    Multi-client pallets in the input list are passed through unchanged.
    The repair step is forbidden from creating new mixed-client pallets.

    Time and iteration budgets are divided across groups proportionally to
    their pallet count.  Each group uses a deterministic seed derived from
    lns_mono_random_seed XOR'd with its client_id for reproducibility.

    Args:
        pallets:        Current pallet list (typically after Phase 1 FFD).
        original_boxes: Full set of original Box objects.
        params:         Optimization parameters.

    Returns:
        Improved mono-client pallets (all groups concatenated) +
        unchanged multi-client pallets.
    """
    box_lookup = {b.id: b for b in original_boxes}

    mono  = [p for p in pallets if not p.is_multi_client]
    multi = [p for p in pallets if p.is_multi_client]

    if not mono:
        print("[LNS-mono] No mono-client pallets — skipping.")
        return pallets

    # Group mono pallets by client_id
    groups: dict = {}
    for p in mono:
        cid = next(iter(p.client_ids))
        groups.setdefault(cid, []).append(p)

    total_pallets = len(mono)
    improved_all: List[Pallet] = []

    print(f"[LNS-mono] {len(groups)} client group(s), {total_pallets} pallets total.")

    for cid, group in sorted(groups.items()):
        if len(group) <= 1:
            print(f"[LNS-mono|client={cid}] Single pallet — skipping LNS.")
            improved_all.extend(group)
            continue

        weight      = len(group) / total_pallets
        time_budget = max(1.0, params.lns_mono_time_limit * weight)
        iter_budget = max(1,   int(params.lns_mono_max_iterations * weight))

        seed = params.lns_mono_random_seed ^ cid
        rng  = random.Random(seed)

        improved = _lns_pass(
            group, box_lookup, params, rng,
            time_limit=time_budget,
            max_iterations=iter_budget,
            allow_multi_client=False,
            label=f"[LNS-mono|client={cid}]",
            cost_fn=compute_cost_mono,
        )
        improved_all.extend(improved)

    result = improved_all + multi
    # Reassign unique IDs — independent group LNS passes can produce duplicate
    # pallet IDs because each pass only knows about its own surviving pallets.
    for new_id, p in enumerate(result, 1):
        p.id = new_id
    return result
