"""
main.py — Palletization optimizer entry point.

All CSV files found in --input-dir are processed sequentially.
For each input file (e.g. test1.csv) the following outputs are created
in --output-dir:

    test1_log_<ts>.txt        — full console log (always written)
    test1_results_<ts>.csv    — optimizer placement (written ONLY on success)

The results CSV is written if and only if the batch finishes with
BATCH-STATUS code=OK (see the contract section below). This means the
mere presence of a results CSV is itself a success signal — no need to
re-validate it against the log. Integrity check failures, validation
failures and unhandled exceptions all leave the log in place but skip
the CSV write.

Usage:
    python main.py
    python main.py --input-dir input/ --output-dir output/

Tune algorithm parameters directly in config/parameters.py.
"""

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Force UTF-8 output on Windows so box-drawing / ellipsis characters print correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Path setup ─────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from config.parameters import OptimizationParameters

_SEP = "=" * 55


# ── Batch-status contract (consumed by app.py) ────────────────────────────────
# Every batch emits exactly one line of this form as the last meaningful line
# of its {stem}_log_*.txt file, just before the log is closed:
#
#     [BATCH-STATUS] stem=<stem> code=<CODE> [detail="<free text on one line>"]
#
# This line is the AUTHORITATIVE success/failure signal for the per-batch
# progress panel in app.py. Do NOT make app.py grep for free-form error text
# anywhere else in the log (it will silently break whenever the log phrasing
# changes); always read this marker instead.
#
# Codes (keep this list in sync with the reader: app.py::_read_batch_status):
#     OK               Batch fully succeeded (results written + integrity OK)
#     ERR_VALIDATION   Phase 0 — input CSV failed validation (structure/dims)
#     ERR_EMPTY_INPUT  Phase 0 — file parsed OK but yielded no boxes
#     ERR_SECURITY     Phase 6 — output boxes do not match input 1:1
#     ERR_EXCEPTION    Unhandled exception inside the pipeline
#     ERR_UNKNOWN      Fallback — should not occur in practice
#
# Absence of the marker on a given log = batch was killed before reaching the
# finally-block (e.g. process terminated externally). app.py treats that case
# based on whether the results CSV exists: present → ok, absent → fail.
BATCH_STATUS_MARKER = "[BATCH-STATUS]"


def _emit_batch_status(stem: str, code: str, detail: str = "") -> None:
    """Print the batch-status contract line. See module docstring above."""
    parts = [BATCH_STATUS_MARKER, f"stem={stem}", f"code={code}"]
    if detail:
        # Strip newlines so the contract stays a single line — the reader
        # parses by line boundaries.
        safe = detail.replace("\n", " ").replace("\r", " ").strip()
        parts.append(f'detail="{safe}"')
    print(" ".join(parts))


def _phase_header(n: int, title: str) -> None:
    print(f"\n{_SEP}")
    print(f"Phase {n} — {title}")
    print(_SEP)


def _phase_footer(n: int) -> None:
    print(f"{_SEP}")
    print(f"End of Phase {n}")
    print(f"{_SEP}")


class _Tee:
    """Writes to a log file, optionally mirroring to the original stream."""
    def __init__(self, stream, path, mirror: bool = True):
        self._stream = stream if mirror else None
        self._file   = open(path, "w", encoding="utf-8", errors="replace")

    def write(self, data):
        if self._stream:
            self._stream.write(data)
        self._file.write(data)

    def flush(self):
        if self._stream:
            self._stream.flush()
        self._file.flush()

    def close(self):
        self._file.close()

    # Proxy any other attribute lookups to the original stream
    def __getattr__(self, name):
        return getattr(self._stream, name)


from file_io.csv_reader import read_boxes_from_csv, validate_csv
from file_io.csv_writer import write_results_to_csv
from optimizer.pallet_optimizer import optimize_palletization
from heuristics.post_processing import postprocess


def parse_args():
    parser = argparse.ArgumentParser(
        description="3-D Palletization Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        default="input",
        help="Folder containing input CSV files (default: input/)."
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Folder where all output files are written (default: output/)."
    )
    parser.add_argument(
        "--params-json",
        default="{}",
        help="JSON string of parameter overrides passed to OptimizationParameters."
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        metavar="N",
        help="Number of CSV files processed in parallel (default: 1 = sequential).",
    )
    return parser.parse_args()


def _collect_inputs(input_dir: str) -> list[Path]:
    """Returns all .csv files in input_dir, sorted alphabetically."""
    folder = Path(input_dir)
    if not folder.is_dir():
        print(f"ERROR: Input folder not found: {input_dir}")
        sys.exit(1)
    files = sorted(folder.glob("*.csv"))
    if not files:
        print(f"ERROR: No CSV files found in: {input_dir}")
        sys.exit(1)
    return files


