"""
Main optimizer — orchestrates the palletization strategy.

Phase 1 — Mono-client packing
    Boxes are grouped by client.  Each client's boxes are packed into
    their own pallets using FFD.  This minimises mixed-client pallets.

Phase 2 — LNS improvement (mono-client)
    LNS improves the mono-client pallets from Phase 1.  Creating new
    mixed-client pallets during repair is forbidden.

Phase 3 — Multi-client merging (adaptive)
    Behaviour depends on the number of pallets and distinct clients.  Two
    parameters tune it:
      * `min_filling_ratio`        — average-fill threshold used in the
                                     small-group regime (≤10 pallets).
      * `multi_client_minimum_ratio` — soft-stop lower bound for the large-group
                                       regime (≥11 pallets), expressed as
                                       multi/total.
      * `multi_client_maximum_ratio` — hard-stop upper bound for the large-group
                                       regime (≥11 pallets), expressed as
                                       multi/total.

    Regimes:
      - 1 client OR 1 pallet  → skip
      - 2 pallets             → merge if (fill_a + fill_b)/2 < min_filling_ratio
      - 3..10 pallets         → merge the 2 least-filled only if their average
                                fill is below min_filling_ratio, then loop:
                                feed the least-filled mono pallet into the
                                multi pool while
                                  (fill_least_mono + avg_fill_multi)/2
                                  < min_filling_ratio.
                                Loop also exits if the total pallet count
                                stops decreasing (no improvement).
      - 11..70 pallets        → merge the 2 least-filled, then feed mono
                                one-at-a-time into the multi pool; stop when
                                (multi/total > multi_client_minimum_ratio AND
                                fill(least mono) > min_filling_ratio)
                                OR multi/total > multi_client_maximum_ratio.
      - >70 pallets           → loop: at each iteration merge the 2
                                least-filled pallets directly into the multi
                                pool (twice as fast for very large batches);
                                same stop condition as the 11..70 regime.

Phase 4 — LNS improvement (multi-client + Phase 3 leftover mono)
    LNS improves the multi-client pallets produced by Phase 3.  In addition,
    any "leftover" mono pallets created by Phase 3 — boxes from one client
    that FFD couldn't merge with the rest during a repack — are also fed into
    the LNS pool, giving them a second chance via the destroy/repair cycle
    (shuffle + top-k perturbation can find a mix FFD's greedy heuristic
    missed).  Untouched original mono pallets pass through unchanged.

    Leftovers are identified by Python object identity against the snapshot
    taken before Phase 3 (any current mono whose `id()` isn't in the snapshot
    is necessarily a fresh object created by an `_repack_pallets` call).

    For the "2 pallets" regime, the Phase 3 merge is tentative: after Phase 4
    the orchestrator compares the final pallet count to the snapshot, and
    reverts to the original 2 mono pallets if no improvement was made.
"""

from typing import List

from models.box import Box
from models.pallet import Pallet
from config.parameters import OptimizationParameters
from heuristics.sorting import sort_boxes_for_packing, sort_boxes_by_client
from heuristics.first_fit_decreasing import pack_boxes_ffd
from heuristics.lns_mono import lns_mono_client
from heuristics.lns_multi import lns_multi_client

_SEP = "=" * 55


def _phase_header(n: int, title: str) -> None:
    print(f"\n{_SEP}")
    print(f"Phase {n} — {title}")
    print(_SEP)


def _phase_footer(n: int) -> None:
    print(f"{_SEP}")
    print(f"End of Phase {n}")
    print(f"{_SEP}")


def _next_id(pallets: List[Pallet]) -> int:
    """Returns the smallest integer ID not yet used by any pallet."""
    if not pallets:
        return 1
    return max(p.id for p in pallets) + 1


# ── Phase 1: mono-client packing ───────────────────────────────────────────────

