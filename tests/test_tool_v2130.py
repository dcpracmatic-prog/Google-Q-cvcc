"""AUTO_MVP v2.13 — el salto de línea que faltaba (pedido de Arturo).

- rotation_merge y peephole re-emitían las Z_POW SIN salto de línea
  en la ruta en memoria: la línea se pegaba a la siguiente y el .kmx
  ya no cargaba ("Invalid decimal angle"). Hallazgo del Notebook de
  mapeo en Kaggle v15/seed2 (2026-11-13): el verificador devolvía
  valid=False por un archivo corrupto, no por un circuito malo.
  El arreglo: el salto de línea se hereda de la entrada (si las
  líneas traen "\\n", las re-emitidas también). El contrato sin
  saltos no cambia (los juguetes y el streaming dan lo mismo).
- El Notebook de mapeo de datasets (Kaggle) entra al repo en
  kaggle-notebooks/google-q-cvcc-mapeo-datasets/.
"""
from __future__ import annotations

from pathlib import Path

from auto_mvp.circuit import SEED_INVSQRT, fast_verify_invsqrt
from auto_mvp.circuits.operators.peephole import peephole_clean
from auto_mvp.circuits.operators.rotation_merge import rotation_merge

SEED_S = 100585.37325984969


def _seed_lines() -> list[str]:
    return Path(SEED_INVSQRT).read_text().splitlines(keepends=True)


def test_rotation_merge_memoria_con_saltos_no_corrompe(tmp_path: Path):
    """La semilla en memoria, con saltos: el .kmx unido carga y el S es idéntico.

    Es el fallo v15/seed2 del Notebook de Kaggle: sin el arreglo,
    la Z_POW re-emitida se pegaba a la siguiente línea y el
    verificador decía "Invalid decimal angle".
    """
    lineas = _seed_lines()
    assert all(l.endswith("\n") for l in lineas)
    out, stats = rotation_merge(list(lineas))
    assert all(l.endswith("\n") for l in out)
    assert stats["merged"] == 0 and stats["removed"] == 0
    tmp = tmp_path / "rm.kmx"
    tmp.write_text("".join(out))
    m = fast_verify_invsqrt(str(tmp), max_x=1024)
    assert m["valid"], m.get("reason")
    assert m["S"] == SEED_S


def test_peephole_fusion_memoria_con_saltos_no_corrompe(tmp_path: Path):
    """El peephole tenía el mismo defecto en su fusión de Z_POW."""
    toy = ["Z_POW q2 0.25\n", "Z_POW q2 0.75\n", "X q0\n", "X q0\n"]
    out, stats = peephole_clean(toy)
    assert stats["zpow_fused"] == 1
    assert all(l.endswith("\n") for l in out)
    assert out == ["Z_POW q2 1.0\n"]
    # Y en la semilla: válido, S idéntico, 122 Clifford menos.
    out2, stats2 = peephole_clean(_seed_lines())
    assert all(l.endswith("\n") for l in out2)
    assert stats2["removed"] == 122
    tmp = tmp_path / "ph.kmx"
    tmp.write_text("".join(out2))
    m = fast_verify_invsqrt(str(tmp), max_x=1024)
    assert m["valid"], m.get("reason")
    assert m["S"] == SEED_S


def test_sin_saltos_contrato_sin_cambio():
    """Sin saltos en la entrada, la salida tampoco los lleva (contrato actual)."""
    out, stats = rotation_merge(["Z_POW q0 0.25", "X q0", "Z_POW q0 0.25"])
    assert out == ["X q0"]
    assert stats == {"merged": 1, "removed": 1, "zpow_in": 2, "zpow_out": 0}
    out2, stats2 = peephole_clean(["Z_POW q2 0.25", "Z_POW q2 0.75"])
    assert out2 == ["Z_POW q2 1.0"]
    assert stats2["zpow_fused"] == 1
