"""AUTO_MVP — núcleo autónomo de optimización para VQCC (desde v0.3.0).

Construye sobre el corrector v0.2.1-vqcc (auto_mvp.vqcc) y el paquete
genérico de auto-reparación v0.1.0 (auto_mvp.healing), y añade lo
concreto de la especificación AUTO_MVP v0.0.1 de Arturo:

- integrity: filtro de integridad obligatorio (sigma, C/B, dreg,
  alpha, temporales) + guardia que envuelve la construcción.
- cvv: bitácora con cadena de hashes (tamper-evident, no firma).
- checkpoint: checkpoint atómico inmediato de cada mejor verificado.
- goal: meta porcentual con regla de paro y presupuesto adaptativo.
- proxy: evaluación proxy en el espacio de metadatos (prefiltro
  antes de construir; el validador como filtro de entrada).
- mvp: orquestador del ciclo de 5 fases.

El mérito de aceptación es siempre el S OFICIAL. La suma ponderada
de la spec solo existe como proxy_merit (ranking, nunca aceptación).
"""
from .cache import VerificationCache, verify_with_cache
from .checkpoint import Checkpoint
from .cvv import CvvChain, CvvRecord, GENESIS_PREV
from .dataset import WorkingDataset, export_candidate, render_module
from .gf212 import DEG as GF212_DEG
from .gf212 import MOD as GF212_MOD
from .gf212 import monic as gf212_monic
from .goal import Goal, GoalState, GoalTracker, target_S_for_meta_mvp
from .integrity import (CircuitConstructionGuard, IntegrityEvidence,
                        IntegrityFilter, IntegrityViolation, canonical_hash,
                        monic_sigma, sigma_scale_factor)
from . import kaggle_init
from .kaggle_init import REPO_URL, detect_environment
from .maxcut import (Partition, greedy_mis, morph as maxcut_morph,
                     exact as maxcut_exact, make_graph as maxcut_graph,
                     mwis_gain, partition_conflict_graph,
                     partition_then_select)
from .json_directive import (ALL_METHODS, METHODS, STEPS, Directive,
                             load_plan, parse_directive)
from .morph_tunnel import (DQI_R, RULES, ReplacementRule, TunnelMove,
                           TunnelResult, tunnel)
from .mvp import AutoMvp, MvpResult
from .mwis import (classify_states, exact_mwis, greedy_mwis,
                   is_independent, one_to_two_improve, solve_mwis,
                   total_weight)
from .numeric_lab import (NUMERIC_WARNING, fail_closed_gate,
                          float_pass_table, numeric_lab)
from .observer import (AdaptiveObservabilityMembrane, Observer,
                       observe_trials)
from .accel import available as accel_available
from .accel import dijkstra as accel_dijkstra
from .accel import spmm_csr_dense as accel_spmm_csr_dense
from .accel import swar_friction as accel_swar_friction
from .combiner import (BestLedger, combine, export_audit_zip,
                       export_base_zip)
from .mutator import Mutation, Mutator
from .notebook import export_winner_notebook
from .operations import (OPERATIONS, apply_morph_tunnel, check_integrity,
                         combine_best, decode_json_config,
                         evaluate_candidate, export_module, export_notebook,
                         mutate, promotion_gate, run_orchestrator,
                         run_serial, validate_submission)
from .serial import compensation_record, run_serial as run_serial_tasks
from .packaging import (EXPECTED_NPZ_KEYS, build_submission_zip,
                        submission_ready, validate_submission_dir,
                        validate_submission_zip)
from .orchestrator import AdaptiveOrchestrator, OrchestratorResult
from .pipeline import (ArtifactStore, Pipeline, PromotionGate,
                       artifact_name, promotion_gm, pure_advantage,
                       required_dqi_ratio)
from .seeds import DEFAULT_SEEDS, default_seeds
from .proxy import (CandidateMeta, MetadataProxy, ProxyVerdict,
                    calibrate_proxy, estimate_S, proxy_merit)
from .qualtran_bridge import (QUALTRAN_VERSION, Block, CallGraph,
                              from_qualtran_bloq)
from .step_plan import DEFAULT_STEPS, StepPlan

__version__ = "2.13.0"

