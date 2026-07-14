from __future__ import annotations

import json
from typing import Any

from app.insilicopop.memory.importance_scorer import ImportanceScorer
from app.insilicopop.memory.rules import as_rows, as_text, find_column
from app.insilicopop.memory.budget import raw_size_bucket, ratio_context, serialized_size
from app.insilicopop.memory.provenance_index import compact_provenance_ref
from app.schemas.memory import MemoryCompressRequest, MemoryCompressResponse


class DomainMemoryCompressor:
    def __init__(self) -> None:
        self.scorer = ImportanceScorer()

    def compress(self, request: MemoryCompressRequest) -> MemoryCompressResponse:
        raw_size = serialized_size(request.raw_output)
        tool = request.tool_name
        compressed: dict[str, Any] = {
            "tool_name": tool,
            "step_name": request.step_name,
            "summary": "",
            "key_facts": [],
            "retained_metrics": {},
            "warnings": [],
            "assumptions": ["Deterministic compression; no external LLM or clinical inference."],
            "downstream_dependencies": [],
            "facts": {},
        }
        retained: list[str] = []
        risks: list[str] = []
        dependencies = ["population metadata", "sample-size context"]

        if tool == "metadata":
            self._compress_metadata(request.raw_output, compressed, retained, risks)
            dependencies.extend(["population metadata", "sample-size context"])
        elif tool == "pca":
            self._compress_pca(request.raw_output, compressed, retained, risks)
            dependencies.extend(["LD pruning status", "relatedness removal status"])
        elif tool == "admixture":
            self._compress_admixture(request.raw_output, compressed, retained, risks)
            dependencies.extend(["K sweep", "CV errors", "multiple seeds"])
        elif tool == "fst":
            self._compress_fst(request.raw_output, compressed, retained, risks)
            dependencies.extend(["population labels", "per-group sample sizes"])
        elif tool == "roh":
            self._compress_roh(request.raw_output, compressed, retained, risks)
            dependencies.extend(["ROH thresholds", "founder-effect context"])
        elif tool == "selection_scan":
            self._compress_selection(request.raw_output, compressed, retained, risks)
            dependencies.extend(["multiple-testing correction", "demographic null model"])
        elif tool == "plink_qc":
            self._compress_plink_qc(request.raw_output, compressed, retained, risks)
            dependencies.extend(["QC failure thresholds", "LD pruning status", "relatedness removal status"])
        else:
            text = as_text(request.raw_output)
            compressed["facts"]["summary"] = text[:1000]
            retained.append("Generic output summary retained.")

        if request.previous_memory:
            compressed["previous_memory_keys"] = sorted(request.previous_memory.keys())
        compressed["key_facts"] = retained
        compressed["warnings"] = risks
        compressed["downstream_dependencies"] = sorted(set(dependencies + compressed["downstream_dependencies"]))
        if not compressed["summary"]:
            compressed["summary"] = f"{tool} output compressed with {len(retained)} retained facts and {len(risks)} risk flags."
        provenance_index = _build_provenance_index(request.raw_output)
        mode_memory = _memory_for_mode(
            compressed,
            request.memory_mode,
            include_provenance=request.include_provenance,
            provenance_index=provenance_index,
        )
        provenance_index = _ensure_fact_provenance_index(mode_memory, provenance_index)
        if request.include_provenance:
            if request.memory_mode == "verbose":
                mode_memory["provenance_index"] = provenance_index
            elif request.memory_mode == "compact":
                mode_memory["provenance_ids"] = sorted(provenance_index)
            else:
                mode_memory["p"] = sorted(provenance_index)
        fact_ids = _fact_ids(mode_memory)
        protected_facts = _critical_facts(mode_memory)
        compressed_size = serialized_size(mode_memory)
        compression_ratio = round(compressed_size / max(raw_size, 1), 4)
        scores = self.scorer.score_facts(retained + risks)
        return MemoryCompressResponse(
            compressed_memory=mode_memory,
            memory_mode=request.memory_mode,
            raw_size_chars=raw_size,
            compressed_size_chars=compressed_size,
            compression_ratio=compression_ratio,
            ratio_context=ratio_context(raw_size, compression_ratio),
            raw_size_bucket=raw_size_bucket(raw_size),
            critical_facts_retained=protected_facts,
            noncritical_facts_dropped=_dropped_facts(compressed, mode_memory, request.memory_mode),
            provenance_index=provenance_index if request.include_provenance else None,
            fact_ids=fact_ids,
            protected_facts=protected_facts,
            retained_facts=retained,
            risk_flags=risks,
            importance_scores=scores,
            dropped_content_summary="Raw logs, repeated rows, and boilerplate were dropped while preserving downstream population-genetics signals.",
            downstream_dependencies=sorted(set(dependencies)),
        )

    def _compress_metadata(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        summary = _summary(raw)
        if summary:
            metrics = {
                "sample_count": summary.get("sample_count"),
                "population_count": summary.get("population_count"),
                "tiny_population_groups": summary.get("tiny_population_groups", {}),
                "broad_label_warnings": summary.get("broad_label_warnings", []),
                "samples_per_population": summary.get("samples_per_population", {}),
            }
            compressed["retained_metrics"].update(metrics)
            compressed["facts"].update(metrics)
            if metrics["tiny_population_groups"]:
                risks.append("tiny population groups fewer than five")
                retained.append("Tiny population groups retained.")
            if metrics["broad_label_warnings"]:
                risks.append(f"broad Indian labels {' '.join(metrics['broad_label_warnings'])}")
                retained.append("Broad Indian population labels retained.")
            compressed["summary"] = "Metadata memory preserves sample counts, tiny groups, and broad-label caveats."
            compressed["downstream_dependencies"].append("Collect finer-grained community/endogamous group metadata.")
            return
        rows = as_rows(raw)
        if rows:
            compressed["retained_metrics"]["row_count"] = len(rows)
            retained.append("Metadata row count retained.")

    def _compress_pca(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        summary = _summary(raw)
        if summary:
            metrics = {
                "parsed_pc_columns": summary.get("parsed_pc_columns", []),
                "variance_explained_summary": summary.get("variance_explained_summary", {}),
                "eigenvalues": summary.get("eigenvalues", []),
                "outlier_samples": summary.get("outlier_samples", []),
                "ld_pruning_status": summary.get("ld_pruning_documented", "unknown"),
                "relatedness_removal_status": summary.get("relatedness_removal_documented", "unknown"),
            }
            compressed["retained_metrics"].update(metrics)
            compressed["facts"].update(metrics)
            risks.extend(summary.get("warnings", []))
            if metrics["outlier_samples"]:
                retained.append("PCA outlier samples retained.")
            if metrics["variance_explained_summary"]:
                retained.append("PCA variance explained by top PCs retained.")
            compressed["summary"] = "PCA memory preserves parsed PCs, variance explained, outliers, LD pruning status, and relatedness-removal status."
            return
        rows = as_rows(raw)
        facts = compressed["facts"]
        if rows:
            first = rows[0]
            variance = {key: value for key, value in first.items() if "variance" in str(key).lower()}
            facts["variance_explained"] = variance
            compressed["retained_metrics"]["variance_explained"] = variance
            if variance:
                retained.append("PCA variance explained by top PCs retained.")
            keys = {str(key).lower() for key in first}
            if "ld_pruned" not in keys and "ld_pruning" not in keys:
                risks.append("Missing LD pruning documentation for PCA.")
            if "relatedness_removed" not in keys:
                risks.append("Missing relatedness removal documentation for PCA.")
            outliers = [row.get("sample_id") for row in rows if str(row.get("outlier", "")).lower() in {"true", "yes", "1"}]
            facts["outliers"] = outliers
            compressed["retained_metrics"]["outlier_samples"] = outliers
            compressed["summary"] = "PCA memory preserves variance explained, outliers, and preprocessing warnings."
        else:
            text = as_text(raw).lower()
            if "ld pruning" not in text and "ld-pruned" not in text:
                risks.append("Missing LD pruning documentation for PCA.")

    def _compress_admixture(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        summary = _summary(raw)
        if summary:
            metrics = {
                "k_values_tested": summary.get("k_values_tested", []),
                "best_k_by_cv": summary.get("best_k_by_cv"),
                "cv_error_by_k": summary.get("cv_error_by_k", {}),
                "cv_curve": summary.get("cv_curve", []),
                "q_matrix_shape": summary.get("q_matrix_shape"),
                "high_admixture_samples": summary.get("high_admixture_samples", []),
                "max_component_per_sample": summary.get("max_component_per_sample", [])[:5],
                "seed_count_by_k": summary.get("seed_count_by_k", {}),
            }
            compressed["retained_metrics"].update(metrics)
            compressed["facts"].update(metrics)
            if summary.get("narrow_k_sweep_warning"):
                risks.append(summary["narrow_k_sweep_warning"])
            if summary.get("missing_seed_replicates_warning"):
                risks.append(summary["missing_seed_replicates_warning"])
            if metrics["best_k_by_cv"] is not None:
                retained.append("Best ADMIXTURE K by CV retained.")
            compressed["summary"] = f"ADMIXTURE memory preserves K values {metrics['k_values_tested']} and best K {metrics['best_k_by_cv']} by CV."
            compressed["downstream_dependencies"].append("Do not interpret ancestry components until broader K sweep and replicate stability are checked.")
            return
        rows = as_rows(raw)
        facts = compressed["facts"]
        k_values: list[int] = []
        cv_errors: dict[int, float] = {}
        for row in rows:
            k_col = find_column(row, ["k"])
            cv_col = find_column(row, ["cv_error", "cverror", "cross_validation_error"])
            if k_col and str(row.get(k_col, "")).isdigit():
                k = int(row[k_col])
                k_values.append(k)
                if cv_col:
                    cv_errors[k] = float(row[cv_col])
        facts["k_values_tested"] = sorted(set(k_values))
        facts["cv_errors"] = cv_errors
        compressed["retained_metrics"]["k_values_tested"] = sorted(set(k_values))
        compressed["retained_metrics"]["cv_errors"] = cv_errors
        if cv_errors:
            facts["best_k"] = min(cv_errors, key=cv_errors.get)
            compressed["retained_metrics"]["best_k"] = facts["best_k"]
            retained.append("ADMIXTURE K/CV result retained.")
        if k_values and max(k_values) < 10:
            risks.append("ADMIXTURE K sweep may be insufficient for Indian fine-scale structure.")
        compressed["summary"] = f"ADMIXTURE tested K={min(k_values) if k_values else '?'}-{max(k_values) if k_values else '?'}; best K={facts.get('best_k')} by CV when available."

    def _compress_fst(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        summary = _summary(raw)
        if summary:
            metrics = {
                "highest_fst_pairs": summary.get("highest_fst_pairs") or summary.get("highest_pairs", []),
                "lowest_fst_pairs": summary.get("lowest_fst_pairs") or summary.get("lowest_pairs", []),
                "high_fst_windows": summary.get("high_fst_windows", []),
                "populations_seen": summary.get("populations_seen", []),
                "matrix_shape": summary.get("matrix_shape"),
            }
            compressed["retained_metrics"].update(metrics)
            compressed["facts"].update(metrics)
            risks.extend(summary.get("sample_size_caveats", []))
            risks.extend(summary.get("overclaim_warnings", []))
            if metrics["highest_fst_pairs"]:
                retained.append("Highest FST pair retained.")
            compressed["summary"] = "FST memory preserves highest/lowest pairwise differentiation, populations seen, and matrix shape."
            return
        rows = as_rows(raw)
        pairs = []
        for row in rows:
            fst_col = find_column(row, ["fst", "pairwise_fst"])
            pop1 = find_column(row, ["pop1", "population1"])
            pop2 = find_column(row, ["pop2", "population2"])
            if fst_col and pop1 and pop2:
                pairs.append({"pop1": row[pop1], "pop2": row[pop2], "fst": float(row[fst_col])})
        ordered = sorted(pairs, key=lambda item: item["fst"], reverse=True)
        if not ordered:
            ordered = self._fst_pairs_from_matrix_rows(rows)
        compressed["facts"]["highest_fst_pairs"] = ordered[:5]
        compressed["retained_metrics"]["highest_fst_pairs"] = ordered[:5]
        if ordered:
            retained.append("Highest FST pair retained.")
        compressed["summary"] = "FST memory preserves top differentiation pairs and downstream sample-size caveats."

    def _compress_roh(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        summary = _summary(raw)
        if summary:
            metrics = {
                "high_roh_samples": summary.get("high_roh_samples", []),
                "high_roh_populations": summary.get("high_roh_populations", []),
                "roh_summary_by_population": summary.get("roh_summary_by_population", {}),
                "roh_summary_by_sample": summary.get("roh_summary_by_sample", {}),
                "roh_segment_count_by_sample": summary.get("roh_segment_count_by_sample", {}),
                "max_roh_segment_by_sample": summary.get("max_roh_segment_by_sample", {}),
            }
            compressed["retained_metrics"].update(metrics)
            compressed["facts"].update(metrics)
            risks.extend(summary.get("endogamy_interpretation_warnings", []))
            risks.extend(summary.get("founder_effect_flags", []))
            if metrics["high_roh_samples"] or metrics["high_roh_populations"]:
                retained.append("High ROH burden retained with founder/endogamy caveat.")
            compressed["summary"] = "ROH memory preserves high-burden samples, populations, population summaries, and endogamy caveats."
            return
        rows = as_rows(raw)
        high = []
        for row in rows:
            pop_col = find_column(row, ["population", "pop", "community"])
            roh_col = find_column(row, ["total_roh_mb", "roh_mb", "mean_roh_mb"])
            if pop_col and roh_col and float(row[roh_col]) >= 50:
                high.append(row[pop_col])
        compressed["facts"]["high_roh_populations"] = sorted(set(high))
        compressed["retained_metrics"]["high_roh_populations"] = sorted(set(high))
        if high:
            retained.append("High ROH burden populations retained.")
            risks.append("High ROH burden may reflect endogamy or founder effects, not automatic disease.")
        compressed["summary"] = "ROH memory preserves high-burden populations and founder/endogamy caveats."

    def _compress_selection(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        summary = _summary(raw)
        if summary:
            metrics = {
                "top_candidate_regions": summary.get("top_candidate_regions", []),
                "statistic_used": summary.get("statistic_used") or summary.get("statistic"),
                "correction_status": summary.get("multiple_testing_status") or summary.get("correction_status"),
            }
            compressed["retained_metrics"].update(metrics)
            compressed["facts"].update(metrics)
            risks.extend(summary.get("overclaim_warnings", []))
            if metrics["correction_status"] == "not_documented":
                risks.append("Missing multiple-testing correction for selection scan.")
            if metrics["top_candidate_regions"]:
                retained.append("Selection candidate regions retained.")
            compressed["summary"] = "Selection memory preserves candidate regions, statistic used, correction status, and overclaim caveats."
            return
        rows = as_rows(raw)
        regions = []
        statistic = None
        corrected = False
        for row in rows:
            region_col = find_column(row, ["region", "locus", "variant"])
            stat_col = find_column(row, ["statistic", "method"])
            corr_col = find_column(row, ["multiple_testing_corrected", "corrected"])
            if region_col:
                regions.append(row[region_col])
            if stat_col and statistic is None:
                statistic = row[stat_col]
            if corr_col and str(row[corr_col]).lower() in {"true", "yes", "1"}:
                corrected = True
        compressed["facts"]["top_candidate_regions"] = regions[:5]
        compressed["facts"]["statistic"] = statistic
        compressed["facts"]["multiple_testing_corrected"] = corrected
        compressed["retained_metrics"]["top_candidate_regions"] = regions[:5]
        compressed["retained_metrics"]["statistic"] = statistic
        compressed["retained_metrics"]["multiple_testing_corrected"] = corrected
        if regions:
            retained.append("Selection candidate regions retained.")
        if not corrected:
            risks.append("Selection candidate without correction requires demographic/founder-effect caveat.")
        compressed["summary"] = "Selection-scan memory preserves candidate regions, statistic, correction status, and caveats."

    def _compress_plink_qc(self, raw: Any, compressed: dict[str, Any], retained: list[str], risks: list[str]) -> None:
        rows = as_rows(raw)
        summary = _summary(raw)
        source_type = None
        if isinstance(raw, dict):
            source_type = raw.get("metadata", {}).get("source_type") if isinstance(raw.get("metadata"), dict) else None
        metrics: dict[str, Any] = {"row_count": len(rows), "source_type": source_type}
        high_missing_samples = []
        high_missing_variants = []
        related_pairs = []
        prune_counts = {"kept": 0, "removed": 0}
        for row in rows:
            lowered = {str(key).lower(): key for key in row}
            f_miss = lowered.get("f_miss")
            if f_miss and _is_number(row.get(f_miss)) and float(row[f_miss]) >= 0.05:
                target = high_missing_samples if (lowered.get("iid") or lowered.get("sample_id")) else high_missing_variants
                target.append(row)
            pi_hat = lowered.get("pi_hat")
            if pi_hat and _is_number(row.get(pi_hat)) and float(row[pi_hat]) >= 0.125:
                related_pairs.append(row)
            status = lowered.get("status")
            if status:
                value = str(row.get(status)).lower()
                if value in prune_counts:
                    prune_counts[value] += 1
        metrics.update(
            {
                "high_missing_samples": len(high_missing_samples),
                "high_missing_variants": len(high_missing_variants),
                "related_pairs_pi_hat_ge_0_125": len(related_pairs),
                "ld_prune_counts": {key: value for key, value in prune_counts.items() if value},
            }
        )
        compressed["retained_metrics"].update({key: value for key, value in metrics.items() if value not in (None, {}, [], 0)})
        compressed["facts"].update(compressed["retained_metrics"])
        if high_missing_samples:
            risks.append("PLINK individual missingness has samples with F_MISS >= 0.05.")
            retained.append("PLINK sample missingness failures retained.")
        if high_missing_variants:
            risks.append("PLINK variant missingness has markers with F_MISS >= 0.05.")
            retained.append("PLINK variant missingness failures retained.")
        if related_pairs:
            risks.append("PLINK genome relatedness has PI_HAT >= 0.125 pairs.")
            retained.append("PLINK relatedness PI_HAT warnings retained.")
        if metrics["ld_prune_counts"]:
            retained.append("PLINK LD pruning kept/removed counts retained.")
        compressed["summary"] = "PLINK QC memory preserves missingness, relatedness, and LD-pruning signals."

    def _fst_pairs_from_matrix_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, object]]:
        pairs: list[dict[str, object]] = []
        for row in rows:
            if not row:
                continue
            first_key = next(iter(row.keys()))
            row_pop = str(row.get(first_key))
            for column, value in row.items():
                if column == first_key or not _is_number(value) or str(column) == row_pop:
                    continue
                pop1, pop2 = sorted([row_pop, str(column)])
                pairs.append({"pop1": pop1, "pop2": pop2, "fst": float(value)})
        seen = set()
        unique = []
        for pair in sorted(pairs, key=lambda item: item["fst"], reverse=True):
            key = (pair["pop1"], pair["pop2"])
            if key not in seen:
                seen.add(key)
                unique.append(pair)
        return unique


def _is_number(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _summary(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("summary"), dict) and raw["summary"]:
        return raw["summary"]
    return {}


def _memory_for_mode(
    verbose: dict[str, Any],
    mode: str,
    *,
    include_provenance: bool,
    provenance_index: dict[str, Any],
) -> dict[str, Any]:
    if mode == "verbose":
        memory = dict(verbose)
        memory["fact_items"] = _fact_items(verbose["tool_name"], verbose.get("key_facts", []), verbose.get("warnings", []), verbose.get("downstream_dependencies", []))
        if include_provenance:
            memory["provenance_index"] = provenance_index
        return memory

    metrics = verbose.get("retained_metrics", {})
    warnings = _unique(verbose.get("warnings", []))
    deps = _unique(verbose.get("downstream_dependencies", []))
    facts = _compact_facts(verbose["tool_name"], metrics, warnings)
    if mode == "compact":
        compact_warnings = _compact_warnings(warnings)
        compact_deps = _compact_deps(deps)
        fact_items = _fact_items(verbose["tool_name"], facts, [], [])
        memory = {
            "tool_name": verbose["tool_name"],
            "step_name": verbose["step_name"],
            "facts": facts,
            "fact_items": fact_items,
            "retained_metrics": _compact_metrics(metrics),
            "warnings": compact_warnings,
            "assumptions": ["deterministic_local_memory"],
            "downstream_dependencies": compact_deps,
        }
        if include_provenance:
            memory["provenance_ids"] = sorted(provenance_index)
        return memory

    critical = _critical_from_facts(facts, warnings, deps)
    fact_items = _fact_items(verbose["tool_name"], critical["facts"], [], [])
    memory = {
        "t": verbose["tool_name"],
        "s": verbose["step_name"],
        "cf": critical["facts"],
        "fi": fact_items,
        "w": _compact_warnings(critical["warnings"]),
        "d": _compact_deps(critical["deps"]),
    }
    if include_provenance:
        memory["p"] = sorted(provenance_index)
    return memory


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in metrics.items():
        if value in ({}, [], None, ""):
            continue
        compact[key] = value
    return compact


def _compact_warnings(warnings: list[str]) -> list[str]:
    compact: list[str] = []
    for warning in warnings:
        lowered = warning.lower()
        if "ld pruning" in lowered:
            compact.append("LD pruning unknown")
        elif "relatedness" in lowered:
            compact.append("relatedness unknown")
        elif "narrow" in lowered and "k" in lowered:
            compact.append("narrow K")
        elif "seed" in lowered:
            compact.append("seed missing")
        elif "high roh" in lowered:
            compact.append("high ROH")
        elif "selection" in lowered and "proven" in lowered:
            compact.append("selection proven")
        elif "correction" in lowered:
            compact.append("correction not_documented")
        else:
            compact.append(warning[:80])
    return _unique(compact)


def _compact_deps(deps: list[str]) -> list[str]:
    compact: list[str] = []
    for dep in deps:
        lowered = dep.lower()
        if "ld" in lowered:
            compact.append("LD pruning")
        elif "seed" in lowered:
            compact.append("multiple seeds")
        elif "k sweep" in lowered or dep == "K sweep":
            compact.append("K sweep")
        elif "correction" in lowered or "demographic" in lowered:
            compact.append("selection correction")
        elif "roh" in lowered:
            compact.append("ROH context")
        elif "sample" in lowered:
            compact.append("sample-size context")
        elif "population" in lowered:
            compact.append("population metadata")
        else:
            compact.append(dep[:40])
    return _unique(compact)


def _compact_facts(tool_name: str, metrics: dict[str, Any], warnings: list[str]) -> list[str]:
    facts: list[str] = []
    if tool_name == "pca":
        pcs = metrics.get("parsed_pc_columns", [])
        if pcs:
            facts.append(f"PCA PCs {' '.join(map(str, pcs))}")
        variance = metrics.get("variance_explained_summary", {})
        if variance:
            facts.append(f"PCA variance {variance}")
        if metrics.get("ld_pruning_status") == "unknown":
            facts.append("LD pruning unknown")
        if metrics.get("relatedness_removal_status") == "unknown":
            facts.append("relatedness unknown")
        for outlier in metrics.get("outlier_samples", []):
            facts.append(f"outlier {outlier}")
    elif tool_name == "metadata":
        tiny = metrics.get("tiny_population_groups", {})
        if tiny:
            facts.append(f"tiny population fewer than five {tiny}")
        broad = metrics.get("broad_label_warnings", [])
        if broad:
            facts.append(f"broad Indian labels {' '.join(map(str, broad))}")
        if metrics.get("sample_count") is not None:
            facts.append(f"sample count {metrics['sample_count']}")
    elif tool_name == "admixture":
        k_values = metrics.get("k_values_tested", [])
        if k_values:
            facts.append(f"ADMIXTURE K {' '.join(map(str, k_values))}")
        if metrics.get("best_k_by_cv") is not None:
            facts.append(f"best K {metrics['best_k_by_cv']}")
        if metrics.get("q_matrix_shape"):
            facts.append(f"Q matrix shape {metrics['q_matrix_shape']}")
        for sample in metrics.get("high_admixture_samples", [])[:3]:
            facts.append(f"high admixture sample {sample.get('sample_id')} max {sample.get('max_component')}")
        if not metrics.get("seed_count_by_k"):
            facts.append("seed missing")
    elif tool_name == "fst":
        for pair in metrics.get("highest_fst_pairs", [])[:3]:
            facts.append(f"highest FST {pair.get('pop1')} {pair.get('pop2')} {pair.get('fst')}")
        for window in metrics.get("high_fst_windows", [])[:2]:
            facts.append(f"high FST window {window.get('region')} {window.get('fst')}")
    elif tool_name == "roh":
        for pop in metrics.get("high_roh_populations", []):
            facts.append(f"high ROH {pop}")
        for sample in metrics.get("high_roh_samples", [])[:3]:
            facts.append(f"high ROH {sample.get('sample_id')} {sample.get('population')}")
    elif tool_name == "selection_scan":
        for region in metrics.get("top_candidate_regions", [])[:3]:
            if isinstance(region, dict):
                facts.append(f"selection candidate {region.get('region')} {region.get('score')}")
            else:
                facts.append(f"selection candidate {region}")
        if metrics.get("statistic_used"):
            facts.append(f"statistic {metrics['statistic_used']}")
        if metrics.get("correction_status"):
            facts.append(f"correction {metrics['correction_status']}")
    facts.extend(_warning_keywords(warnings))
    return _unique(facts)


def _warning_keywords(warnings: list[str]) -> list[str]:
    facts = []
    for warning in warnings:
        lowered = warning.lower()
        if "narrow" in lowered and "k" in lowered:
            facts.append("narrow K")
        if "selection" in lowered and "proven" in lowered:
            facts.append("selection proven")
        if "correction" in lowered:
            facts.append("correction not_documented")
        if "ld pruning" in lowered:
            facts.append("LD pruning unknown")
        if "high roh" in lowered:
            facts.append("high ROH")
        if "tiny" in lowered:
            facts.append("tiny population")
    return facts


def _critical_from_facts(facts: list[str], warnings: list[str], deps: list[str]) -> dict[str, list[str]]:
    critical_terms = ["selection", "proven", "ld pruning", "tiny", "high roh", "narrow k", "highest fst", "best k", "correction", "seed"]
    critical_facts = [fact for fact in facts if any(term in fact.lower() for term in critical_terms)]
    critical_warnings = [warning for warning in warnings if any(term in warning.lower() for term in critical_terms)]
    critical_deps = [
        dep
        for dep in deps
        if any(term in dep.lower() for term in ["ld", "seed", "k sweep", "correction", "demographic", "roh", "sample"])
    ]
    return {
        "facts": _unique(critical_facts),
        "warnings": _unique(critical_warnings),
        "deps": _unique(critical_deps),
    }


def _critical_facts(memory: dict[str, Any]) -> list[str]:
    if "cf" in memory:
        return list(memory.get("cf", []))
    facts = memory.get("facts", [])
    if isinstance(facts, list):
        return _critical_from_facts(facts, memory.get("warnings", []), memory.get("downstream_dependencies", []))["facts"]
    return _critical_from_facts(memory.get("key_facts", []), memory.get("warnings", []), memory.get("downstream_dependencies", []))["facts"]


def _fact_items(tool_name: str, facts: list[str], warnings: list[str], deps: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen = set()
    for category, values, base_score in [
        ("fact", facts, 0.75),
        ("warning", warnings, 0.85),
        ("dependency", deps, 0.7),
    ]:
        for value in values:
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            is_critical = any(
                term in text.lower()
                for term in ["selection", "proven", "ld pruning", "tiny", "high roh", "narrow k", "highest fst", "best k", "correction", "seed"]
            )
            fact_id = _stable_fact_id(tool_name, text)
            items.append(
                {
                    "fact_id": fact_id,
                    "text": text,
                    "category": category,
                    "importance_score": 0.95 if is_critical else base_score,
                    "is_critical": is_critical,
                    "source_step": tool_name,
                    "provenance_id": compact_provenance_ref(tool_name, category.upper(), text),
                    "downstream_dependency": text if category == "dependency" else None,
                    "retained_reason": "protected critical fact" if is_critical else f"retained {category}",
                }
            )
    return items


def _fact_ids(memory: dict[str, Any]) -> list[str]:
    items = memory.get("fact_items") or memory.get("fi") or []
    return [str(item.get("fact_id")) for item in items if isinstance(item, dict) and item.get("fact_id")]


def _stable_fact_id(tool_name: str, text: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")[:32]
    return f"{tool_name}_{safe}"


def _dropped_facts(verbose: dict[str, Any], mode_memory: dict[str, Any], mode: str) -> list[str]:
    if mode == "verbose":
        return []
    verbose_text = json.dumps(verbose.get("retained_metrics", {}), sort_keys=True)
    compact_text = json.dumps(mode_memory, sort_keys=True)
    dropped = []
    for key in verbose.get("retained_metrics", {}):
        if key not in compact_text and key in verbose_text:
            dropped.append(key)
    return dropped


def _build_provenance_index(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    index: dict[str, Any] = {}
    for item in raw.get("findings", []) or []:
        provenance = item.get("provenance") if isinstance(item, dict) else None
        if provenance and provenance.get("rule_id"):
            index[provenance.get("provenance_id") or provenance["rule_id"]] = provenance
    for row in raw.get("rows", []) or []:
        if isinstance(row, dict):
            provenance = row.get("_provenance")
            if isinstance(provenance, dict):
                pid = str(provenance.get("provenance_id") or row.get("provenance_id") or f"row_{row.get('row_index', 'unknown')}")
                index[pid] = provenance
    return index


def _ensure_fact_provenance_index(memory: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    merged = dict(index)
    items = memory.get("fact_items") or memory.get("fi") or []
    tool_name = memory.get("tool_name") or memory.get("t") or "unknown"
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = item.get("provenance_id")
        if pid and pid not in merged:
            merged[pid] = {
                "source_file": tool_name,
                "source_section": item.get("category", "memory_fact"),
                "parser_name": f"{tool_name}_parser",
                "auditor_name": "DomainMemoryCompressor",
                "field_or_column": None,
                "evidence_value": item.get("text"),
                "rule_id": pid,
                "rule_description": "Compact memory fact provenance reference.",
                "severity": "info" if not item.get("is_critical") else "high",
            }
    return merged


def _serialized_size(value: Any) -> int:
    return serialized_size(value)


def _unique(values: list[Any]) -> list[Any]:
    seen = set()
    unique = []
    for value in values:
        key = json.dumps(value, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique
