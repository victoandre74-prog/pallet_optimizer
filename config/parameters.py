"""
Global optimization parameters for the 3D palletization system.

Centralizing all tunable parameters here makes it easy to adjust
the optimizer's behavior without touching the algorithmic code.
"""

from dataclasses import dataclass


@dataclass
class OptimizationParameters:
    """
    All configurable parameters for the palletization optimizer.

    Attributes:
        --- Pallet geometry ---
        pallet_length:   Pallet dimension along X axis (cm)
        pallet_width:    Pallet dimension along Y axis (cm)
        pallet_max_height: Maximum stacking height along Z axis (cm)
        pallet_max_weight: Maximum total weight per pallet (kg)

        --- Physics / stability ---
        min_support_ratio:   Minimum fraction of a box base that must rest
                             on another box or the floor (0.0 – 1.0)
        stability_ratio:     Maximum allowed ratio of stack height to its
                             narrowest base dimension (prevents tall thin towers)

        --- Ergonomics ---
        priority2_max_deposit_height: Maximum z coordinate (cm) at which the
            bottom of a priority-2 box may be placed.  Prevents manual-handling
            ergonomic issues by keeping hand-deposited boxes within reach.

        --- Multi-client strategy ---
        enable_multi_client:        Enable Phase 3 (pallet merging) and Phase 4
                                    (multi-client LNS).  Set to False to keep every
                                    pallet mono-client.
        multi_client_minimum_ratio: Soft-stop lower bound for Phase 3 in the
                                    11..70 and >70 pallet regimes — contributes
                                    to the compound stop condition.
        multi_client_maximum_ratio: Hard-stop upper bound for Phase 3 in the
                                    11..70 and >70 pallet regimes — always exits
                                    once multi/total > this ratio.
        min_filling_ratio:          Stop condition for the small-group regime
                                    (≤10 pallets).  A merge of two pallets only
                                    happens if the resulting average fill ratio
                                    would still be below this value, so the loop
                                    keeps merging while pallets are noticeably
                                    underfilled.

        --- Large Neighbourhood Search (mono-client pass) ---
        lns_mono_time_per_pallet:   Wall-clock budget per pallet in the group (seconds).
                                    Total budget = group_size × this value.
        lns_mono_small_box_volume:  Boxes below this volume (cm³) are also extracted
                                    from surviving pallets each iteration (alongside the
                                    destroyed pallets), giving the repair step more room.
        lns_mono_repair_top_k:      Pick randomly from top-k valid positions
                                    (EP × orientation) during repair.
        lns_mono_iter_per_pallet:   LNS iterations allocated per pallet in the group.
                                    Total cap = group_size × this value.
        lns_mono_random_seed:       Seed for reproducible mono-client runs.

        --- Large Neighbourhood Search (multi-client pass) ---
        lns_multi_time_per_pallet:   Wall-clock budget per pallet in the pool (seconds).
                                     Total budget = pool_size × this value.
        lns_multi_iter_per_pallet:   LNS iterations allocated per pallet in the pool.
                                     Total cap = pool_size × this value.
        lns_multi_random_seed:       Seed for reproducible multi-client runs
        lns_multi_destroy_ratio:     Fraction of least-filled pallets destroyed
                                     each iteration (at least 1 pallet)
        lns_multi_repair_top_k:      Pick randomly from top-k valid positions
                                     (EP × orientation) during repair

        --- Post-processing LNS (pp_*) ---
        pp_time_per_pallet:   Wall-clock budget per pallet in the group (seconds).
                              Total budget = group_size × this value.
        pp_iter_per_pallet:   LNS iterations allocated per pallet in the group.
                              Total cap = group_size × this value.
        pp_top_k:            Random-draw pool size for assignment (Least-Loaded-First
                             picks from the top-k candidates) and for placement
                             (_find_best_placement scores all EPs, picks the best).
        pp_random_seed:      Seed for reproducible post-processing runs.
        pp_w_contact:        Cost weight — reward P2→P1 lateral contact area (cm²).
        pp_w_fill:           Cost weight — penalise fill-ratio variance across pallets.
        pp_w_p2:             Cost weight — penalise P2-count variance across pallets.
        pp_w_height:         Cost weight — penalise mean height ratio (current / max).
        pp_w_stability:      Cost weight — penalise worst stability ratio across group.
        pp_center_min_shift: Minimum shift (cm) to apply load-centering in X or Y.
    """

    # ── Pallet geometry ────────────────────────────────────────────────────────
    pallet_length: float = 130.0       # cm  (custom -pallet: 130 × 80)
    pallet_width: float = 80.0          # cm
    pallet_max_height: float = 226.0    # cm
    pallet_max_weight: float = 600.0   # kg

    # ── Physics / stability ────────────────────────────────────────────────────
    min_support_ratio: float = 0.80      # 75% of base area must be supported
    stability_ratio: float = 7.0        # stack_height / min_base_dim < 7

    # ── Ergonomics ─────────────────────────────────────────────────────────────
    priority2_max_deposit_height: float = 160.0  # cm — max z for priority-2 box bottom

    # ── Multi-client strategy ──────────────────────────────────────────────────
    # Phase 3 merging logic — full description in pallet_optimizer.py.  Summary:
    #   ≤1 client or ≤1 pallet → skip
    #   2 pallets              → merge if avg fill < min_filling_ratio
    #   3..10 pallets          → merge 2 least if avg < min_filling_ratio,
    #                            then feed least-filled mono into multi pool
    #                            while (fill_mono + avg_fill_multi)/2 <
    #                            min_filling_ratio  (also exits if pallet count
    #                            stops decreasing)
    #   11..70 pallets         → merge 2 least, then feed mono one at a time;
    #                            stop when (multi/total > multi_client_minimum_ratio
    #                            AND fill(least mono) > min_filling_ratio)
    #                            OR multi/total > multi_client_maximum_ratio
    #   >70 pallets            → loop: merge the 2 least-filled into the multi
    #                            pool each iteration, same stop condition
    enable_multi_client: bool = True     # set False to skip Phase 3 and Phase 4 entirely
    multi_client_minimum_ratio: float = 0.13 # soft-stop lower bound (11+ pallets)
    multi_client_maximum_ratio: float = 0.20 # hard-stop upper bound (11+ pallets)
    min_filling_ratio: float = 0.45          # avg-fill threshold for the small-group regime
                                             # (≤10 pallets); merge stops once the resulting
                                             # average fill would reach this value

    # ── Post-processing ────────────────────────────────────────────────────────
    enable_post_processing: bool = True      # set False to skip Phase 5 entirely

    # ── Cost function weights — LNS Mono ──────────────────────────────────────
    # Primary goal: reduce pallet count.
    # Secondary goal: minimise fill ratio on the least-filled pallet so it is
    # a good candidate for merging with another client's pallet in Phase 3/4.
    cost_mono_pallet_count: float = 500.0
    cost_mono_last_pallet_filling: float = 400.0   # penalises high fill on least-filled pallet

    # ── Cost function weights — LNS Multi ─────────────────────────────────────
    # Single goal: reduce pallet count.
    # P2 repartition is handled by post_processing.py.
    cost_multi_pallet_count: float = 10.0

    # ── Large Neighbourhood Search — mono-client pass ─────────────────────────
    lns_mono_time_per_pallet: float = 0.1  # seconds per pallet — total = group_size × value
    lns_mono_small_box_volume: float = 408000.0  # cm³ — boxes below this volume are extracted from surviving pallets each iteration
    lns_mono_repair_top_k: int = 3              # pick randomly from top-k valid positions (EP × orientation) during repair
    lns_mono_iter_per_pallet: int = 5           # iterations per pallet — total cap = group_size × value
    lns_mono_random_seed: int = 42

    # ── Large Neighbourhood Search — multi-client pass ─────────────────────────
    lns_multi_time_per_pallet: float = 1.0  # seconds per pallet — total = pool_size × value
    lns_multi_iter_per_pallet: int = 10     # iterations per pallet — total cap = pool_size × value
    lns_multi_random_seed: int = 42
    lns_multi_destroy_ratio: float = 0.33        # fraction of least-filled pallets destroyed each iteration (at least 1)
    lns_multi_repair_top_k: int   = 3             # pick randomly from top-k valid positions during repair

    # ── Post-processing LNS — budget ───────────────────────────────────────────
    pp_time_per_pallet: float = 2.0  # seconds per pallet per group — total = group_size × value
    pp_iter_per_pallet: int   = 30   # iterations per pallet per group; split 50/50 fill/P2 phase
    pp_top_k:          int   = 2        # candidate pool for placement and donor/recip selection
    pp_random_seed:    int   = 7        # reproducibility

    # ── Post-processing LNS — cost-function weights ────────────────────────────
    pp_w_contact:   float = 10.0    # reward per cm² of P2→P1 vertical contact area
    pp_w_fill:      float = 5.0     # penalty per unit of fill-ratio variance
    pp_w_p2:        float = 5000.0  # penalty per unit of P2-count variance
    pp_w_height:    float = 5.0     # penalty for mean height ratio (lower height = better)
    pp_w_stability: float = 10.0    # penalty for worst stability ratio across group

    # ── Post-processing — centering ────────────────────────────────────────────
    pp_center_min_shift: float = 5.0    # minimum shift (cm) to apply centering in X or Y