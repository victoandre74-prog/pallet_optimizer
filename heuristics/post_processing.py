"""
post_processing.py — LNS-based post-processing for palletization results.

Five joint objectives optimised by a cost function:
    1. P2→P1 contact  — priority-2 boxes should be placed laterally against
                        priority-1 boxes (maximise vertical contact area).
    2. Fill balance   — fill ratios across pallets in the same group should
                        be as equal as possible (low variance).
    3. P2 spread      — priority-2 boxes should be evenly spread across all
                        pallets in each group (low variance of P2 count).
    4. Height         — reward minimal pallet height across the group.
    5. Stability      — reward more stable pallets (lower stability ratio).

Algorithm (per group):
    Unified LNS strategy for both mono-client and multi-client groups:

    Single-pallet group:
        Depack all P2 boxes, shuffle, repack P2 with top-k placement
        scored by (z, -contact_P2/P1, x, y).

    Multi-pallet group:
        1. Depack all P2 from all pallets into a pool (shuffled).
        2. If fill delta (max fill - min fill) > 15%:
             Fill equalization — iteratively move 1–2 smallest P1 boxes
             from the best-filled (donor) to the least-filled (receiver).
             Repack P1 of both with core engine scoring:
             (z, cx, cy, height_score, -residual).
        3. P2 placement — iterate, each iteration randomly assigning each
             P2 box to a pallet with top-k contact placement.
             Accept if cost improves.

    After LNS, gap repair is applied on flagged pallets using signed
    placements (negative EP orientations) then P2 contact placement.

Placement engine:
    Score P1 : (z, x, y)               — core engine with residual tiebreaker.
    Score P2 : (z, -contact_P1, x, y)  — maximise P2→P1 lateral contact.
    Top-k    : top_k best placements collected, one picked at random.

Groups:
    • One group per mono-client (client_id).
    • One multi-client group — processed with the same LNS as mono.

Hard constraints (always enforced):
    • Total pallet count ≤ input count.
    • All 3-D placement constraints (collision, stacking, support, weight,
      ergonomic height) enforced by is_valid_placement at every step.
"""

import copy
import random
import time
from dataclasses import replace as dc_replace
from typing import Dict, List, Optional, Tuple

from models.box import Box
from models.pallet import Pallet
from models.placed_box import PlacedBox
from models.orientation import Orientation, ALL_ORIENTATIONS, get_oriented_dimensions
from config.parameters import OptimizationParameters
from core.placement_engine import (
    generate_extreme_points,
    find_support_z,
    is_valid_placement,
    make_placed_box,
    find_best_placement as _core_find_best_placement,
)

FLOAT_TOL = 1e-6
_FILL_EQUALIZATION_THRESHOLD = 0.15   # 15% fill delta triggers P1 moves


# ══════════════════════════════════════════════════════════════════════════════
# Box lookup helpers
# ══════════════════════════════════════════════════════════════════════════════

def _reconstruct_box(pb: PlacedBox) -> Box:
    """Fallback when a box is not in the lookup (uses placed dims as canonical)."""
    return Box(
        id=pb.box_id, priority=pb.priority,
        length=pb.length, width=pb.width, height=pb.height,
        weight=pb.weight, client_id=pb.client_id,
        allowed_orientations=list(ALL_ORIENTATIONS),
        stackable={o: pb.stackable for o in ALL_ORIENTATIONS},
    )


def _get_box(pb: PlacedBox, box_lookup: Dict[str, Box]) -> Box:
    return box_lookup.get(pb.box_id) or _reconstruct_box(pb)


# ══════════════════════════════════════════════════════════════════════════════
# Cost function
# ══════════════════════════════════════════════════════════════════════════════

def _vertical_contact_area(p2: PlacedBox, p1: PlacedBox) -> float:
    """
    Vertical contact area (cm²) between a P2 box and a P1 box on their
    shared lateral face (perpendicular to the XY plane).
    """
    total = 0.0

    ov_z = max(0.0, min(p2.z_max, p1.z_max) - max(p2.z, p1.z))
    if ov_z <= FLOAT_TOL:
        return 0.0

    if abs(p2.x - p1.x_max) <= FLOAT_TOL or abs(p2.x_max - p1.x) <= FLOAT_TOL:
        ov_y = max(0.0, min(p2.y_max, p1.y_max) - max(p2.y, p1.y))
        total += ov_y * ov_z

    if abs(p2.y - p1.y_max) <= FLOAT_TOL or abs(p2.y_max - p1.y) <= FLOAT_TOL:
        ov_x = max(0.0, min(p2.x_max, p1.x_max) - max(p2.x, p1.x))
        total += ov_x * ov_z

    return total