def _process_one(
    input_path: Path,
    output_dir: Path,
    params: OptimizationParameters,
    quiet: bool = False,
) -> tuple:
    """Runs the full optimization pipeline for a single input CSV.

    Returns a 3-tuple `(check_ok, status_code, status_detail)` where:
      * check_ok       True iff the batch succeeded end-to-end.
      * status_code    Same code emitted by the BATCH-STATUS marker (OK,
                       ERR_VALIDATION, ERR_EMPTY_INPUT, ERR_SECURITY,
                       ERR_EXCEPTION, ERR_UNKNOWN).
      * status_detail  Free-text detail about the failure (empty on OK).

    The caller (`main()`) aggregates these to write the batch summary file.
    """

    from datetime import datetime
    stem        = input_path.stem
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results_path  = output_dir / f"{stem}_results_{ts}.csv"
    report_path   = output_dir / f"{stem}_log_{ts}.txt"

    # ── Start log ─────────────────────────────────────────────────────────────
    _original_stdout = sys.stdout
    tee = _Tee(sys.stdout, str(report_path), mirror=not quiet)
    sys.stdout = tee

    # Batch-status contract state. Every code path below MUST set these before
    # returning so the marker emitted in the finally-block reflects reality.
    # ERR_UNKNOWN is the fallback (a path that forgot to set the code).
    status_code   = "ERR_UNKNOWN"
    status_detail = ""

    try:
        t_start = time.time()

        print(f"\n{_SEP}")
        print(f"  3-D Palletization Optimizer — {input_path.name}")
        print(f"{_SEP}")
        print(f"  Input      : {input_path}")
        print(f"  Output     : {results_path}")
        print(f"  Time Stamp : {ts_display}")
        print(f"  --- Pallet geometry ---")
        print(f"  pallet_length              : {params.pallet_length} cm")
        print(f"  pallet_width               : {params.pallet_width} cm")
        print(f"  pallet_max_height          : {params.pallet_max_height} cm")
        print(f"  pallet_max_weight          : {params.pallet_max_weight} kg")
        print(f"  --- Physics / stability ---")
        print(f"  min_support_ratio          : {params.min_support_ratio}")
        print(f"  stability_ratio            : {params.stability_ratio}")
        print(f"  --- Ergonomics ---")
        print(f"  priority2_max_deposit_height: {params.priority2_max_deposit_height} cm")
        print(f"  --- Multi-client strategy ---")
        print(f"  enable_multi_client        : {params.enable_multi_client}")
        print(f"  min_filling_ratio          : {params.min_filling_ratio}")
        print(f"  multi_client_minimum_ratio : {params.multi_client_minimum_ratio}")
        print(f"  multi_client_maximum_ratio : {params.multi_client_maximum_ratio}")
        print(f"  --- LNS mono-client ---")
        print(f"  lns_mono_time_per_pallet   : {params.lns_mono_time_per_pallet} s/palette")
        print(f"  lns_mono_small_box_volume  : {params.lns_mono_small_box_volume} cm³")
        print(f"  lns_mono_repair_top_k      : {params.lns_mono_repair_top_k}")
        print(f"  lns_mono_iter_per_pallet   : {params.lns_mono_iter_per_pallet} iters/palette")
        print(f"  lns_mono_random_seed       : {params.lns_mono_random_seed}")
        print(f"  --- LNS multi-client ---")
        print(f"  lns_multi_time_per_pallet  : {params.lns_multi_time_per_pallet} s/palette")
        print(f"  lns_multi_iter_per_pallet  : {params.lns_multi_iter_per_pallet} iters/palette")
        print(f"  lns_multi_destroy_ratio    : {params.lns_multi_destroy_ratio}")
        print(f"  lns_multi_repair_top_k     : {params.lns_multi_repair_top_k}")
        print(f"  lns_multi_random_seed      : {params.lns_multi_random_seed}")
        print(f"  --- Post-processing ---")
        print(f"  enable_post_processing     : {params.enable_post_processing}")
        print(f"  pp_time_per_pallet         : {params.pp_time_per_pallet} s/palette")
        print(f"  pp_iter_per_pallet         : {params.pp_iter_per_pallet} iters/palette")
        print(f"  pp_top_k                   : {params.pp_top_k}")
        print(f"  pp_random_seed             : {params.pp_random_seed}")
        print(f"  pp_w_contact               : {params.pp_w_contact}")
        print(f"  pp_w_fill                  : {params.pp_w_fill}")
        print(f"  pp_w_p2                    : {params.pp_w_p2}")
        print(f"  pp_center_min_shift        : {params.pp_center_min_shift} cm")
        print(f"{_SEP}\n")

        # ── Phase 0: CSV validation and box loading ────────────────────────────
        _phase_header(0, "Control of input CSV")
        print(f"  File : {input_path.name}")

        errors = validate_csv(str(input_path), pallet_max_height=params.pallet_max_height)
        if errors:
            print(f"\n  CSV VALIDATION FAILED — {len(errors)} error(s):")
            for err in errors:
                print(f"    [ERROR] {err}")
            _phase_footer(0)
            print(f"\n[Aborted] Fix the input file and retry.")
            status_code   = "ERR_VALIDATION"
            status_detail = f"{len(errors)} validation error(s)"
            return False, status_code, status_detail

        boxes = read_boxes_from_csv(str(input_path))
        if not boxes:
            print("  ERROR: No boxes loaded. Check the CSV format.")
            _phase_footer(0)
            status_code   = "ERR_EMPTY_INPUT"
            status_detail = "no boxes loaded from CSV"
            return False, status_code, status_detail

        unique_clients = len({b.client_id for b in boxes})
        print(f"  Boxes  : {len(boxes)}")
        print(f"  Clients: {unique_clients}")
        print(f"  Status : OK")
        _phase_footer(0)

        # ── Phases 1–4: optimizer ─────────────────────────────────────────────
        pallets = optimize_palletization(boxes, params)

        # ── Phase 5: post-processing ──────────────────────────────────────────
        _phase_header(5, "Post-processing (P2 repartition, fill repartition, centering)")
        if params.enable_post_processing:
            pallets = postprocess(pallets, boxes, params)
        else:
            print("  Skipped (enable_post_processing = False).")
        _phase_footer(5)

        # ── Phase 6: security check (BEFORE writing results) ──────────────────
        # The results CSV is written only when this check passes — see contract
        # requested by the operator: a {stem}_results_*.csv file MUST imply a
        # successful, integrity-verified batch (BATCH-STATUS code=OK). The check
        # therefore runs against the in-memory `pallets` list, not the not-yet-
        # written CSV.
        _phase_header(6, "Security check — box integrity")
        input_ids  = [b.id for b in boxes]
        input_set  = set(input_ids)
        output_ids = [pb.box_id for p in pallets for pb in p.boxes]
        output_set = set(output_ids)
        input_map: dict[str, object] = {b.id: b for b in boxes}

        check_ok        = True
        security_reason = ""
        if len(output_ids) != len(input_ids):
            print(f"  [FAIL] Box count mismatch : input={len(input_ids)}, output={len(output_ids)}")
            check_ok = False
            security_reason = f"count mismatch input={len(input_ids)} output={len(output_ids)}"
        missing = input_set - output_set
        if missing:
            print(f"  [FAIL] {len(missing)} box id(s) from input not found in output:")
            for bid in sorted(missing)[:10]:
                print(f"         - {bid}")
            if len(missing) > 10:
                print(f"         ... and {len(missing) - 10} more.")
            check_ok = False
            if not security_reason:
                security_reason = f"{len(missing)} box(es) missing in output"
        extra = output_set - input_set
        if extra:
            print(f"  [FAIL] {len(extra)} box id(s) in output not present in input:")
            for bid in sorted(extra)[:10]:
                print(f"         - {bid}")
            check_ok = False
            if not security_reason:
                security_reason = f"{len(extra)} extra box(es) in output"
        # ── Sequence uniqueness per pallet ───────────────────────────────────
        seq_errors: list[str] = []
        for p in pallets:
            seen_seqs: dict[int, list[str]] = {}
            for pb in p.boxes:
                seen_seqs.setdefault(pb.sequence, []).append(pb.box_id)
            for seq, box_ids in seen_seqs.items():
                if len(box_ids) > 1:
                    seq_errors.append(
                        f"pallet {p.id}: sequence {seq} shared by "
                        + ", ".join(box_ids[:5])
                        + (f" … (+{len(box_ids)-5} more)" if len(box_ids) > 5 else "")
                    )
        if seq_errors:
            print(f"  [FAIL] Sequence duplicates found ({len(seq_errors)} pallet(s) affected):")
            for msg in seq_errors:
                print(f"         - {msg}")
            check_ok = False
            if not security_reason:
                security_reason = f"sequence duplicates in {len(seq_errors)} pallet(s)"

        # ── Field-level immutability check ────────────────────────────────────
        # For each placed box whose box_id exists in input, verify that the
        # fields copied from Box to PlacedBox have not been mutated:
        #   client_id, priority, weight, orientation (must be in allowed list),
        #   placed dimensions (must match get_oriented_dims(L,W,H,orientation)).
        field_errors: list[str] = []
        for p in pallets:
            for pb in p.boxes:
                orig = input_map.get(pb.box_id)
                if orig is None:
                    continue  # unknown box_id already caught by the extra-boxes check
                violations: list[str] = []

                if pb.client_id != orig.client_id:
                    violations.append(
                        f"client_id: input={orig.client_id} → output={pb.client_id}"
                    )
                if pb.priority != orig.priority:
                    violations.append(
                        f"priority: input={orig.priority} → output={pb.priority}"
                    )
                if pb.weight != orig.weight:
                    violations.append(
                        f"weight: input={orig.weight} → output={pb.weight}"
                    )
                if pb.orientation not in orig.allowed_orientations:
                    allowed_str = ", ".join(o.value for o in orig.allowed_orientations)
                    violations.append(
                        f"orientation: placed={pb.orientation.value!r} not in"
                        f" allowed=[{allowed_str}]"
                    )
                # Dimension coherence: placed dims must equal
                # orig.get_oriented_dims(placed_orientation)
                exp_l, exp_w, exp_h = orig.get_oriented_dims(pb.orientation)
                if pb.length != exp_l or pb.width != exp_w or pb.height != exp_h:
                    violations.append(
                        f"dims: placed=({pb.length}×{pb.width}×{pb.height})"
                        f" ≠ expected=({exp_l}×{exp_w}×{exp_h})"
                        f" for orientation={pb.orientation.value}"
                    )

                if violations:
                    field_errors.append(
                        f"box_id={pb.box_id!r} pallet={p.id}: "
                        + " | ".join(violations)
                    )

        if field_errors:
            print(f"  [FAIL] Box field mutations detected ({len(field_errors)} box(es) affected):")
            for msg in field_errors[:10]:
                print(f"         - {msg}")
            if len(field_errors) > 10:
                print(f"         ... and {len(field_errors) - 10} more.")
            check_ok = False
            if not security_reason:
                security_reason = f"{len(field_errors)} box(es) with mutated fields"

        if check_ok:
            print(f"  [OK] All {len(input_ids)} box(es) accounted for — input matches output.")
            print(f"  [OK] Sequence numbers are unique within each pallet.")
            print(f"  [OK] Box field integrity verified (client, priority, weight, dims, orientation).")
        _phase_footer(6)

        # ── Write results — only on a clean integrity check ───────────────────
        if check_ok:
            write_results_to_csv(pallets, str(results_path))
            print(f"  Result saved to : {results_path}")
        else:
            print(f"  Result NOT written ({results_path.name}) — integrity check failed.")

        print(f"\n{_SEP}")
        print(f"  Total runtime : {time.time() - t_start:.1f}s")
        if check_ok:
            print(f"  Output        : {results_path.name}")
        print(f"{_SEP}")

        if check_ok:
            status_code   = "OK"
            status_detail = ""
        else:
            status_code   = "ERR_SECURITY"
            status_detail = security_reason
        return check_ok, status_code, status_detail

    except Exception as e:
        print(f"\n{_SEP}")
        print(f"  UNEXPECTED ERROR")
        print(f"{_SEP}")
        traceback.print_exc(file=sys.stdout)
        print(f"{_SEP}")
        print(f"\n[Aborted] Processing of {input_path.name} failed.")
        status_code   = "ERR_EXCEPTION"
        # Keep detail short: first line of the exception, truncated. Full
        # traceback is already printed above for operators.
        status_detail = (str(e) or type(e).__name__)[:200]
        return False, status_code, status_detail

    finally:
        # ── Close log ─────────────────────────────────────────────────────────
        # Emit the batch-status contract line FIRST so it lands in the log
        # file (it goes through the still-active tee).  Restoring sys.stdout
        # and closing the tee happen AFTER.  See BATCH_STATUS_MARKER docstring.
        _emit_batch_status(stem, status_code, status_detail)

        sys.stdout = _original_stdout
        tee.close()
        print(f"[Log] Execution report written to: {report_path}")


