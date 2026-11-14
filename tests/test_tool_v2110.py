"""AUTO_MVP v2.11 — innovar, probar, auditar; cuarta vuelta (5/5,
ÚLTIMA del bucle ×5).

- MAX_GAP 256 (antes 16): en la semilla el resultado de la
  conmutación satura en 256 (42 con 16, 48 con 32, 58 con 64, 70
  con 128, 76 con 256 y lo mismo con 512/1024/4096). Tras el
  peephole: 76 más (38 pares), S idéntico, válido, idempotente.
- CONMUTACIÓN EN EL BENCHMARK: quinto operador de la comparación
  (subsume al peephole: en la semilla quita 198 en total).
"""
from __future__ import annotations

from auto_mvp.benchmark import benchmark
from auto_mvp.circuit import SEED_INVSQRT
from auto_mvp.circuits.operators.commuting import _commuting_pass
from auto_mvp.circuits.operators.peephole import clean_file


def test_gap_satura_en_256(tmp_path):
    """La conmutación tras el peephole: 42/58/76 con GAP 16/64/256."""
    p_out = tmp_path / "peephole.kmx"
    clean_file(SEED_INVSQRT, p_out)
    lines = p_out.read_text(encoding="utf-8").splitlines()
    got = {}
    for gap in (16, 64, 256):
        out: list[str] = []
        got[gap] = _commuting_pass(lines, out, max_gap=gap)["removed"]
    assert got == {16: 42, 64: 58, 256: 76}


def test_benchmark_tiene_cinco_operadores(tmp_path):
    """Peephole, commuting, rotation_merge, fanout y sa_windows."""
    rep = benchmark(SEED_INVSQRT, work_dir=tmp_path, run_sa=False)
    assert set(rep["operators"]) == {
        "peephole", "commuting", "rotation_merge", "fanout", "sa_windows"}
    c = rep["operators"]["commuting"]
    assert c["valid"] is True
    assert c["delta_S"] == 0
    # 122 adyacentes + 76 por conmutación (GAP 256) = 198. En la
    # pasada sola, un par que tras el peephole es adyacente se
    # cuenta como conmutación (39 en vez de 38): el total es el
    # mismo, cambia el reparto por el orden de cancelación.
    assert c["stats"]["removed"] == 198
    assert c["stats"]["pairs_commuting"] == 39