def _p2_p1_contact_area(pallet: Pallet) -> float:
    """Total vertical contact area (cm²) between P2 and P1 boxes on a pallet."""
    total = 0.0
    p1_boxes = [pb for pb in pallet.boxes if pb.priority == 1]
    for pb in pallet.boxes:
        if pb.priority != 2:
            continue
        for p1 in p1_boxes:
            total += _vertical_contact_area(pb, p1)
    return total


def compute_pp_cost(pallets: List[Pallet], params: OptimizationParameters) -> float:
    """
    Lower cost = better post-processed solution.

    Cost = - w_contact   * Σ_pallets( p2_p1_contact_area )  [maximise contact]
           + w_fill      * Var( fill_ratio )
           + w_p2        * Var( p2_count )
           + w_height    * mean( current_height / max_height )
           + w_stability * max( worst_stability_ratio )
    """
    if not pallets:
        return 0.0

    # P2→P1 contact (maximise → negative)
    contact_cost = -sum(_p2_p1_contact_area(p) for p in pallets)

    # Fill variance
    fills = [p.volumetric_fill_ratio for p in pallets]
    fill_mean = sum(fills) / len(fills)
    fill_var  = sum((f - fill_mean) ** 2 for f in fills) / len(fills)

    # P2 count variance
    p2c    = [sum(1 for pb in p.boxes if pb.priority == 2) for p in pallets]
    p2m    = sum(p2c) / len(p2c)
    p2_var = sum((c - p2m) ** 2 for c in p2c) / len(p2c)

    # Height term — mean normalised height across group
    heights = [(p.current_height / p.max_height) if p.max_height > 0 else 0.0
               for p in pallets]
    height_term = sum(heights) / len(heights)

    # Stability term — worst (highest) stability ratio across group
    stab_ratios = [p.worst_stability_ratio for p in pallets if p.boxes]
    stability_term = max(stab_ratios) if stab_ratios else 0.0

    return (params.pp_w_contact * contact_cost
            + params.pp_w_fill * fill_var
            + params.pp_w_p2 * p2_var
            + params.pp_w_height * height_term
            + params.pp_w_stability * stability_term)


# ══════════════════════════════════════════════════════════════════════════════
# Placement helpers
# ══════════════════════════════════════════════════════════════════════════════

def _p2_contact_with_p1(
    x: float, y: float, z: float,
    length: float, width: float, height: float,
    placed_boxes: List[PlacedBox],
) -> float:
    """
    Total vertical contact area (cm²) between a candidate P2 box at
    (x, y, z, length, width, height) and all placed P1 boxes.
    """
    total  = 0.0
    x_max  = x + length
    y_max  = y + width
    z_max  = z + height

    for pb in placed_boxes:
        if pb.priority != 1:
            continue

        ov_z = max(0.0, min(z_max, pb.z_max) - max(z, pb.z))
        if ov_z <= FLOAT_TOL:
            continue

        if abs(x - pb.x_max) <= FLOAT_TOL or abs(x_max - pb.x) <= FLOAT_TOL:
            ov_y = max(0.0, min(y_max, pb.y_max) - max(y, pb.y))
            total += ov_y * ov_z

        if abs(y - pb.y_max) <= FLOAT_TOL or abs(y_max - pb.y) <= FLOAT_TOL:
            ov_x = max(0.0, min(x_max, pb.x_max) - max(x, pb.x))
            total += ov_x * ov_z

    return total


def _find_best_p2_placement(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
) -> Optional[Tuple[float, float, float, Orientation]]:
    """
    Returns the single best valid P2 placement (x, y, z, orientation).
    Score: (z, -contact_per_cm², x, y).
    """
    best       = None
    best_score = None

    for orientation in box.allowed_orientations:
        L, W, H = get_oriented_dimensions(box.length, box.width, box.height, orientation)

        for cx, cy in generate_extreme_points(pallet):
            z = find_support_z(cx, cy, L, W, H, pallet.boxes)

            if not is_valid_placement(box, cx, cy, z, orientation, L, W, H, pallet, params):
                continue

            contact = _p2_contact_with_p1(cx, cy, z, L, W, H, pallet.boxes)
            score = (z, -contact, cx, cy)

            if best_score is None or score < best_score:
                best_score = score
                best = (cx, cy, z, orientation)

    return best


