"""Tests de dfthc_retrain (v2.17.20): forward, gradientes y ángulos.

Caso sintético pequeño (N=4 orbitales, R=1, B=2, C=2) para que el test
sea rápido y autocontenido (sin el ref_cache.npz de 133 MB ni el kit).
Verifica:
- forward reproduce error_2 por cálculo directo (matriz H completa).
- los gradientes analíticos (barrera y lambda_eff) coinciden con
  diferencias finitas.
- build_angle_words normaliza a norma 1 en float64 (corrección C-1) y
  vector_to_angles invierte la reconstrucción del árbol.
- project_W sube E_gap al objetivo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_mvp.circuits.generators.dfthc_retrain import (
    Data,
    balanced_tree,
    build_angle_words,
    forward,
    loss_and_grad_barrier,
    loss_and_grad_lameff,
    pack,
    project_W,
    vector_to_angles,
)


def make_small_data(seed=0):
    rng = np.random.default_rng(seed)
    N = 4
    oei = rng.standard_normal((N, N))
    oei = 0.5 * (oei + oei.T)
    tei = rng.standard_normal((N, N, N, N))
    # simetrizar en los pares (p,q) y (s,t) y en el intercambio de pares
    tei = 0.5 * (tei + np.swapaxes(tei, 0, 1))
    tei = 0.5 * (tei + np.swapaxes(tei, 2, 3))
    tei = 0.5 * (tei + np.swapaxes(np.swapaxes(tei, 0, 2), 1, 3))
    ref = {"oei": oei, "tei": tei, "ecore": -22140.0, "electrons": 4, "orbitals": N}
    S = np.zeros((N, N))
    beta_1 = 0.0
    return Data(ref, S, beta_1, R=1, B=2, C=2)


def make_small_point(seed=1):
    rng = np.random.default_rng(seed)
    Y = rng.standard_normal((1, 2, 4))
    w = rng.standard_normal((1, 2, 2)) * 0.3
    Wnat = rng.standard_normal((1, 2)) * 0.1
    return Y, w, Wnat


def test_forward_error2_directo():
    """error_2 del forward coincide con el cálculo directo de H."""
    data = make_small_data()
    Y, w, Wnat = make_small_point()
    fw = forward(Y, w, Wnat, data)
    # cálculo directo: H = sum_rc X_rc ⊗ X_rc (con X simétrica)
    X = fw["X"]
    N = data.N
    H = np.zeros((N * N, N * N))
    for c in range(data.C):
        x = X[0, c].reshape(-1)
        H += np.outer(x, x)
    # objetivo M (la matriz de pares del Data)
    err_direct = float(np.linalg.norm(H - data.M))
    assert fw["error_2"] == pytest.approx(err_direct, rel=1e-9, abs=1e-9)


def test_grad_barrier_finite_diff():
    """Gradiente de la barrera coincide con diferencias finitas."""
    data = make_small_data()
    Y, w, Wnat = make_small_point()
    vec = pack(Y, w, Wnat)
    mu = 0.3
    fw0 = forward(Y, w, Wnat, data)
    # punto factible con margen (la barrera exige error_2 < target2 y
    # E_gap > floor_gap; el caso sintético no está en el límite real)
    target2 = fw0["error_2"] + 1.0
    floor_gap = fw0["E_gap"] - 1.0
    loss, grad, fw = loss_and_grad_barrier(vec, data, mu, target2=target2, floor_gap=floor_gap)
    assert fw["error_2"] < target2
    assert fw["E_gap"] > floor_gap
    h = 1e-6
    rng = np.random.default_rng(3)
    for c in rng.choice(len(vec), size=5, replace=False):
        vp = vec.copy(); vp[c] += h
        vm = vec.copy(); vm[c] -= h
        lp, _, _ = loss_and_grad_barrier(vp, data, mu, target2=target2, floor_gap=floor_gap)
        lm, _, _ = loss_and_grad_barrier(vm, data, mu, target2=target2, floor_gap=floor_gap)
        num = (lp - lm) / (2 * h)
        assert grad[c] == pytest.approx(num, rel=2e-2, abs=2e-2)


def test_grad_lameff_finite_diff():
    """Gradiente de lambda_eff coincide con diferencias finitas."""
    data = make_small_data()
    Y, w, Wnat = make_small_point()
    vec = pack(Y, w, Wnat)
    mu = 0.3
    fw0 = forward(Y, w, Wnat, data)
    target2 = fw0["error_2"] + 1.0
    floor_gap = fw0["E_gap"] - 1.0
    loss, grad, fw = loss_and_grad_lameff(vec, data, mu, target2=target2, floor_gap=floor_gap)
    assert fw["error_2"] < target2
    assert fw["E_gap"] > floor_gap
    assert np.isfinite(fw["lambda_eff"])
    h = 1e-6
    rng = np.random.default_rng(4)
    for c in rng.choice(len(vec), size=5, replace=False):
        vp = vec.copy(); vp[c] += h
        vm = vec.copy(); vm[c] -= h
        lp, _, _ = loss_and_grad_lameff(vp, data, mu, target2=target2, floor_gap=floor_gap)
        lm, _, _ = loss_and_grad_lameff(vm, data, mu, target2=target2, floor_gap=floor_gap)
        num = (lp - lm) / (2 * h)
        assert grad[c] == pytest.approx(num, rel=2e-2, abs=2e-2)


def test_angle_words_c1_norma_uno():
    """C-1: build_angle_words normaliza a norma 1 en float64 y el
    round-trip vector->ángulos->vector reproduce el vector unitario."""
    data = make_small_data()
    Y, w, Wnat = make_small_point()
    words, tree_edges, fw = build_angle_words(Y, w, Wnat, data, brot=8)
    # las palabras son enteros en [0, 256)
    assert words.shape == (data.N + data.R * data.B, data.N - 1)
    assert words.min() >= 0 and words.max() < 256
    # round-trip: reconstruir el vector desde los ángulos y comparar
    # (reconstrucción directa del árbol, inversa de vector_to_angles)
    n = data.N
    edges = tree_edges
    for v in [fw["U"][0, 0], fw["evecs"][:, 0]]:
        v = v / np.linalg.norm(v)
        thetas = vector_to_angles(v, edges)
        # reconstruir: recorrer ejes en orden directo acumulando rotaciones
        x = np.zeros(n)
        x[0] = 1.0
        for k in range(len(edges)):
            p, c = int(edges[k, 0]), int(edges[k, 1])
            th = thetas[k] * np.pi
            a, b = x[p], x[c]
            x[p] = a * np.cos(th) - b * np.sin(th)
            x[c] = a * np.sin(th) + b * np.cos(th)
        # el vector reconstruido debe ser ±v (el signo global es libre
        # porque la reconstrucción del verificador usa la misma convención)
        assert abs(abs(float(x @ v)) - 1.0) < 1e-9


def test_project_W_sube_egap():
    """project_W escala W para llevar E_gap al objetivo."""
    data = make_small_data()
    Y, w, Wnat = make_small_point()
    fw0 = forward(Y, w, Wnat, data)
    target = fw0["E_gap"] + 0.5
    W1, fw1, alpha = project_W(Y, w, Wnat, data, target_gap=target)
    assert alpha > 1.0
    assert fw1["E_gap"] == pytest.approx(target, rel=1e-3, abs=1e-3)


def test_balanced_tree_estructura():
    edges = balanced_tree(4)
    assert edges.shape == (3, 2)
    assert set(map(tuple, edges.tolist())) == {(0, 1), (0, 2), (1, 3)}