def _write_execution_summary(
    output_dir: Path,
    input_dir: str,
    results: list,
    ts: str,
    total_time_s: float = 0.0,
) -> Path:
    """
    Writes a human-readable summary of a full batch run to
    `execution_summary_<ts>.txt` in `output_dir`.

    Each `results` entry is a dict: {"name", "stem", "status_code",
    "status_detail"}. The summary contains:
      * a header (timestamp, input/output dirs, totals),
      * a count breakdown of error codes,
      * a per-file table aligned for quick scanning.

    Returns the path of the written file.
    """
    summary_path = output_dir / f"execution_summary_{ts}.txt"

    total = len(results)
    n_ok  = sum(1 for r in results if r["status_code"] == "OK")
    n_err = total - n_ok

    # Count failures grouped by error code (excluding OK)
    err_counts = {}
    for r in results:
        code = r["status_code"]
        if code != "OK":
            err_counts[code] = err_counts.get(code, 0) + 1

    sep = "=" * 62
    lines = []
    lines.append(sep)
    lines.append(f"  Execution Summary — {ts}")
    lines.append(f"  Input directory  : {input_dir}")
    lines.append(f"  Output directory : {output_dir}")
    lines.append(sep)
    lines.append(f"  Total files : {total}")
    lines.append(f"  Succeeded   : {n_ok}")
    lines.append(f"  Failed      : {n_err}")
    lines.append(f"  Total time  : {total_time_s:.1f}s")
    lines.append(sep)
    lines.append("")

    if err_counts:
        lines.append("Errors by type:")
        # Sort by count desc, then code asc, for determinism
        for code in sorted(err_counts, key=lambda c: (-err_counts[c], c)):
            lines.append(f"  {code:<16} : {err_counts[code]}")
        lines.append("")

    lines.append("Per-file results:")
    # Align the [code] column for readability
    code_width = max((len(r["status_code"]) for r in results), default=2) + 2
    for r in results:
        tag = f"[{r['status_code']}]".ljust(code_width)
        line = f"  {tag} {r['name']}"
        if r["status_code"] != "OK" and r["status_detail"]:
            line += f"  — {r['status_detail']}"
        lines.append(line)

    summary_path.write_text("\n".join(lines) + "\n",
                            encoding="utf-8", errors="replace")
    return summary_path