def _find_top_k_p2_placements(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
    k: int,
) -> List[Tuple[float, float, float, Orientation]]:
    """
    Returns up to *k* best valid P2 placements sorted by
    (z, -contact/base_area, x, y).
    """
    candidates: List[Tuple[Tuple, Tuple]] = []

    for orientation in box.allowed_orientations:
        L, W, H = get_oriented_dimensions(box.length, box.width, box.height, orientation)

        for cx, cy in generate_extreme_points(pallet):
            z = find_support_z(cx, cy, L, W, H, pallet.boxes)

            if not is_valid_placement(box, cx, cy, z, orientation, L, W, H, pallet, params):
                continue

            contact = _p2_contact_with_p1(cx, cy, z, L, W, H, pallet.boxes)
            score = (z, -contact, cx, cy)
            candidates.append((score, (cx, cy, z, orientation)))

    candidates.sort(key=lambda c: c[0])
    return [c[1] for c in candidates[:k]]


def _pack_p1_only(
    p1_boxes: List[Box],
    template: Pallet,
    params: OptimizationParameters,
) -> Optional[Pallet]:
    """
    Repacks only P1 boxes onto a fresh pallet using the core engine's
    scoring: (z, cx, cy, height_score, -residual).

    Returns None if any P1 box cannot be placed.
    """
    pallet = Pallet(id=template.id, length=template.length,
                    width=template.width, max_height=template.max_height,
                    max_weight=template.max_weight)

    ordered = sorted(p1_boxes, key=lambda b: (-b.volume, -b.weight))

    for box in ordered:
        result = _core_find_best_placement(box, pallet, params)
        if result is None:
            return None

        x, y, z, orientation = result
        pb = make_placed_box(box, x, y, z, orientation)
        pb.sequence = len(pallet.boxes) + 1
        pallet.boxes.append(pb)

    return pallet


def _place_p2_pool(
    p2_pool: List[Box],
    pallets: List[Pallet],
    params: OptimizationParameters,
    rng: random.Random,
) -> bool:
    """
    Distributes every P2 box from *p2_pool* onto *pallets* (mutates them).

    For each P2 box, pallets are tried in random order.  On each pallet
    the top-k best contact placements are collected; one is picked at
    random.  Returns True if all boxes were placed.
    """
    N = len(pallets)
    for box in p2_pool:
        order = list(range(N))
        rng.shuffle(order)
        placed = False
        for i in order:
            tops = _find_top_k_p2_placements(box, pallets[i], params, params.pp_top_k)
            if tops:
                x, y, z, orientation = rng.choice(tops)
                pb = make_placed_box(box, x, y, z, orientation)
                pb.sequence = len(pallets[i].boxes) + 1
                pallets[i].boxes.append(pb)
                placed = True
                break
        if not placed:
            return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Unified LNS
# ══════════════════════════════════════════════════════════════════════════════

