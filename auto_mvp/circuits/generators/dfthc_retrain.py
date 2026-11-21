"""Reentrenamiento DFTHC (química) desde cero — v2.17.20.

Entrenador de la factorización (U, W) que minimiza el score DFTHC
(S = lambda_eff * T * Q) con gradientes analíticos verificados.

Matemática EXACTA del verificador oficial (scoreinfra/dfthc_math.py):
  lambda_h2 = 1/4 * sum_(rho,c) (||w^(rho,c)||_1 + |w_B^(rho,c)|)^2
  error_2   = ||sum X⊗X - (S⊗I + I⊗S)/2 - tei||_F
  E_gap     = E_upper - E_SOS,  E_SOS = ecore - eta*beta_1
              - (lambda_h1 - tr(h1_prime)) - 0.5*sum(Wnat^2)
  lambda_eff = sqrt(E_gap * (2*Lambda - E_gap))

Variables: Y (R,B,N) -> U normalizado por fila; w (R,B,C); Wnat (R,C).
Los gradientes analíticos están verificados por diferencias finitas
(peor error relativo ~1e-4 en test completo; ~4e-3 en coordenadas de
gradiente casi nulo, artefacto de la diferencia finita).

Resultado medido (2026-11-20, sandbox, 5 variantes probadas):
  El portfolio (Lambda=283.144, lambda_eff=46.9216, S=294,642,170) es un
  óptimo local fuerte. Ninguna variante local lo bate:
  - v1 penalización cuadrática (L-BFGS): diverge (Lambda a 138k).
  - v2 W congelado + penalización débil: error_2 a 0.048 (FAIL).
  - v3 barrera log en error_2 y E_gap, objetivo Lambda: E_gap a 4.25,
    lambda_eff a 48.91, S=307M (peor).
  - v4 barrera solo error_2 + proyección de W a E_gap=piso entre rondas:
    Lambda a 282.82 pero la proyección lo devuelve a 283.50, S=294.9M.
  - v5 objetivo lambda_eff directo + barreras, todo junto:
    lambda_eff a 47.07, S=295.6M (peor).
  Diagnóstico: E_gap(alpha) tiene forma de U con mínimo en alpha~1.0 y
  (lambda_h1 - tr) es 2*sum|autovalores negativos de h1_prime|, tan
  sensible que un 1% en W mueve E_gap ~13 Ha. La ineficiencia 20x del
  diagnóstico (sum||X||^2_F=53.18 -> lambda_h2>=13.29 vs 270 real)
  exige un cambio GLOBAL de representación, no optimización local.
  El spectral_init (cold start) tampoco es viable: Lambda=1942, E_gap=957.

Corrección C-1 (2026-11-20): la U se guarda en float32 y su norma deja
de ser 1 (desvío ~1e-7); reconstruct_u_vectors conserva norma 1 y no
puede reproducirla. build_angle_words normaliza los vectores a norma 1
en float64 antes de cuantizar (err 2.85e-08 -> ~1e-16).

Uso: retrain() corre el entrenador (v5 por defecto) y devuelve la
factorización y las métricas. La medición oficial es con el verificador
DFTHC en Kaggle; este módulo solo entrena.
"""
from __future__ import annotations

import numpy as np

E_GAP_FLOOR = 3.914898
E_UPPER = -22140.27335


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

def load_cache(path):
    """ref_cache.npz con oei/tei/ecore/electrons/orbitals (datos oficiales)."""
    d = np.load(path)
    return {
        "oei": np.asarray(d["oei"], dtype=np.float64),
        "tei": np.asarray(d["tei"], dtype=np.float64),
        "ecore": float(d["ecore"]),
        "electrons": int(d["electrons"]),
        "orbitals": int(d["orbitals"]),
    }


def load_fixed_shifts(verifier_dir):
    """S y beta_1 FIJOS del baseline (el verificador ignora los enviados).

    verifier_dir: directorio con scoreinfra/ del kit de competencia.
    """
    import sys
    sys.path.insert(0, verifier_dir)
    from scoreinfra import dfthc_math
    from scoreinfra.reference import load_fixed_shifts as _lfs
    sh = _lfs()
    n = 76
    S = dfthc_math.symmetric_from_lower(sh["Hsym_lower"], n).astype(np.float64)
    beta_1 = float(sh["H1_I"]) - 0.5 * float(np.trace(S))
    return S, beta_1