def pack_mono_client(
    boxes: List[Box],
    params: OptimizationParameters
) -> List[Pallet]:
    """
    Packs boxes independently per client.

    Each client's boxes are sorted and fed into FFD on a fresh set of pallets.
    The resulting pallets should all be mono-client.

    Returns a flat list of all pallets produced.
    """
    client_groups = sort_boxes_by_client(boxes)
    all_pallets: List[Pallet] = []

    for client_id, client_boxes in sorted(client_groups.items()):
        print(f"[Phase 1] Packing client {client_id} "
              f"({len(client_boxes)} boxes)…")
        client_pallets = pack_boxes_ffd(
            client_boxes, params,
            next_pallet_id=_next_id(all_pallets)
        )
        all_pallets.extend(client_pallets)
        print(f"[Phase 1] Client {client_id}: {len(client_pallets)} pallets.")

    return all_pallets


# ── Phase 3: helpers ───────────────────────────────────────────────────────────

def _extract_boxes(pallets: List[Pallet], box_lookup: dict) -> List[Box]:
    """Collect original Box objects from a list of pallets."""
    boxes: List[Box] = []
    for pallet in pallets:
        for pb in pallet.boxes:
            original = box_lookup.get(pb.box_id)
            if original:
                boxes.append(original)
    return boxes


def _repack_pallets(
    pallets_to_repack: List[Pallet],
    well_filled: List[Pallet],
    box_lookup: dict,
    params: OptimizationParameters,
    iteration: int,
    label: str = "",
) -> List[Pallet]:
    """Disassemble *pallets_to_repack*, repack with FFD, keep *well_filled* intact."""
    boxes_to_repack = _extract_boxes(pallets_to_repack, box_lookup)

    print(
        f"[Phase 3 | iter {iteration}] Repacking {len(boxes_to_repack)} boxes "
        f"from {len(pallets_to_repack)} pallet(s){label}…"
    )

    sorted_repack = sort_boxes_for_packing(boxes_to_repack)
    new_pallets = pack_boxes_ffd(
        sorted_repack, params,
        next_pallet_id=_next_id(well_filled),
    )
    result_pallets = well_filled + new_pallets

    new_multi = sum(1 for p in new_pallets if p.is_multi_client)
    print(
        f"[Phase 3 | iter {iteration}] Created {len(new_pallets)} pallet(s) "
        f"({new_multi} multi-client). Total: {len(result_pallets)}."
    )
    return result_pallets


# ── Renumbering ────────────────────────────────────────────────────────────────

def _renumber_pallets(pallets: List[Pallet]) -> List[Pallet]:
    """
    Renumbers pallets so that mono-client pallets come first (1…Y-X),
    sorted by client_id ascending, and multi-client pallets come last
    (Y-X+1…Y), where Y is the total number of pallets and X is the
    number of multi-client pallets.

    Returns the same list, reordered and with updated ids.
    """
    mono   = sorted(
        [p for p in pallets if not p.is_multi_client],
        key=lambda p: min(p.client_ids) if p.client_ids else 0,
    )
    multi  = [p for p in pallets if p.is_multi_client]

    ordered = mono + multi
    for new_id, pallet in enumerate(ordered, start=1):
        pallet.id = new_id

    return ordered


# ── Public API ─────────────────────────────────────────────────────────────────

