"""
LNS — multi-client pass (Phase 4).

Cost function:
    cost = cost_multi_pallet_count * pallet_count

Primary goal:  reduce the number of pallets.

Destroy strategy (per iteration):
    Destroy the bottom lns_multi_destroy_ratio fraction of least-filled pallets
    (at least one) entirely — all their boxes enter the pool.
    Surviving pallets are kept untouched.

Repair strategy:
    The pool is shuffled randomly.  Priority-1 boxes are sorted before
    priority-2 boxes to respect the placement order constraint.
    Each box is placed using a perturbed placement: all valid (EP, orientation)
    combinations are collected, sorted by score, and one is chosen randomly
    from the top-k (lns_multi_repair_top_k).  This lets the search escape
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

def compute_cost_multi(pallets: List[Pallet], params: OptimizationParameters) -> float:
    """
    Evaluates a multi-client solution.

    Lower cost = better solution.

    Formula:
        cost = cost_multi_pallet_count * pallet_count
    """
    if not pallets:
        return 0.0

    return params.cost_multi_pallet_count * len(pallets)


# ── Pool helpers ───────────────────────────────────────────────────────────────
# make_pool_box and get_next_pallet_id are imported from lns_utils
_make_pool_box      = make_pool_box
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
) -> List[Pallet]:
    """
    Repairs the pool onto surviving pallets using perturbed placement.

    For each box in the pool:
        1. Try each existing pallet — pick a random position from its top-k
           valid candidates (lns_multi_repair_top_k).  Use the first pallet
           that offers at least one valid position (First Fit, but with
           intra-pallet position perturbation).
        2. If no existing pallet accepts the box, open a new pallet and
           place deterministically (best position — no benefit in perturbing
           an empty pallet since all EPs collapse to the origin).

    Boxes that cannot be placed on any pallet (too large/heavy) are skipped
    with a warning, consistent with FFD behaviour.
    """
    top_k   = params.lns_multi_repair_top_k
    pallets = list(surviving_pallets)
    counter = next_pallet_id

    for box in pool_boxes:
        placed = False

        for pallet in pallets:
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
                print(f"[LNS-multi] WARNING: Box {box.id!r} could not be placed "
                      f"(dims {box.length}×{box.width}×{box.height}). Skipping.")

    return pallets


# ── Single-pass LNS ────────────────────────────────────────────────────────────

def _lns_pass(
    initial_pallets: List[Pallet],
    box_lookup: dict,
    params: OptimizationParameters,
    rng: random.Random,
    max_iterations: int,
    label: str,
    cost_fn: Callable,
) -> List[Pallet]:
    """
    Runs one LNS pass on the given multi-client pallets.

    Each iteration:
        Destroy  — remove the bottom lns_multi_destroy_ratio fraction of
                   least-filled pallets (at least one) entirely.
                   Surviving pallets are kept untouched.
        Randomise — shuffle pool order, then sort P1 before P2.
        Repair   — repack the pool onto surviving pallets with perturbed FFD.
        Accept   — keep the new solution only if cost strictly improves and
                   no box was lost.

    Args:
        initial_pallets: Pallets to optimise.
        box_lookup:      Mapping box_id → original Box.
        params:          Optimization parameters.
        rng:             Shared random state.
        max_iterations:  Maximum iterations for this pass.
        label:           Log prefix (e.g. "[LNS-multi]").
        cost_fn:         Cost function (pallets, params) → float.

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

    while iteration < max_iterations:

        iteration += 1

        # ── Destroy ────────────────────────────────────────────────────────────
        current = copy.deepcopy(best_pallets)

        # Identify the bottom least-filled pallets to destroy.
        # Floor of 2: with only 1 pallet destroyed, the surviving ones are
        # frozen and FFD can only stack on top of them — true fusion (e.g.
        # interleaving boxes between existing layers of a stack) is impossible.
        # Forcing ≥ 2 destructions guarantees at least 2 pallets are merged
        # together each iteration, so small groups (2..6 multi pallets) get a
        # real chance to reorganize. Larger groups are unaffected (30 %
        # already dominates).
        n_destroy = max(2, int(len(current) * params.lns_multi_destroy_ratio))
        sorted_by_fill = sorted(range(len(current)),
                                key=lambda i: current[i].volumetric_fill_ratio)
        destroy_indices = set(sorted_by_fill[:n_destroy])

        pool_pbs: List[PlacedBox]       = []
        surviving_pallets: List[Pallet] = []

        for i, pallet in enumerate(current):
            if i in destroy_indices:
                # Destroy entirely — all boxes go to pool
                pool_pbs.extend(pallet.boxes)
                continue

            # Surviving pallets are kept untouched
            surviving_pallets.append(pallet)

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
        )

        # ── Accept / reject ────────────────────────────────────────────────────
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

def lns_multi_client(
    pallets: List[Pallet],
    original_boxes: List[Box],
    params: OptimizationParameters,
    extra_mono: List[Pallet] = None,
) -> List[Pallet]:
    """
    Runs LNS on multi-client pallets, plus any mono pallets that the caller
    flags as candidates for re-mixing (typically Phase 3 leftovers — mono
    pallets produced by FFD when boxes from multiple clients didn't mix).

    Args:
        pallets:        Current pallet list (typically after Phase 3 repack).
        original_boxes: Full set of original Box objects.
        params:         Optimization parameters.
        extra_mono:     Optional list of mono-client pallets to include in the
                        LNS pool alongside the multi pallets. Identified by
                        Python object identity (`id()`), so the caller MUST
                        pass the actual Pallet objects present in `pallets`,
                        not deepcopies. Pass `None`/empty for the legacy
                        behaviour (multi-only).

    Returns:
        Unchanged mono-client pallets (those NOT in `extra_mono`) + improved
        pool (multi + extra_mono after LNS).
    """
    rng        = random.Random(params.lns_multi_random_seed)
    box_lookup = {b.id: b for b in original_boxes}

    extra_ids      = {id(p) for p in (extra_mono or [])}
    pool           = [p for p in pallets if p.is_multi_client or id(p) in extra_ids]
    untouched_mono = [p for p in pallets if not p.is_multi_client and id(p) not in extra_ids]

    if len(pool) <= 1:
        if not pool:
            print("[LNS-multi] No multi-client pallets — skipping.")
        else:
            print(f"[LNS-multi] Pool too small ({len(pool)} pallet) — skipping.")
        return pallets

    if extra_ids:
        print(f"[LNS-multi] Pool: {len(pool)} pallet(s) "
              f"({len(pool) - len(extra_ids)} multi + {len(extra_ids)} Phase-3 leftover mono).")

    pool_size   = len(pool)
    iter_budget = max(1, pool_size * params.lns_multi_iter_per_pallet)
    print(f"[LNS-multi] Budget: {pool_size} palettes × "
          f"{params.lns_multi_iter_per_pallet} iters = {iter_budget} iters")
    improved_pool = _lns_pass(
        pool, box_lookup, params, rng,
        max_iterations=iter_budget,
        label="[LNS-multi]",
        cost_fn=compute_cost_multi,
    )
    return untouched_mono + improved_pool