def _lns_group(
    pallets: List[Pallet],
    box_lookup: Dict[str, Box],
    params: OptimizationParameters,
    rng: random.Random,
    label: str,
) -> List[Pallet]:
    """
    Unified LNS for both mono-client and multi-client groups.

    1. Depack all P2 into a pool (shuffled).
    2. If N==1: one-shot P2 repack with top-k contact placement.
    3. If N>1 and fill delta > 15%: fill equalization phase (move
       1-2 smallest P1 from best-filled to least-filled, repack P1
       of both with core scoring).
    4. P2 placement phase: iteratively shuffle + assign P2 boxes to
       pallets with top-k contact placement, accept if cost improves.
    """
    if not pallets:
        return pallets

    N = len(pallets)
    original = copy.deepcopy(pallets)      # safety net — returned if nothing improves
    best = copy.deepcopy(pallets)

    # ── Step 1: depack all P2 into pool ──────────────────────────────────────
    p2_pool: List[Box] = []
    for p in best:
        p2_pbs = [pb for pb in p.boxes if pb.priority == 2]
        for pb in p2_pbs:
            p2_pool.append(_get_box(pb, box_lookup))
        p.boxes = [pb for pb in p.boxes if pb.priority == 1]
    rng.shuffle(p2_pool)

    original_cost = compute_pp_cost(original, params)

    print(f"{label} start — {N} pallet(s), {len(p2_pool)} P2 boxes depacked")
    _log_group_stats(label, original)

    # ── Step 3: fill equalization (if delta > threshold) ─────────────────────
    # (N==1 skips equalization — nothing to equalise, falls through to P2 loop)
    fills = [p.volumetric_fill_ratio for p in best]
    delta = max(fills) - min(fills)

    start    = time.time()
    improved = 0
    skipped  = 0
    fill_last_improvement_iter = 0
    fill_iters_run             = 0

    if delta > _FILL_EQUALIZATION_THRESHOLD:
        # Use half the iteration budget for fill equalization
        fill_iters = params.pp_max_iterations // 2
        fill_cost  = compute_pp_cost(best, params)   # cost without P2

        print(f"{label} fill delta {delta:.1%} > {_FILL_EQUALIZATION_THRESHOLD:.0%}"
              f" — running fill equalization ({fill_iters} iters max)")

        for iteration in range(1, fill_iters + 1):
            if time.time() - start > params.pp_time_limit / 2:
                break

            current = copy.deepcopy(best)
            fills_cur = [p.volumetric_fill_ratio for p in current]

            i_donor    = fills_cur.index(max(fills_cur))
            i_receiver = fills_cur.index(min(fills_cur))
            if i_donor == i_receiver:
                break  # balanced

            # Pick 1–2 smallest P1 by volume from donor
            donor_p1 = [(pb, _get_box(pb, box_lookup))
                        for pb in current[i_donor].boxes if pb.priority == 1]
            if not donor_p1:
                skipped += 1
                continue
            donor_p1.sort(key=lambda t: t[1].volume)
            k = rng.randint(1, min(2, len(donor_p1)))
            move = donor_p1[:k]
            move_ids = {pb.box_id for pb, _ in move}
            move_boxes = [b for _, b in move]

            # Remaining P1 on donor + all P1 on receiver + moved boxes
            donor_remaining = [_get_box(pb, box_lookup)
                               for pb in current[i_donor].boxes
                               if pb.priority == 1 and pb.box_id not in move_ids]
            receiver_p1 = [_get_box(pb, box_lookup)
                           for pb in current[i_receiver].boxes
                           if pb.priority == 1] + move_boxes

            # Repack P1 of both using core engine scoring
            new_donor = _pack_p1_only(donor_remaining, current[i_donor], params) \
                        if donor_remaining else \
                        Pallet(id=current[i_donor].id,
                               length=current[i_donor].length,
                               width=current[i_donor].width,
                               max_height=current[i_donor].max_height,
                               max_weight=current[i_donor].max_weight)
            new_receiver = _pack_p1_only(receiver_p1, current[i_receiver], params)

            if new_donor is None or new_receiver is None:
                skipped += 1
                continue

            current[i_donor]    = new_donor
            current[i_receiver] = new_receiver

            new_cost = compute_pp_cost(current, params)
            if new_cost < fill_cost:
                d = fill_cost - new_cost
                fill_cost = new_cost
                best = current
                improved += 1
                fill_last_improvement_iter = iteration
                new_fills = [p.volumetric_fill_ratio for p in best]
                print(f"{label} fill iter {iteration:4d}: "
                      f"cost {new_cost:.4f} (Δ={d:.4f})  "
                      f"moved {k} P1  fills=[{', '.join(f'{f:.1%}' for f in new_fills)}]")

            fill_iters_run = iteration

        elapsed_fill  = time.time() - start
        fill_stag     = fill_iters_run - fill_last_improvement_iter
        fill_stag_pct = fill_stag / max(1, fill_iters_run) * 100
        print(
            f"{label} fill equalization done — {improved} improvements "
            f"({skipped} skipped) in {elapsed_fill:.1f}s | "
            f"stagnation: {fill_stag} iters ({fill_stag_pct:.0f}%)"
        )

    # ── Step 4: P2 placement iterations ──────────────────────────────────────
    p1_snapshot = copy.deepcopy(best)   # save P1-only state for re-trials
    best_cost   = original_cost         # baseline = original with P2 in place
    best        = original              # start from original; only replace on improvement

    p2_improved               = 0
    p2_skipped                = 0
    p2_last_improvement_iter  = 0
    p2_iters_run              = 0
    p2_start                  = time.time()

    for iteration in range(1, params.pp_max_iterations + 1):
        if time.time() - p2_start > params.pp_time_limit:
            break

        trial = copy.deepcopy(p1_snapshot)
        rng.shuffle(p2_pool)

        if not _place_p2_pool(p2_pool, trial, params, rng):
            p2_skipped += 1
            p2_iters_run = iteration
            continue

        new_cost = compute_pp_cost(trial, params)
        if new_cost < best_cost:
            d = best_cost - new_cost
            best_cost = new_cost
            best = trial
            p2_improved += 1
            p2_last_improvement_iter = iteration
            if p2_improved <= 10 or p2_improved % 50 == 0:
                print(f"{label} P2 iter {iteration:4d}: "
                      f"cost {new_cost:.4f} (Δ={d:.4f})")

        p2_iters_run = iteration

    elapsed_p2  = time.time() - p2_start
    p2_stag     = p2_iters_run - p2_last_improvement_iter
    p2_stag_pct = p2_stag / max(1, p2_iters_run) * 100
    if p2_improved == 0:
        print(
            f"{label} P2 done — no improvement found, keeping original. "
            f"({p2_skipped} skipped) in {elapsed_p2:.1f}s | "
            f"stagnation: {p2_stag} iters ({p2_stag_pct:.0f}%)"
        )
    else:
        print(
            f"{label} P2 done — {p2_improved} improvements "
            f"({p2_skipped} skipped) in {elapsed_p2:.1f}s | "
            f"stagnation: {p2_stag} iters ({p2_stag_pct:.0f}%) | "
            f"Final cost={best_cost:.2f}"
        )

    # ── Safety: verify no box was lost ───────────────────────────────────────
    original_ids = {pb.box_id for p in original for pb in p.boxes}
    best_ids     = {pb.box_id for p in best for pb in p.boxes}
    if best_ids != original_ids:
        lost   = original_ids - best_ids
        gained = best_ids - original_ids
        print(f"{label} WARNING: box mismatch — lost={len(lost)} gained={len(gained)}. "
              f"Reverting to original.")
        best = original

    _log_group_stats(label, best)
    return best


# ══════════════════════════════════════════════════════════════════════════════
# Logging helpers
# ══════════════════════════════════════════════════════════════════════════════

def _log_group_stats(label: str, pallets: List[Pallet]) -> None:
    if not pallets:
        return
    fills     = [p.volumetric_fill_ratio for p in pallets]
    p2s       = [sum(1 for pb in p.boxes if pb.priority == 2) for p in pallets]
    contacts  = [_p2_p1_contact_area(p) for p in pallets]
    heights   = [p.current_height for p in pallets]
    stab      = [p.worst_stability_ratio for p in pallets if p.boxes]
    avg_fill  = sum(fills) / len(fills)
    fill_var  = sum((f - avg_fill) ** 2 for f in fills) / len(fills)
    fills_fmt = "  ".join(f"{f:.1%}" for f in fills)
    print(f"  {label}")
    print(f"    fill/pallet    : [{fills_fmt}]")
    print(f"    fill var       : {fill_var:.6f}  (lower=more balanced)")
    print(f"    P2/pallet      : {p2s}")
    print(f"    P2→P1 contact  : {[f'{c:.0f}cm²' for c in contacts]}")
    print(f"    height/pallet  : {[f'{h:.0f}cm' for h in heights]}")
    print(f"    stability      : {[f'{s:.2f}' for s in stab]}")


# ══════════════════════════════════════════════════════════════════════════════
# Gap detection
# ══════════════════════════════════════════════════════════════════════════════

def _water_fill_gap(
    pallet: Pallet,
    a_attr: str,
    a_len_attr: str,
    b_attr: str,
    b_len_attr: str,
    scale: float = 1.0,
) -> float:
    """
    Water-fill gap area (cm²) of the P1 height profile along one projection.

    Builds the height profile H[a] = max(b + b_len) of all P1 boxes covering
    position a.  Then computes the "trapped water" area — the region where
    H[a] < min(running_max_from_left[a], running_max_from_right[a]).
    """
    p1_boxes = [pb for pb in pallet.boxes if pb.priority == 1]
    if not p1_boxes:
        return 0.0

    a_max = max(getattr(pb, a_attr) + getattr(pb, a_len_attr) for pb in p1_boxes)
    n = int(a_max / scale) + 2
    H = [0.0] * n

    for pb in p1_boxes:
        a0 = getattr(pb, a_attr)
        a1 = a0 + getattr(pb, a_len_attr)
        b1 = getattr(pb, b_attr) + getattr(pb, b_len_attr)
        for ga in range(int(a0 / scale), min(int(a1 / scale) + 1, n)):
            if H[ga] < b1:
                H[ga] = b1

    occupied = [gx for gx in range(n) if H[gx] > 0]
    if not occupied:
        return 0.0
    x0, x1 = min(occupied), max(occupied) + 1

    max_left = [0.0] * n
    ml = 0.0
    for gx in range(x0, x1):
        ml = max(ml, H[gx])
        max_left[gx] = ml

    max_right = [0.0] * n
    mr = 0.0
    for gx in range(x1 - 1, x0 - 1, -1):
        mr = max(mr, H[gx])
        max_right[gx] = mr

    gap = sum(
        max(0.0, min(max_left[gx], max_right[gx]) - H[gx]) * scale
        for gx in range(x0, x1)
    )
    return gap


def _detect_gap_pallets(pallets: List[Pallet]) -> List[Tuple[Pallet, float, float]]:
    """
    Returns pallets that have any XZ or YZ water-fill gap (gap_area > 0).
    Sorted by max gap descending.
    """
    flagged = []
    for pallet in pallets:
        xz = _water_fill_gap(pallet, 'x', 'length', 'z', 'height')
        yz = _water_fill_gap(pallet, 'y', 'width',  'z', 'height')
        if xz > 0.0 or yz > 0.0:
            flagged.append((pallet, xz, yz))

    flagged.sort(key=lambda t: max(t[1], t[2]), reverse=True)
    return flagged