def build_target_pair_matrix(tei, S):
    """M (N^2 x N^2): tei + ajustes de shift, exactamente como el verificador.

    M[(p,q),(s,t)] = tei[p,q,s,t] + 0.5*S[p,q]*delta_{s,t} + 0.5*delta_{p,q}*S[s,t]
    Todo in-place: sin temporales de 5776x5776 (la RAM es compartida).
    """
    n = tei.shape[0]
    M = np.asarray(tei, dtype=np.float64).reshape(n * n, n * n).copy()
    M += M.T
    M *= 0.5
    M4 = M.reshape(n, n, n, n)
    ar = np.arange(n)
    M4[:, :, ar, ar] += 0.5 * np.asarray(S, dtype=np.float64)[:, :, None]
    M4[ar, ar, :, :] += 0.5 * np.asarray(S, dtype=np.float64)[None, :, :]
    return M


def build_h1_thc(oei, tei):
    """h1_thc = oei - 0.5 * sum_r tei[p,r,r,q]."""
    return np.asarray(oei) - 0.5 * np.einsum("prrq->pq", tei)


class Data:
    def __init__(self, ref, S, beta_1, R=8, B=143, C=44):
        self.N = int(ref["orbitals"])
        self.eta = int(ref["electrons"])
        self.ecore = float(ref["ecore"])
        self.h1_thc = build_h1_thc(ref["oei"], ref["tei"])
        self.S = np.asarray(S, dtype=np.float64)
        self.beta_1 = float(beta_1)
        self.M = build_target_pair_matrix(ref["tei"], self.S)
        self.M_fro2 = float(np.sum(self.M * self.M))
        self.R, self.B, self.C = int(R), int(B), int(C)
        self.K = self.R * self.C
        self.N2 = self.N * self.N


def normalize_rows(Y):
    nrm = np.linalg.norm(Y, axis=2, keepdims=True)
    nrm = np.where(nrm == 0, 1.0, nrm)
    return Y / nrm, nrm


def forward(Y, w, Wnat, data: Data):
    """Métricas e intermedios para el gradiente (ver dfthc_train.py).

    error_2 SIN formar H (5776x5776): con G = Xflat@Xflat.T (KxK) y
    MXt = M@Xflat.T (N^2 x K):
      ||H||_F^2 = ||G||_F^2 ;  <H,M> = sum(Xflat * MXt.T)
      error_2^2 = ||G||_F^2 - 2<H,M> + ||M||_F^2
    """
    R, B, C, N = data.R, data.B, data.C, data.N
    U, nrm = normalize_rows(Y)
    X = np.empty((R, C, N, N), dtype=np.float64)
    for rho in range(R):
        Ur = U[rho]
        wr = w[rho]
        for c in range(C):
            X[rho, c] = (Ur * wr[:, c:c + 1]).T @ Ur
    X = 0.5 * (X + np.swapaxes(X, 2, 3))
    Xflat = X.reshape(data.K, data.N2)
    G = Xflat @ Xflat.T
    MXt = data.M @ Xflat.T
    inner = float(np.sum(Xflat * MXt.T))
    err2_sq = float(np.sum(G * G)) - 2.0 * inner + data.M_fro2
    err2_sq = max(err2_sq, 0.0)
    error_2 = float(np.sqrt(err2_sq))
    h1_prime = (
        data.h1_thc
        - 0.5 * data.eta * data.S
        + data.beta_1 * np.eye(N)
        - np.einsum("rc,rcnm->nm", Wnat, X, optimize=True)
    )
    h1_prime = 0.5 * (h1_prime + h1_prime.T)
    evals, evecs = np.linalg.eigh(h1_prime)
    lambda_h1 = float(np.sum(np.abs(evals)))
    wB = Wnat + np.sum(w, axis=1)
    s = np.linalg.norm(w, ord=1, axis=1) + np.abs(wB)
    lambda_h2 = float(0.25 * np.sum(s ** 2))
    Lambda = lambda_h1 + lambda_h2
    E_SOS = float(
        data.ecore - data.eta * data.beta_1
        - (lambda_h1 - float(np.sum(evals)))
        - 0.5 * float(np.sum(Wnat ** 2))
    )
    E_gap = float(E_UPPER - E_SOS)
    lam_eff = float(np.sqrt(E_gap * (2.0 * Lambda - E_gap))) if 0.0 < E_gap < 2.0 * Lambda else float("nan")
    return {
        "U": U, "nrm": nrm, "X": X, "Xflat": Xflat, "G": G, "MXt": MXt,
        "error_2": error_2, "err2_sq": err2_sq,
        "h1_prime": h1_prime, "evals": evals, "evecs": evecs,
        "lambda_h1": lambda_h1, "lambda_h2": lambda_h2, "Lambda": Lambda,
        "E_SOS": E_SOS, "E_gap": E_gap, "lambda_eff": lam_eff,
        "wB": wB, "s": s,
    }