__all__ = [
    "Checkpoint",
    "CvvChain", "CvvRecord", "GENESIS_PREV",
    "VerificationCache", "verify_with_cache",
    "GF212_MOD", "GF212_DEG", "gf212_monic",
    "Goal", "GoalState", "GoalTracker", "target_S_for_meta_mvp",
    "CircuitConstructionGuard", "IntegrityEvidence",
    "IntegrityFilter", "IntegrityViolation", "canonical_hash",
    "monic_sigma", "sigma_scale_factor",
    "REPO_URL", "detect_environment", "kaggle_init",
    "AutoMvp", "MvpResult",
    "ArtifactStore", "Pipeline", "PromotionGate",
    "artifact_name", "promotion_gm", "pure_advantage", "required_dqi_ratio",
    "Partition", "greedy_mis", "maxcut_morph", "maxcut_exact",
    "maxcut_graph", "mwis_gain", "partition_conflict_graph",
    "partition_then_select",
    "classify_states", "exact_mwis", "greedy_mwis", "is_independent",
    "one_to_two_improve", "solve_mwis", "total_weight",
    "NUMERIC_WARNING", "fail_closed_gate", "float_pass_table", "numeric_lab",
    "AdaptiveObservabilityMembrane", "Observer", "observe_trials",
    "QUALTRAN_VERSION", "Block", "CallGraph", "from_qualtran_bloq",
    "DQI_R", "RULES", "ReplacementRule", "TunnelMove", "TunnelResult",
    "tunnel",
    "ALL_METHODS", "METHODS", "STEPS", "Directive", "load_plan",
    "parse_directive",
    "DEFAULT_STEPS", "StepPlan",
    "AdaptiveOrchestrator", "OrchestratorResult",
    "OPERATIONS", "apply_morph_tunnel", "check_integrity",
    "combine_best", "decode_json_config", "evaluate_candidate",
    "export_module", "export_notebook", "mutate", "promotion_gate",
    "run_orchestrator", "run_serial", "validate_submission",
    "BestLedger", "combine", "export_audit_zip",
    "Mutation", "Mutator",
    "run_serial_tasks", "compensation_record",
    "export_winner_notebook",
    "accel_available", "accel_dijkstra", "accel_spmm_csr_dense",
    "accel_swar_friction",
    "WorkingDataset", "export_candidate", "render_module",
    "EXPECTED_NPZ_KEYS", "build_submission_zip", "submission_ready",
    "validate_submission_dir", "validate_submission_zip",
    "CandidateMeta", "MetadataProxy", "ProxyVerdict",
    "calibrate_proxy", "estimate_S", "proxy_merit",
    "__version__",
    "run_auto", "DEFAULT_SEEDS", "default_seeds",
    "BruteForce", "export_base_zip", "limits_ok",
    "fast_verify_invsqrt", "static_count", "propose_sa_windows",
    "run_circuit_auto",
    "fast_verify_dqi", "fast_verify_dfthcsos",
    "ensure_dfthcsos_reference_data",
    "LLMError", "complete", "complete_json",
    "new_seed", "validate_seed", "save_seed", "load_seed", "list_seeds",
    "run_llm_auto",
    "rank_deltas", "estimate_delta", "calibrate_margin",
    "dqi_estimate_variant", "dqi_sweep",
    "peephole_clean", "clean_peephole_file",
    "eea_trace", "dialog_bezout", "playback",
    "rotation_merge", "merge_rotations_file",
    "build_report", "render_report",
    "benchmark", "render_benchmark",
]


def __getattr__(name: str):
    """Carga perezosa de auto/seeds: así `python -m auto_mvp.auto`
    no choca con el módulo ya importado por el __init__."""
    if name == "run_auto":
        from .auto import run_auto
        return run_auto
    if name in ("DEFAULT_SEEDS", "default_seeds"):
        from .seeds import DEFAULT_SEEDS, default_seeds
        return DEFAULT_SEEDS if name == "DEFAULT_SEEDS" else default_seeds
    if name == "BruteForce":
        from .brute import BruteForce
        return BruteForce
    if name == "limits_ok":
        from .brute import limits_ok
        return limits_ok
    if name in ("fast_verify_invsqrt", "static_count", "propose_sa_windows",
                "fast_verify_dqi", "fast_verify_dfthcsos",
                "ensure_dfthcsos_reference_data"):
        from .circuit import (ensure_dfthcsos_reference_data,
                              fast_verify_dfthcsos, fast_verify_dqi,
                              fast_verify_invsqrt, propose_sa_windows,
                              static_count)
        return {"fast_verify_invsqrt": fast_verify_invsqrt,
                "static_count": static_count,
                "propose_sa_windows": propose_sa_windows,
                "fast_verify_dqi": fast_verify_dqi,
                "fast_verify_dfthcsos": fast_verify_dfthcsos,
                "ensure_dfthcsos_reference_data":
                    ensure_dfthcsos_reference_data}[name]
    if name == "run_circuit_auto":
        from .circuit_auto import run_circuit_auto
        return run_circuit_auto
    if name in ("LLMError", "complete", "complete_json"):
        from .llm import LLMError, complete, complete_json
        return {"LLMError": LLMError, "complete": complete,
                "complete_json": complete_json}[name]
    if name in ("new_seed", "validate_seed", "save_seed", "load_seed",
                "list_seeds"):
        from .seed import (list_seeds, load_seed, new_seed, save_seed,
                           validate_seed)
        return {"new_seed": new_seed, "validate_seed": validate_seed,
                "save_seed": save_seed, "load_seed": load_seed,
                "list_seeds": list_seeds}[name]
    if name == "run_llm_auto":
        from .llm_auto import run_llm_auto
        return run_llm_auto
    if name in ("rank_deltas", "estimate_delta", "calibrate_margin"):
        from .prefilter import calibrate_margin, estimate_delta, rank_deltas
        return {"rank_deltas": rank_deltas,
                "estimate_delta": estimate_delta,
                "calibrate_margin": calibrate_margin}[name]
    if name in ("dqi_estimate_variant", "dqi_sweep"):
        from .circuits.cost_models.dqi_cost import estimate_variant, sweep
        return {"dqi_estimate_variant": estimate_variant,
                "dqi_sweep": sweep}[name]
    if name in ("peephole_clean", "clean_peephole_file"):
        from .circuits.operators.peephole import clean_file, peephole_clean
        return {"peephole_clean": peephole_clean,
                "clean_peephole_file": clean_file}[name]
    if name in ("eea_trace", "dialog_bezout", "playback"):
        from .circuits.dialog import dialog_bezout, eea_trace, playback
        return {"eea_trace": eea_trace, "dialog_bezout": dialog_bezout,
                "playback": playback}[name]
    if name in ("rotation_merge", "merge_rotations_file"):
        from .circuits.operators.rotation_merge import (
            merge_file, rotation_merge)
        return {"rotation_merge": rotation_merge,
                "merge_rotations_file": merge_file}[name]
    if name in ("build_report", "render_report"):
        from .report import build_report, render_markdown
        return {"build_report": build_report,
                "render_report": render_markdown}[name]
    if name in ("benchmark", "render_benchmark"):
        from .benchmark import benchmark, render_markdown
        return {"benchmark": benchmark,
                "render_benchmark": render_markdown}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