# ══════════════════════════════════════════════════════════════════════════════
# Gap repair
# ══════════════════════════════════════════════════════════════════════════════

_SIGNS = [(1, 1), (-1, 1), (1, -1), (-1, -1)]


def _gap_direction(pallet: Pallet, scale: float = 1.0) -> str:
    """
    Returns 'right' if the taller P1 column is to the right of the gap,
    'left' if it is to the left.
    """
    p1_boxes = [pb for pb in pallet.boxes if pb.priority == 1]
    if not p1_boxes:
        return 'right'

    a_max = max(pb.x + pb.length for pb in p1_boxes)
    n = int(a_max / scale) + 2
    H = [0.0] * n

    for pb in p1_boxes:
        a0, a1 = pb.x, pb.x + pb.length
        b1 = pb.z + pb.height
        for ga in range(int(a0 / scale), min(int(a1 / scale) + 1, n)):
            if H[ga] < b1:
                H[ga] = b1

    occupied = [gx for gx in range(n) if H[gx] > 0]
    if not occupied:
        return 'right'
    x0, x1 = min(occupied), max(occupied) + 1

    max_left = [0.0] * n
    ml = 0.0
    for gx in range(x0, x1):
        ml = max(ml, H[gx])
        max_left[gx] = ml

    max_right = [0.0] * n
    mr = 0.0
    for gx in range(x1 - 1, x0 - 1, -1):
        mr = max(mr, H[gx])
        max_right[gx] = mr

    right_sum = left_sum = 0.0
    for gx in range(x0, x1):
        water = min(max_left[gx], max_right[gx]) - H[gx]
        if water > 0:
            right_sum += max_right[gx]
            left_sum  += max_left[gx]

    return 'right' if right_sum >= left_sum else 'left'


def _find_best_placement_signed(
    box: Box,
    pallet: Pallet,
    params: OptimizationParameters,
    x_gravity: int,
) -> Optional[Tuple[float, float, float, Orientation]]:
    """
    Tests all 4 signed placements at each EP and uses *x_gravity* to
    bias horizontal preference.

        x_gravity = -1  →  prefer high x  (move right toward tall column)
        x_gravity = +1  →  prefer low  x  (move left toward tall column)
    """
    best       = None
    best_score = None

    for orientation in box.allowed_orientations:
        L, W, H = get_oriented_dimensions(box.length, box.width, box.height, orientation)

        for cx, cy in generate_extreme_points(pallet):
            for sx, sy in _SIGNS:
                ax = cx if sx > 0 else cx - L
                ay = cy if sy > 0 else cy - W

                if ax < -FLOAT_TOL or ay < -FLOAT_TOL:
                    continue
                if ax + L > pallet.length + FLOAT_TOL or ay + W > pallet.width + FLOAT_TOL:
                    continue

                ax = max(0.0, ax)
                ay = max(0.0, ay)

                z = find_support_z(ax, ay, L, W, H, pallet.boxes)

                if not is_valid_placement(box, ax, ay, z, orientation, L, W, H, pallet, params):
                    continue

                score = (z, x_gravity * ax, ay)
                if best_score is None or score < best_score:
                    best_score = score
                    best = (ax, ay, z, orientation)

    return best