def pack(Y, w, Wnat):
    return np.concatenate([np.asarray(Y).ravel(), np.asarray(w).ravel(), np.asarray(Wnat).ravel()])


def unpack(vec, R, B, C, N):
    nY = R * B * N
    nw = R * B * C
    Y = vec[:nY].reshape(R, B, N)
    w = vec[nY:nY + nw].reshape(R, B, C)
    Wnat = vec[nY + nw:nY + nw + R * C].reshape(R, C)
    return Y, w, Wnat


def _grad_core(fw, w, Wnat, data, A, c2):
    """Núcleo del gradiente dado A = dL/d(h1_prime) y c2 = dL/d(err2^2).

    Devuelve (dLdY, dLdw, dLdW) con la estructura de loss_and_grad.
    A y c2 los fija cada variante de pérdida (penalización / barrera /
    lambda_eff). dLdW aquí NO incluye el término g_gap*Wnat: lo añade
    la variante que lo necesite vía el parámetro extra_w (ver abajo).
    """
    R, B, C, N = data.R, data.B, data.C, data.N
    GXflat = c2 * 4.0 * (fw["G"] @ fw["Xflat"] - fw["MXt"].T)
    GX = GXflat.reshape(R, C, N, N)
    GX = 0.5 * (GX + np.swapaxes(GX, 2, 3))
    dLdX = GX - Wnat[:, :, None, None] * A[None, None, :, :]
    dLdX = 0.5 * (dLdX + np.swapaxes(dLdX, 2, 3))
    dLdW = (
        - np.einsum("nm,rcnm->rc", A, fw["X"], optimize=True)
    )
    dLd_w_x = np.empty((R, B, C), dtype=np.float64)
    for rho in range(R):
        _T = np.einsum("cnm,bm->cnb", dLdX[rho], fw["U"][rho], optimize=True)
        dLd_w_x[rho] = np.einsum("bn,cnb->bc", fw["U"][rho], _T, optimize=True)
    dLdU = np.empty((R, B, N), dtype=np.float64)
    for rho in range(R):
        _V = np.einsum("cnm,bm->cnb", dLdX[rho], fw["U"][rho], optimize=True)
        dLdU[rho] = 2.0 * np.einsum("bc,cnb->bn", w[rho], _V, optimize=True)
    U, nrm = fw["U"], fw["nrm"]
    dot = np.sum(dLdU * U, axis=2, keepdims=True)
    dLdY = (dLdU - U * dot) / nrm
    return dLdY, dLd_w_x, dLdW


def loss_and_grad_barrier(vec, data: Data, mu, target2=0.0205, floor_gap=3.92):
    """v3: pérdida = Lambda - mu*log(target2 - error_2) - mu*log(E_gap - floor_gap).

    La barrera es suave (sin el codo de relu) y -> +infinito al acercarse
    al límite, así que el optimizador NO puede violarlo. Requiere punto
    inicial factible (error_2 < target2, E_gap > floor_gap): usar
    project_W para subir E_gap a ~3.93 antes de llamar.
    """
    R, B, C, N = data.R, data.B, data.C, data.N
    Y, w, Wnat = unpack(vec, R, B, C, N)
    fw = forward(Y, w, Wnat, data)
    error_2, E_gap = fw["error_2"], fw["E_gap"]
    if error_2 >= target2 or E_gap <= floor_gap:
        return 1e12, np.zeros_like(vec), fw
    loss = (fw["Lambda"]
            - mu * np.log(target2 - error_2)
            - mu * np.log(E_gap - floor_gap))
    c2 = mu / (2.0 * error_2 * (target2 - error_2))
    g_gap = -mu / (E_gap - floor_gap)
    evecs, evals = fw["evecs"], fw["evals"]
    sgn = np.sign(evals)
    Sh1 = (evecs * sgn[None, :]) @ evecs.T
    A = Sh1 + g_gap * (Sh1 - np.eye(N))
    dLdY, dLd_w_x, dLdW = _grad_core(fw, w, Wnat, data, A, c2)
    dLdW = dLdW + 0.5 * fw["s"] * np.sign(fw["wB"]) + g_gap * Wnat
    dLd_w_lam = 0.5 * fw["s"][:, None, :] * (np.sign(w) + np.sign(fw["wB"])[:, None, :])
    dLdw = dLd_w_lam + dLd_w_x
    grad = pack(dLdY, dLdw, dLdW)
    return float(loss), grad, fw