def main():
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_files = _collect_inputs(args.input_dir)

    import json
    try:
        overrides = json.loads(args.params_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid --params-json: {e}")
        sys.exit(1)
    params = OptimizationParameters(**overrides)

    max_workers = args.max_workers
    if max_workers > 1 and len(input_files) < 4:
        print(f"[Batch] Only {len(input_files)} file(s) — parallel mode requires ≥ 4, falling back to sequential.")
        max_workers = 1
    print(f"[Batch] {len(input_files)} file(s) to process from '{args.input_dir}'"
          + (f" — {max_workers} parallel worker(s)" if max_workers > 1 else ""))

    t_batch_start = time.time()
    failed  = 0
    results = []  # collected per-file outcomes for the summary file

    if max_workers == 1:
        for i, input_path in enumerate(input_files, start=1):
            print(f"\n[Batch] [{i}/{len(input_files)}] Processing: {input_path.name}")
            ok, status_code, status_detail = _process_one(input_path, output_dir, params)
            if not ok:
                failed += 1
            results.append({
                "name":          input_path.name,
                "stem":          input_path.stem,
                "status_code":   status_code,
                "status_detail": status_detail,
            })
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(_process_one, p, output_dir, params, True): p
                for p in input_files
            }
            completed = 0
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                completed += 1
                try:
                    ok, status_code, status_detail = future.result()
                except Exception as e:
                    ok, status_code, status_detail = False, "ERR_EXCEPTION", str(e)
                print(f"[Batch] [{completed}/{len(input_files)}] Done: {path.name} → {status_code}")
                if not ok:
                    failed += 1
                results.append({
                    "name":          path.name,
                    "stem":          path.stem,
                    "status_code":   status_code,
                    "status_detail": status_detail,
                })

    print(f"\n[Batch] All {len(input_files)} file(s) processed — {failed} failure(s).")

    # ── Execution summary file ────────────────────────────────────────────────
    # Aggregates per-file outcomes (OK / ERR_*) into a single human-readable
    # report at the root of the output directory. Driven by the BATCH-STATUS
    # codes defined alongside main.py::BATCH_STATUS_MARKER.
    try:
        from datetime import datetime
        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = _write_execution_summary(output_dir, args.input_dir, results, ts, time.time() - t_batch_start)
        print(f"[Summary] Execution summary written to: {summary_path}")
    except Exception as e:
        print(f"[Summary] Warning: could not write execution summary: {e}")

    # Generate KPI Excel report from all result CSVs in output_dir
    try:
        from visualization.view_kpi import generate_excel_report
        excel_path = generate_excel_report(str(output_dir))
        print(f"[Excel] KPI report written to: {excel_path}")
    except Exception as e:
        print(f"[Excel] Warning: could not generate KPI report: {e}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