def _repack_gap_pallet(
    pallet: Pallet,
    box_lookup: Dict[str, Box],
    params: OptimizationParameters,
) -> Pallet:
    """
    Attempts a gap-repair repack on *pallet*.

    1. Detect gap direction (which side has the taller P1 column).
    2. Repack P1 with signed placement (negative EP orientations).
    3. Repack P2 with contact-aware placement.
    4. Accept only if every box was placed AND XZ gap decreased.
    """
    old_gap = _water_fill_gap(pallet, 'x', 'length', 'z', 'height')
    direction = _gap_direction(pallet)
    x_gravity = -1 if direction == 'right' else 1

    all_boxes = [(pb, box_lookup.get(pb.box_id)) for pb in pallet.boxes]
    if any(b is None for _, b in all_boxes):
        return pallet  # missing lookup entries — skip

    p1_boxes = [b for pb, b in all_boxes if pb.priority == 1]
    p2_boxes = [b for pb, b in all_boxes if pb.priority == 2]

    # Repack P1 with signed placement
    new_pallet = Pallet(id=pallet.id, length=pallet.length,
                        width=pallet.width, max_height=pallet.max_height,
                        max_weight=pallet.max_weight)

    ordered_p1 = sorted(p1_boxes, key=lambda b: (-b.volume, -b.weight))
    for box in ordered_p1:
        result = _find_best_placement_signed(box, new_pallet, params, x_gravity)
        if result is None:
            print(f"    Pallet {pallet.id:3d}: could not place P1  ✗ skipped")
            return pallet
        x, y, z, orientation = result
        pb = make_placed_box(box, x, y, z, orientation)
        pb.sequence = len(new_pallet.boxes) + 1
        new_pallet.boxes.append(pb)

    # Repack P2 with contact placement
    ordered_p2 = sorted(p2_boxes, key=lambda b: (-b.volume, -b.weight))
    for box in ordered_p2:
        result = _find_best_p2_placement(box, new_pallet, params)
        if result is None:
            print(f"    Pallet {pallet.id:3d}: could not place P2  ✗ skipped")
            return pallet
        x, y, z, orientation = result
        pb = make_placed_box(box, x, y, z, orientation)
        pb.sequence = len(new_pallet.boxes) + 1
        new_pallet.boxes.append(pb)

    new_gap = _water_fill_gap(new_pallet, 'x', 'length', 'z', 'height')
    if new_gap < old_gap - FLOAT_TOL:
        print(f"    Pallet {pallet.id:3d}: gap {old_gap:.0f} → {new_gap:.0f} cm²  "
              f"[direction: {direction}]  ✓ accepted")
        return new_pallet
    else:
        print(f"    Pallet {pallet.id:3d}: gap {old_gap:.0f} → {new_gap:.0f} cm²  "
              f"[direction: {direction}]  ✗ no improvement")
        return pallet


# ══════════════════════════════════════════════════════════════════════════════
# Renumbering
# ══════════════════════════════════════════════════════════════════════════════

def _center_boxes(pallet: Pallet, min_shift: float = 1.0) -> Pallet:
    """
    Translates all boxes on a pallet by half the remaining space in X and Y,
    effectively centering the load and minimising CoG offset without repacking.
    Only applied when the shift in at least one axis exceeds min_shift (cm).
    """
    if not pallet.boxes:
        return pallet

    max_x = max(pb.x + pb.length for pb in pallet.boxes)
    max_y = max(pb.y + pb.width  for pb in pallet.boxes)

    shift_x = (pallet.length - max_x) / 2.0
    shift_y = (pallet.width  - max_y) / 2.0

    if abs(shift_x) < min_shift and abs(shift_y) < min_shift:
        return pallet

    new_boxes = [
        dc_replace(pb, x=pb.x + shift_x, y=pb.y + shift_y)
        for pb in pallet.boxes
    ]
    return dc_replace(pallet, boxes=new_boxes)