def loss_and_grad_lameff(vec, data: Data, mu, target2=0.0205, floor_gap=3.92):
    """v5: pérdida = lambda_eff - mu*log(target2 - error_2) - mu*log(E_gap - floor_gap).

    Minimiza lambda_eff directamente (el objetivo real del score), que
    equilibra Lambda y E_gap de forma suave. d(lambda_eff)/dLambda =
    E_gap/lambda_eff = a; d(lambda_eff)/dE_gap = (Lambda-E_gap)/lambda_eff.
    """
    R, B, C, N = data.R, data.B, data.C, data.N
    Y, w, Wnat = unpack(vec, R, B, C, N)
    fw = forward(Y, w, Wnat, data)
    error_2, E_gap, lam_eff = fw["error_2"], fw["E_gap"], fw["lambda_eff"]
    if error_2 >= target2 or E_gap <= floor_gap:
        return 1e12, np.zeros_like(vec), fw
    loss = lam_eff - mu * np.log(target2 - error_2) - mu * np.log(E_gap - floor_gap)
    a = E_gap / lam_eff
    g_gap_barrier = -mu / (E_gap - floor_gap)
    b = (fw["Lambda"] - E_gap) / lam_eff + g_gap_barrier
    c2 = mu / (2.0 * error_2 * (target2 - error_2))
    evecs, evals = fw["evecs"], fw["evals"]
    sgn = np.sign(evals)
    Sh1 = (evecs * sgn[None, :]) @ evecs.T
    A = a * Sh1 + b * (Sh1 - np.eye(N))
    dLdY, dLd_w_x, dLdW = _grad_core(fw, w, Wnat, data, A, c2)
    dLdW = dLdW + 0.5 * a * fw["s"] * np.sign(fw["wB"]) + b * Wnat
    dLd_w_lam = a * 0.5 * fw["s"][:, None, :] * (np.sign(w) + np.sign(fw["wB"])[:, None, :])
    dLdw = dLd_w_lam + dLd_w_x
    grad = pack(dLdY, dLdw, dLdW)
    return float(loss), grad, fw


# ---------------------------------------------------------------------------
# Proyección de W (E_gap) e inicialización
# ---------------------------------------------------------------------------

def project_W(Y, w, W0, data, target_gap=3.93, iters=20):
    """Escala W = alpha*W0 para que E_gap = target_gap.

    E_gap(alpha) tiene forma de U con mínimo en alpha~1.0 (el portfolio):
    (lambda_h1 - tr) es 2*sum|autovalores negativos de h1_prime| y es
    extremadamente sensible a alpha (un 1% mueve E_gap ~13 Ha). Por eso
    la bisección usa un bracket ANGOSTO [1.0, 1.05] donde E_gap crece
    monótonamente desde el mínimo. target_gap debe estar apenas arriba
    del mínimo (3.914898).
    """
    def egap_of(alpha):
        fw = forward(Y, w, alpha * W0, data)
        return fw["E_gap"], fw
    e1, fw1 = egap_of(1.0)
    if e1 >= target_gap:
        return W0, fw1, 1.0
    prev_a, prev_fw = 1.0, fw1
    a = 1.0
    step = 0.001
    lo, hi, fw_lo, fw_hi = None, None, None, None
    for _ in range(60):
        a += step
        e_a, fw_a = egap_of(a)
        if e_a >= target_gap:
            lo, hi, fw_lo, fw_hi = prev_a, a, prev_fw, fw_a
            break
        prev_a, prev_fw = a, fw_a
        step *= 1.5
    if lo is None:
        return W0, fw1, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        e_mid, fw_mid = egap_of(mid)
        if e_mid < target_gap:
            lo = mid
        else:
            hi = mid
    alpha = 0.5 * (lo + hi)
    W = alpha * W0
    fw = forward(Y, w, W, data)
    return W, fw, alpha


def warm_init(portfolio_npz):
    """Desde el portfolio (base permitida): U, w, Wnat."""
    d = np.load(portfolio_npz)
    U = np.asarray(d["U"], dtype=np.float64)
    w = np.asarray(d["W"], dtype=np.float64)
    H2_I = np.asarray(d["H2_I"], dtype=np.float64)
    Wnat = H2_I - np.sum(w, axis=1)
    return U.copy(), w.copy(), Wnat.copy()


# ---------------------------------------------------------------------------
# Ángulos (con corrección C-1)
# ---------------------------------------------------------------------------

