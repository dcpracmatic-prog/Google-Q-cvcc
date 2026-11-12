"""AUTO_MVP v2.2 — modelo de lenguaje gratis + solo salen semillas.

El modelo es el estratega (propone K y seed como JSON chico); los
operadores verificados construyen; el verificador oficial decide.
El Notebook no construye .kmx: el circuito vive solo en temporal y
se borra; en runs/seeds/ quedan solo JSONs de kilobytes.

Los tests del cliente LLM no tocan la red: monkeypatchean urlopen.
Los del corredor usan un cliente falso (sin llave real).
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from auto_mvp.circuit import SEED_INVSQRT, propose_sa_windows
from auto_mvp.llm import LLMError, complete, complete_json
from auto_mvp.llm_auto import run_llm_auto
from auto_mvp.seed import (list_seeds, load_seed, new_seed, save_seed,
                           seed_id, validate_seed)


def test_seed_roundtrip_and_tamper(tmp_path):
    s = new_seed("invsqrt", 100568.5, 62, 1325.48,
                 {"base": "invsqrt_pub"}, notes="base")
    assert s["id"] == seed_id(s)
    p = save_seed(s, tmp_path)
    assert p.suffix == ".json"
    assert load_seed(p) == s
    bad = dict(s)
    bad["S"] = 1.0
    with pytest.raises(ValueError):
        validate_seed(bad)
    with pytest.raises(ValueError):
        new_seed("invsqrt", 1.0, 62, 1.0, {})
    with pytest.raises(ValueError):
        new_seed("otro", 1.0, 62, 1.0, {"base": "x"})


def test_llm_client_no_key(monkeypatch):
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "LLM_API_KEY",
                "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(LLMError) as exc:
        complete("hola")
    assert exc.value.no_key is True


def _fake_urlopen(body: dict, status: int = 200):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(body).encode("utf-8")
    return lambda req, timeout=None: Resp()


def test_llm_client_429(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
    monkeypatch.setattr("urllib.request.urlopen", boom)
    monkeypatch.setenv("GEMINI_API_KEY", "falsa")
    with pytest.raises(LLMError) as exc:
        complete("hola", provider="gemini")
    assert exc.value.rate_limited is True


def test_complete_json_extracts_fenced(monkeypatch):
    body = {"choices": [{"message": {"content":
        'Claro, aquí va:\n```json\n{"K": 6, "seed": 123, '
        '"reason": "probar K=6"}\n```'}}]}
    monkeypatch.setattr("urllib.request.urlopen",
                        _fake_urlopen(body))
    monkeypatch.setenv("GEMINI_API_KEY", "falsa")
    out = complete_json("propón", provider="gemini")
    assert out == {"K": 6, "seed": 123, "reason": "probar K=6"}


def _fake_llm(_prompt: str) -> dict:
    return {"K": 5, "seed": 99, "reason": "falso: probar K=5"}


def test_llm_auto_fake_llm_one_proposal(tmp_path):
    res = run_llm_auto(90000, runs_dir=tmp_path, max_proposals=1,
                       sa_budget_s=5, llm_client=_fake_llm, seed=7)
    assert res["proposals"] == 1
    assert res["llm_calls"] == 1 and res["llm_fallbacks"] == 0
    assert res["reached"] is False
    # Solo salen semillas: JSONs, ningún .kmx en runs/.
    kmx = list(Path(tmp_path).rglob("*.kmx"))
    assert kmx == []
    seeds = list_seeds(tmp_path, "invsqrt")
    assert len(seeds) >= 1
    assert seeds[0]["task"] == "invsqrt"
    assert (tmp_path / "seed_ledger.json").is_file()


def test_llm_auto_no_key_falls_back(tmp_path):
    def _no_key(_prompt: str) -> dict:
        raise LLMError("sin llave", no_key=True)
    res = run_llm_auto(90000, runs_dir=tmp_path, max_proposals=1,
                       sa_budget_s=5, llm_client=_no_key, seed=7)
    assert res["proposals"] == 1
    assert res["llm_fallbacks"] == 1 and res["llm_calls"] == 0
    assert list(Path(tmp_path).rglob("*.kmx")) == []


def test_llm_auto_rejects_other_tasks(tmp_path):
    with pytest.raises(ValueError):
        run_llm_auto(90000, task="dqi", runs_dir=tmp_path,
                     max_proposals=1)


def test_sa_windows_deterministic(tmp_path):
    # La semilla se reconstruye re-corriendo el operador con los
    # mismos (K, seed): dos corridas deben dar lo mismo.
    out1 = tmp_path / "a.kmx"
    log1 = tmp_path / "a.json"
    out2 = tmp_path / "b.kmx"
    log2 = tmp_path / "b.json"
    r1 = propose_sa_windows(SEED_INVSQRT, out1, log1, K=5,
                            budget_s=5, seed=7)
    r2 = propose_sa_windows(SEED_INVSQRT, out2, log2, K=5,
                            budget_s=5, seed=7)
    assert r1["ok"] and r2["ok"]
    assert r1["gain"] == r2["gain"]
    assert out1.read_bytes() == out2.read_bytes()