def _renumber(pallets: List[Pallet]) -> List[Pallet]:
    mono  = sorted([p for p in pallets if not p.is_multi_client],
                   key=lambda p: min(p.client_ids) if p.client_ids else 0)
    multi = [p for p in pallets if p.is_multi_client]
    ordered = mono + multi
    for new_id, p in enumerate(ordered, 1):
        p.id = new_id
    return ordered


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def postprocess(
    pallets: List[Pallet],
    boxes:   List[Box],
    params:  Optional[OptimizationParameters] = None,
) -> List[Pallet]:
    """
    Runs the full LNS post-processing pipeline on in-memory pallets.

    Args:
        pallets: Optimizer output — fully constructed Pallet / PlacedBox objects.
        boxes:   The original Box catalogue (used to look up canonical stackable
                 flags and allowed orientations during re-placement).
        params:  Optimisation parameters (uses defaults if None).

    Returns:
        Post-processed list of pallets.
    """
    if params is None:
        params = OptimizationParameters()

    print(f"\n{'='*60}")
    print(f"  Post-processing  (LNS)")
    print(f"{'='*60}")
    print(f"  Budget   : {params.pp_time_limit}s / {params.pp_max_iterations} iters  top-k={params.pp_top_k}")
    print(f"  Weights  : contact={params.pp_w_contact}  fill={params.pp_w_fill}  "
          f"P2={params.pp_w_p2}  height={params.pp_w_height}  "
          f"stability={params.pp_w_stability}\n")

    # ── Prepare box lookup and correct stackable flags ───────────────────────
    box_lookup = {b.id: b for b in boxes}
    for pallet in pallets:
        for pb in pallet.boxes:
            orig = box_lookup.get(pb.box_id)
            if orig:
                pb.stackable = orig.is_stackable_in(pb.orientation)

    n_pallets_in  = len(pallets)
    n_multi_in    = sum(1 for p in pallets if p.is_multi_client)

    print(f"  Loaded {n_pallets_in} pallets  "
          f"({n_multi_in} multi-client, {n_pallets_in - n_multi_in} mono-client)\n")

    # ── Group ─────────────────────────────────────────────────────────────────
    mono_groups: Dict[int, List[Pallet]] = {}
    multi_group: List[Pallet] = []

    for p in pallets:
        if p.is_multi_client:
            multi_group.append(p)
        else:
            cid = next(iter(p.client_ids)) if p.client_ids else 0
            mono_groups.setdefault(cid, []).append(p)

    result: List[Pallet] = []
    rng = random.Random(params.pp_random_seed)

    # ── LNS per mono-client group ─────────────────────────────────────────────
    for cid in sorted(mono_groups.keys()):
        group = mono_groups[cid]
        print(f"\n[Post] ── Mono-client group: client {cid}  "
              f"({len(group)} pallet(s)) ──")
        improved = _lns_group(
            group, box_lookup, params,
            rng=random.Random(rng.randint(0, 2**31)),
            label=f"[LNS|cid={cid}]",
        )
        result.extend(improved)

    # ── LNS for multi-client group (same unified strategy) ──────────────────
    if multi_group:
        print(f"\n[Post] ── Multi-client group  ({len(multi_group)} pallet(s)) ──")
        improved_multi = _lns_group(
            multi_group, box_lookup, params,
            rng=random.Random(rng.randint(0, 2**31)),
            label="[LNS|multi]",
        )
        result.extend(improved_multi)

    # ── Gap repair (water-fill detection + signed repack) ────────────────────
    gap_pallets = _detect_gap_pallets(result)
    if gap_pallets:
        print(f"\n[Post] Gap repair — {len(gap_pallets)} pallet(s) with P1 height voids:")
        result_by_id = {p.id: i for i, p in enumerate(result)}
        for pallet, xz, yz in gap_pallets:
            dominant = "XZ" if xz >= yz else "YZ"
            print(f"  Pallet {pallet.id:3d}: XZ={xz:6.0f} cm²  YZ={yz:6.0f} cm²  "
                  f"[dominant: {dominant}]")
            repacked = _repack_gap_pallet(pallet, box_lookup, params)
            result[result_by_id[pallet.id]] = repacked
    else:
        print("\n[Post] Gap repair — no P1 height voids found.")

    # ── Centre load on every pallet ──────────────────────────────────────────
    print("\n[Post] Centering boxes on each pallet...")
    result = [_center_boxes(p, min_shift=params.pp_center_min_shift) for p in result]

    # ── Safety checks ─────────────────────────────────────────────────────────
    n_multi_out = sum(1 for p in result if p.is_multi_client)
    if n_multi_out > n_multi_in:
        print(f"\n[Post] WARNING: multi-client count grew {n_multi_in} → {n_multi_out}. "
              f"Reverting affected pallets.")
        orig_by_id = {p.id: p for p in pallets}
        orig_multi_ids = {p.id for p in pallets if p.is_multi_client}
        for i, p in enumerate(result):
            if p.id in orig_multi_ids:
                orig = orig_by_id.get(p.id)
                if orig:
                    result[i] = orig
    elif n_multi_out < n_multi_in:
        print(f"\n[Post] INFO: multi-client count reduced {n_multi_in} → {n_multi_out} "
              f"(clients better separated — keeping improvement).")

    if len(result) > n_pallets_in:
        print(f"\n[Post] WARNING: pallet count grew {n_pallets_in} → {len(result)}. "
              f"Trimming.")
        result = result[:n_pallets_in]

    # ── Renumber ──────────────────────────────────────────────────────────────
    result = _renumber(result)

    n_multi_final = sum(1 for p in result if p.is_multi_client)
    all_fills     = [p.volumetric_fill_ratio for p in result if p.boxes]
    avg_fill      = sum(all_fills) / len(all_fills) if all_fills else 0.0
    total_contact = sum(_p2_p1_contact_area(p) for p in result if p.boxes)
    max_stab      = max((p.worst_stability_ratio for p in result if p.boxes), default=0.0)
    avg_height    = (sum(p.current_height for p in result if p.boxes)
                     / len(all_fills)) if all_fills else 0.0

    print(f"\n[Post] ══ Final solution ══")
    print(f"  Pallets          : {len(result)}  (was {n_pallets_in})")
    print(f"  Multi-client     : {n_multi_final}  (was {n_multi_in})")
    print(f"  Avg fill         : {avg_fill:.1%}")
    print(f"  P2→P1 contact    : {total_contact:.0f} cm² total")
    print(f"  Avg height       : {avg_height:.0f} cm")
    print(f"  Worst stability  : {max_stab:.2f}")

    return result