def vector_to_angles(v, tree_edges):
    """Inversa de reconstruct_u_vectors: vector unitario -> theta/pi.

    Recorre los ejes en orden INVERSO; theta = atan2(hijo, padre).
    float64; el round-trip se verifica contra la función oficial.
    """
    x = np.array(v, dtype=np.float64)
    edges = np.asarray(tree_edges, dtype=np.int64)
    thetas = np.zeros(len(edges), dtype=np.float64)
    for k in range(len(edges) - 1, -1, -1):
        p, c = int(edges[k, 0]), int(edges[k, 1])
        a, b = x[p], x[c]
        theta = np.arctan2(b, a)
        thetas[k] = theta / np.pi
        r = float(np.hypot(a, b))
        x[p], x[c] = r, 0.0
    return thetas


def balanced_tree(n):
    """Árbol binario balanceado (heap: hijos de i son 2i+1, 2i+2), orden DFS
    pre-orden (padre antes que hijo), igual estructura que el del portfolio."""
    edges = []

    def dfs(i):
        for ch in (2 * i + 1, 2 * i + 2):
            if ch < n:
                edges.append((i, ch))
                dfs(ch)

    dfs(0)
    return np.array(edges, dtype=np.int64)


def build_angle_words(U, w, Wnat, data: Data, brot=8, tree_edges=None):
    """Palabras (N+R*B, N-1) desde la factorización: filas one-body =
    autovectores de h1_prime; filas two-body = U. Cuantizadas a brot bits.

    Corrección C-1: normalizar TODOS los vectores a norma 1 en float64
    antes de cuantizar (la U guardada en float32 pierde la norma ~1e-7
    y reconstruct_u_vectors no puede reproducirla; err 2.85e-08 -> ~1e-16).
    """
    if tree_edges is None:
        tree_edges = balanced_tree(data.N)
    R, B, N = data.R, data.B, data.N
    U64 = np.asarray(U, dtype=np.float64)
    U64 = U64 / np.linalg.norm(U64, axis=2, keepdims=True)
    fw = forward(U64, w, Wnat, data)
    one_body = fw["evecs"].T
    vectors = np.vstack([one_body, U64.reshape(R * B, N)])
    # C-1: normalizar a norma 1 en float64 (todas las filas, no solo U).
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    thetas = np.array([vector_to_angles(v, tree_edges) for v in vectors])
    words = np.mod(np.round(thetas * (2 ** (brot - 1))).astype(np.int64), 2 ** brot)
    return words, tree_edges, fw


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def retrain(data, portfolio_npz, mus=(0.3, 0.1, 0.03, 0.01), maxiter=25,
            target_gap=3.93, log=print):
    """Reentrena desde el portfolio con la barrera lambda_eff (v5).

    Devuelve (U, w, Wnat, fw, history) con fw las métricas finales.
    La medición oficial es con el verificador DFTHC en Kaggle.
    """
    from scipy.optimize import minimize
    U0, w0, W0 = warm_init(portfolio_npz)
    fw0 = forward(U0, w0, W0, data)
    log(f"BASE: Lambda={fw0['Lambda']:.4f} lam_eff={fw0['lambda_eff']:.4f} "
        f"error_2={fw0['error_2']:.6f} E_gap={fw0['E_gap']:.6f}")
    W1, fw1, alpha = project_W(U0, w0, W0, data, target_gap=target_gap)
    log(f"tras proyectar W: alpha={alpha:.4f} Lambda={fw1['Lambda']:.4f} "
        f"E_gap={fw1['E_gap']:.6f} lam_eff={fw1['lambda_eff']:.4f}")
    vec = pack(U0, w0, W1)
    best = fw1["lambda_eff"]
    history = [fw1]
    for mu in mus:
        def fun(v, mu=mu):
            loss, grad, fw = loss_and_grad_lameff(v, data, mu)
            return loss, grad
        res = minimize(fun, vec, jac=True, method="L-BFGS-B",
                       options={"maxiter": maxiter, "ftol": 1e-13, "gtol": 1e-9, "maxcor": 10})
        vec = res.x
        Y1, w1, W1 = unpack(vec, data.R, data.B, data.C, data.N)
        fw = forward(Y1, w1, W1, data)
        log(f"mu={mu}: Lambda={fw['Lambda']:.4f} error_2={fw['error_2']:.6f} "
            f"E_gap={fw['E_gap']:.6f} lam_eff={fw['lambda_eff']:.4f} nit={res.nit}")
        history.append(fw)
        if fw["lambda_eff"] < best:
            best = fw["lambda_eff"]
        elif len(history) > 2 and fw["lambda_eff"] > best - 0.001:
            break
    Y1, w1, W1 = unpack(vec, data.R, data.B, data.C, data.N)
    fw = forward(Y1, w1, W1, data)
    return Y1, w1, W1, fw, history