def optimize_palletization(
    boxes: List[Box],
    parameters: OptimizationParameters,
) -> List[Pallet]:
    """
    Entry point for the palletization optimizer.

    Runs:
        Phase 1 — mono-client FFD
        Phase 2 — LNS on mono-client pallets
        Phase 3 — repack underfilled pallets
        Phase 4 — LNS on multi-client pallets

    Args:
        boxes:      All boxes to be packed.
        parameters: Tuning parameters for the algorithm.

    Returns:
        Optimized list of pallets with their placed boxes.
    """
    if not boxes:
        print("[Optimizer] No boxes to pack.")
        return []

    print(f"[Optimizer] {len(boxes)} boxes to optimize across "
          f"{len({b.client_id for b in boxes})} client(s).")

    # ── Phase 1: mono-client FFD ──────────────────────────────────────────────
    _phase_header(1, "Mono-client packing")
    pallets = pack_mono_client(boxes, parameters)
    phase1_pallet_count = len(pallets)
    print(f"  Result : {phase1_pallet_count} pallet(s)")
    _phase_footer(1)

    # ── Phase 2: LNS on mono-client pallets ───────────────────────────────────
    _phase_header(2, "LNS improvement (mono-client)")
    if parameters.lns_mono_iter_per_pallet > 0 and len(pallets) > 1:
        pallets = lns_mono_client(pallets, boxes, parameters)
    else:
        print("  Skipped (single pallet or iter_per_pallet=0).")
    print(f"  Result : {len(pallets)} pallet(s)")
    _phase_footer(2)

    # ── Phase 3: adaptive multi-client merging ─────────────────────────────────
    unique_clients = {b.client_id for b in boxes}
    n_pallets = len(pallets)

    _phase_header(3, "Adaptive multi-client merging")

    # --- Skip conditions ---
    def _skip_phase3_and_4(reason: str):
        """Helper to skip both Phase 3 and Phase 4 cleanly."""
        print(f"  Skipped ({reason}).")
        nonlocal pallets
        pallets = _renumber_pallets(pallets)
        _phase_footer(3)
        _phase_header(4, "LNS improvement (multi-client, single pass)")
        print(f"  Skipped ({reason}).")
        _phase_footer(4)
        multi = sum(1 for p in pallets if p.is_multi_client)
        print(
            f"\n[Optimizer] ══ Raw solution ══\n"
            f"  Pallets used : {len(pallets)}\n"
            f"  Multi-client : {multi}\n"
        )

    if not parameters.enable_multi_client:
        _skip_phase3_and_4("enable_multi_client=False")
        return pallets

    if len(unique_clients) <= 1:
        _skip_phase3_and_4("single client")
        return pallets

    if n_pallets <= 1:
        _skip_phase3_and_4("single pallet")
        return pallets

    box_lookup = {b.id: b for b in boxes}
    iteration  = 0

    # Snapshot of the pre-Phase-3 state. Used by Phase 4 to detect "leftover"
    # mono pallets created by FFD inside _repack_pallets: any current mono
    # whose `id()` isn't in this snapshot is necessarily a fresh object that
    # came out of a repack (and thus a candidate for re-mixing in LNS-multi).
    phase3_initial_state = pallets[:]

    # Helper: average volumetric fill of a list of pallets (0.0 if empty).
    def _avg_fill(pool):
        return (sum(p.volumetric_fill_ratio for p in pool) / len(pool)) if pool else 0.0

    min_fill = parameters.min_filling_ratio

    # ── Regime: exactly 2 pallets ────────────────────────────────────────────
    if n_pallets == 2:
        avg_fill = _avg_fill(pallets)
        if avg_fill < min_fill:
            iteration = 1
            print(f"  2 pallets, avg fill {avg_fill:.1%} < {min_fill:.0%} → merging.")
            pallets = _repack_pallets(
                pallets, [], box_lookup, parameters, iteration,
                label=" (2 pallets together)",
            )
        else:
            print(f"  2 pallets, avg fill {avg_fill:.1%} ≥ {min_fill:.0%} → no merge.")

    # ── Regime: 3..10 pallets — fill-driven feeding loop ────────────────────
    elif n_pallets <= 10:
        # Initial merge of the 2 least-filled, only if their avg fill is below
        # the threshold (otherwise nothing to gain).
        sorted_by_fill = sorted(pallets, key=lambda p: p.volumetric_fill_ratio)
        two_least      = sorted_by_fill[:2]
        well_filled    = sorted_by_fill[2:]
        init_avg       = _avg_fill(two_least)

        if init_avg >= min_fill:
            print(f"  ≤10 pallets: 2 least-filled avg {init_avg:.1%} ≥ "
                  f"{min_fill:.0%} → no initial merge, skipping loop.")
        else:
            iteration = 1
            print(f"  ≤10 pallets: initial merge of 2 least-filled "
                  f"(avg {init_avg:.1%} < {min_fill:.0%}).")
            repack_pool = _repack_pallets(
                two_least, [], box_lookup, parameters, iteration,
                label=" (2 least-filled, initial)",
            )
            pallets = well_filled + repack_pool

            # Feed the least-filled mono into the multi pool while the projected
            # combined average is still below min_filling_ratio AND each merge
            # actually reduces the total pallet count (else we're spinning).
            max_iterations = phase1_pallet_count
            while iteration < max_iterations:
                if not well_filled:
                    print("  No mono-client pallets left to feed. Stopping loop.")
                    break

                well_filled_sorted = sorted(well_filled,
                                            key=lambda p: p.volumetric_fill_ratio)
                candidate          = well_filled_sorted[0]
                cand_fill          = candidate.volumetric_fill_ratio
                multi_avg          = _avg_fill(repack_pool)
                projected          = (cand_fill + multi_avg) / 2.0

                if projected >= min_fill:
                    print(f"  Combined avg ({cand_fill:.1%} + {multi_avg:.1%})/2 = "
                          f"{projected:.1%} ≥ {min_fill:.0%}. Stopping loop.")
                    break

                iteration += 1
                prev_total = len(pallets)

                mono_to_add        = [candidate]
                well_filled        = well_filled_sorted[1:]
                pallets_to_repack  = repack_pool + mono_to_add
                repack_pool = _repack_pallets(
                    pallets_to_repack, [], box_lookup, parameters, iteration,
                    label=f" ({len(mono_to_add)} mono + {len(repack_pool)} repack pool)",
                )
                pallets = well_filled + repack_pool

                # Improvement check: if the merge didn't actually reduce the
                # total pallet count, stop — feeding more won't help.
                if len(pallets) >= prev_total:
                    print(f"  No improvement on pallet count "
                          f"({prev_total} → {len(pallets)}). Stopping loop.")
                    break
            else:
                print(f"  Max iterations reached ({max_iterations}). Stopping loop.")

    # ── Regime: 11..70 pallets — multi-ratio-driven feeding loop ────────────
    elif n_pallets <= 70:
        iteration      = 1
        sorted_by_fill = sorted(pallets, key=lambda p: p.volumetric_fill_ratio)
        two_least      = sorted_by_fill[:2]
        well_filled    = sorted_by_fill[2:]
        print(f"  11..70 pallets — initial merge of 2 least-filled pallets.")
        repack_pool = _repack_pallets(
            two_least, [], box_lookup, parameters, iteration,
            label=" (2 least-filled, initial)",
        )
        pallets = well_filled + repack_pool

        max_iterations = phase1_pallet_count
        while iteration < max_iterations:
            iteration  += 1
            total_count = len(pallets)
            multi_count = sum(1 for p in pallets if p.is_multi_client)
            multi_ratio = multi_count / total_count if total_count > 0 else 0.0

            if multi_ratio > parameters.multi_client_maximum_ratio:
                print(f"  Hard cap reached: {multi_count}/{total_count} "
                      f"({multi_ratio:.1%}) > "
                      f"{parameters.multi_client_maximum_ratio:.0%}. Stopping loop.")
                break

            if multi_ratio > parameters.multi_client_minimum_ratio and well_filled:
                least_mono_fill = min(p.volumetric_fill_ratio for p in well_filled)
                if least_mono_fill > parameters.min_filling_ratio:
                    print(f"  Soft cap: {multi_ratio:.1%} > min ratio and "
                          f"least mono fill {least_mono_fill:.1%} > "
                          f"{parameters.min_filling_ratio:.0%}. Stopping loop.")
                    break

            if not well_filled:
                print("  No mono-client pallets left to feed. Stopping loop.")
                break

            well_filled_sorted = sorted(well_filled,
                                        key=lambda p: p.volumetric_fill_ratio)
            mono_to_add        = well_filled_sorted[:1]
            well_filled        = well_filled_sorted[1:]
            pallets_to_repack  = repack_pool + mono_to_add
            repack_pool = _repack_pallets(
                pallets_to_repack, [], box_lookup, parameters, iteration,
                label=f" ({len(mono_to_add)} mono + {len(repack_pool)} repack pool)",
            )
            pallets = well_filled + repack_pool
        else:
            print(f"  Max iterations reached ({max_iterations}). Stopping loop.")

    # ── Regime: >70 pallets — pair-merge loop for speed ─────────────────────
    # Two least-filled pallets are merged into the multi pool every iteration
    # (instead of one at a time) to reach the multi-client target faster on
    # very large batches.  Same stop condition as the 11..70 regime.
    else:
        repack_pool = []
        max_iterations = phase1_pallet_count
        while iteration < max_iterations:
            total_count = len(pallets)
            multi_count = sum(1 for p in pallets if p.is_multi_client)
            multi_ratio = multi_count / total_count if total_count > 0 else 0.0

            if multi_ratio > parameters.multi_client_maximum_ratio:
                print(f"  Hard cap reached: {multi_count}/{total_count} "
                      f"({multi_ratio:.1%}) > "
                      f"{parameters.multi_client_maximum_ratio:.0%}. Stopping loop.")
                break

            # well_filled = everything that's NOT in the repack pool, sorted
            # by fill ratio ascending.  We pick its 2 least-filled.
            repack_ids  = {id(p) for p in repack_pool}
            well_filled = [p for p in pallets if id(p) not in repack_ids]

            if multi_ratio > parameters.multi_client_minimum_ratio and well_filled:
                least_mono_fill = min(p.volumetric_fill_ratio for p in well_filled)
                if least_mono_fill > parameters.min_filling_ratio:
                    print(f"  Soft cap: {multi_ratio:.1%} > min ratio and "
                          f"least mono fill {least_mono_fill:.1%} > "
                          f"{parameters.min_filling_ratio:.0%}. Stopping loop.")
                    break

            if len(well_filled) < 2:
                print("  Fewer than 2 mono-client pallets left. Stopping loop.")
                break

            well_filled_sorted = sorted(well_filled,
                                        key=lambda p: p.volumetric_fill_ratio)
            two_least          = well_filled_sorted[:2]
            remaining          = well_filled_sorted[2:]

            iteration += 1
            pallets_to_repack = repack_pool + two_least
            repack_pool = _repack_pallets(
                pallets_to_repack, [], box_lookup, parameters, iteration,
                label=f" (2 mono + {len(repack_pool)} repack pool)",
            )
            pallets = remaining + repack_pool
        else:
            print(f"  Max iterations reached ({max_iterations}). Stopping loop.")

    multi_end3 = sum(1 for p in pallets if p.is_multi_client)
    print(f"  Result : {len(pallets)} pallet(s) ({multi_end3} multi-client)"
          + (f" after {iteration} iteration(s)" if iteration > 0 else ""))
    _phase_footer(3)

    # ── Phase 4: LNS on multi-client pallets (single pass after loop) ─────────
    # Phase 3 may have produced "leftover" mono pallets — boxes from a single
    # client that FFD couldn't fold into the multi pool during a repack.
    # We identify them by object identity: any current mono whose `id()` is
    # NOT in the snapshot taken before Phase 3 must be a freshly-created
    # leftover (FFD always returns new Pallet instances). Phase 4 receives
    # these as `extra_mono` so its perturbation/destroy-and-repair loop gets
    # a second chance to mix them with the multi pool.
    _phase_header(4, "LNS improvement (multi-client, single pass)")
    original_ids = {id(p) for p in phase3_initial_state}
    phase3_leftover_mono = [
        p for p in pallets
        if not p.is_multi_client and id(p) not in original_ids
    ]
    multi_count = sum(1 for p in pallets if p.is_multi_client)
    pool_size   = multi_count + len(phase3_leftover_mono)

    if parameters.lns_multi_iter_per_pallet > 0 and pool_size > 1:
        if phase3_leftover_mono:
            print(f"  Including {len(phase3_leftover_mono)} Phase-3 leftover "
                  f"mono pallet(s) in the LNS pool.")
        pallets = lns_multi_client(pallets, boxes, parameters,
                                   extra_mono=phase3_leftover_mono)
    else:
        print(f"  Skipped (pool size {pool_size} ≤ 1 or iter_per_pallet=0).")
    pallets = _renumber_pallets(pallets)
    multi_p4 = sum(1 for p in pallets if p.is_multi_client)
    print(f"  Result : {len(pallets)} pallet(s) ({multi_p4} multi-client)")
    _phase_footer(4)

    multi = sum(1 for p in pallets if p.is_multi_client)
    print(
        f"\n[Optimizer] ══ Raw solution ══\n"
        f"  Pallets used : {len(pallets)}\n"
        f"  Multi-client : {multi}\n"
    )

    return pallets
