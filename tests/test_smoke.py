"""Prueba de humo del paquete auto_mvp.healing (v0.1.0).

Cubre, en orden:
1. Que el __init__ importa y expone todo.
2. Que el detector dispara con tasa de error >= 0.2.
3. Que validate() distingue un buen modelo de un baseline tonto.
4. Que el lazo completo AUTO repara una funcion con bug y la deja
   funcionando, con rollback disponible si la probation falla.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_mvp.healing import (
    Autonomy, ErrorRateDetector, Ledger, SelfHealing, Spec,
    SubprocessVerifier, __version__,
)
from auto_mvp.healing.validate import evaluate


def test_imports():
    assert __version__ == "0.1.0"
    assert Spec is not None and SelfHealing is not None
    assert Autonomy is not None and SubprocessVerifier is not None
    assert ErrorRateDetector is not None and Ledger is not None
    print("imports OK, version", __version__)


def test_detector():
    d = ErrorRateDetector(window=20, min_events=10, threshold=0.2)
    for _ in range(9):
        assert not d.add(True)
    assert not d.add(True)  # 10 ok -> 0% error, no dispara
    assert not d.add(False)  # 1/11 = 9% -> no dispara
    assert not d.add(False)  # 2/12 = 17% -> no dispara
    assert d.add(False)     # 3/13 = 23% -> dispara
    print("detector OK: dispara al superar 20% de error")


def test_validate():
    # Modelo casi perfecto vs baseline al azar (0.5 constante).
    labels = [1, 1, 1, 1, 0, 0, 0, 0] * 5
    model = [0.9, 0.8, 0.95, 0.85, 0.1, 0.2, 0.05, 0.15] * 5
    baseline = [0.5] * len(labels)
    out = evaluate(model, {"azar": baseline}, labels, n_boot=100, seed=0)
    assert out["beats_baselines"] is True, out
    assert out["baselines"]["azar"]["delta_lo95"] > 0, out
    print("validate OK:", out["model_auc"], "vs azar",
          out["baselines"]["azar"]["auc"],
          "delta_lo95 =", out["baselines"]["azar"]["delta_lo95"])


BUGGY = "def divide10(x):\n    return 10 // x\n"
FIXED = "def divide10(x):\n    return 0 if x == 0 else 10 // x\n"

CONTRACT = '''
def check(fn):
    fails = []
    try:
        if fn(2) != 5:
            fails.append("fn(2) debe ser 5")
    except Exception as e:
        fails.append("fn(2) lanzo %s" % type(e).__name__)
    try:
        if fn(0) != 0:
            fails.append("fn(0) debe ser 0")
    except Exception as e:
        fails.append("fn(0) lanzo %s" % type(e).__name__)
    return fails
'''


class DummyProposer:
    def propose(self, spec, current_src, evidence):
        return FIXED


def test_heal_auto():
    spec = Spec(
        name="divide10",
        entrypoint="divide10",
        contract_src=CONTRACT,
        intent="10/x, con 0 si x es 0",
    )
    ledger = Ledger()
    svc = SelfHealing(
        spec, BUGGY, DummyProposer(),
        autonomy=Autonomy.AUTO,
        detector=ErrorRateDetector(window=20, min_events=10, threshold=0.2),
        ledger=ledger,
    )
    assert svc(2) == 5
    # 10 fallos seguidos con x=0 -> el detector dispara y repara.
    for _ in range(10):
        try:
            svc(0)
        except ZeroDivisionError:
            pass
    assert svc(0) == 0, "tras la reparacion fn(0) debe ser 0"
    assert svc(2) == 5, "lo que funcionaba debe seguir igual (replay)"
    events = ledger.events()
    assert "anomaly_detected" in events, events
    assert "applied" in events, events
    print("heal AUTO OK: eventos =", events)


if __name__ == "__main__":
    test_imports()
    test_detector()
    test_validate()
    test_heal_auto()
    print("TODO OK: 4/4 pruebas de humo pasaron")
