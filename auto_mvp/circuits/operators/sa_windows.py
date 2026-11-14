"""Fase Slow: busqueda estocastica (SA) de circuitos equivalentes con menos Toffoli
dentro de ventanas clasicas (X, CX, SWAP, CCX, CSWAP) de <=K qubits.

Exactitud: una ventana se reemplaza solo si su permutacion sobre sus qubits es identica
(comprobado sobre los 2^k estados base). Fuera de las ventanas no se toca nada. Solo se
usan ventanas fuera de bloques condicionados (lvl 0), asi que el conteo estatico es el dinamico.

Entrada: .kmx texto (formato kickmix). Salida: .kmx texto modificado + log JSON.
Uso: python3 sa_windows.py IN.kmx OUT.kmx LOG.json [K] [TIME_BUDGET_S] [SEED]
"""
import sys, json, math, random, time

IN, OUT, LOG = sys.argv[1], sys.argv[2], sys.argv[3]
K = int(sys.argv[4]) if len(sys.argv) > 4 else 5
BUDGET = float(sys.argv[5]) if len(sys.argv) > 5 else 7000.0
SEED = int(sys.argv[6]) if len(sys.argv) > 6 else 1
MIN_TOF = 2          # solo ventanas con >=2 Toffoli-like
ITERS = 300000        # iteraciones SA por intento
RESTARTS = 4
LAM = 2              # penalizacion por exceder el presupuesto de Toffoli
rng = random.Random(SEED)

CLS = {"CX", "CCX", "X", "SWAP", "CSWAP"}
TOF = {"CCX", "CSWAP"}

# ---------- parseo ----------
raw = open(IN).read().split("\n")
ops = []  # (line_idx, tokens)  solo operaciones
lvl = []
depth = 0
for li, line in enumerate(raw):
    s = line.split("#", 1)[0].strip()
    if not s or s.startswith(("APPEND", "REGISTER")):
        continue
    t = s.split()
    if t[0] == "PUSH_CONDITION":
        depth += 1; lvl.append(-1)
    elif t[0] == "POP_CONDITION":
        depth -= 1; lvl.append(-1)
    else:
        lvl.append(depth)
    ops.append((li, t))


def qids(t):
    return [int(x[1:]) for x in t[1:] if x[0] == "q" and x[1:].isdigit()]


# ---------- ventanas (greedy, maximal) ----------
wins = []
cur = None
for i, (li, t) in enumerate(ops):
    if t[0] not in CLS or "if" in t or lvl[i] != 0:
        cur = None
        continue
    q = set(qids(t))
    if cur is not None and len(cur["q"] | q) <= K:
        cur["q"] |= q
        cur["ops"].append(i)
    else:
        cur = {"q": set(q), "ops": [i]}
        wins.append(cur)
wins = [w for w in wins if sum(1 for i in w["ops"] if ops[i][1][0] in TOF) >= MIN_TOF]


# ---------- semantica bit-plane ----------
def planes_init(k):
    n = 1 << k
    P = []
    for qq in range(k):
        v = 0
        for s in range(n):
            if (s >> qq) & 1:
                v |= 1 << s
        P.append(v)
    return P


def apply(gates, k):
    n = 1 << k
    ALL = (1 << n) - 1
    p = planes_init(k)
    for g in gates:
        o = g[0]
        if o == "X":
            p[g[1]] ^= ALL
        elif o == "CX":
            p[g[2]] ^= p[g[1]]
        elif o == "SWAP":
            a, b = g[1], g[2]
            d = (p[a] ^ p[b])
            p[a] ^= d; p[b] ^= d
        elif o == "CCX":
            p[g[3]] ^= p[g[1]] & p[g[2]]
        elif o == "CSWAP":
            c, a, b = g[1], g[2], g[3]
            d = (p[a] ^ p[b]) & p[c]
            p[a] ^= d; p[b] ^= d
    return p


def ntof(gates):
    return sum(1 for g in gates if g[0] in ("CCX", "CSWAP"))


def diff_count(p, T, k):
    m = 0
    for x, y in zip(p, T):
        m |= x ^ y
    return bin(m).count("1")


# ---------- generacion de puertas ----------
def rand_gate(k, tof_ok):
    while True:
        r = rng.random()
        if r < 0.15:
            return ("X", rng.randrange(k))
        if r < 0.55:
            a, b = rng.sample(range(k), 2)
            return ("CX", a, b)
        if r < 0.65:
            a, b = rng.sample(range(k), 2)
            return ("SWAP", a, b)
        if not tof_ok:
            continue
        if r < 0.85 and k >= 3:
            c1, c2, t = rng.sample(range(k), 3)
            return ("CCX", c1, c2, t)
        if k >= 3:
            c, a, b = rng.sample(range(k), 3)
            return ("CSWAP", c, a, b)


def cost(gates, T, k, t_budget):
    """Coste del SA (v2.14: solo compuertas cobrables).

    La única métrica es la baja de Toffolis con la permutación
    intacta. El coste es: desajuste de la permutación (mism) +
    penalización por exceder el presupuesto de Toffoli (over). NO
    hay ningún término por el número total de instrucciones ni por
    las Clifford: quitar Clifford no mueve el S y no se premia.
    El circuito candidato siempre tiene la misma longitud que el
    original (L puertas); lo único que cambia es cuántas son
    Toffoli. La aceptación final exige ganancia estricta de
    Toffoli (gain > 0) con permutación idéntica (mism = 0).
    """
    p = apply(gates, k)
    mism = diff_count(p, T, k)
    over = max(0, ntof(gates) - t_budget)
    return mism + LAM * over, mism, over


def sa_search(orig, T, k, t_budget, iters):
    """Busca circuito de longitud len(orig)+slack con <=t_budget Toffoli y permutacion T."""
    L = len(orig)
    # arranque: original sin un Toffoli (asi cumple presupuesto t0-1)
    tof_idx = [i for i, g in enumerate(orig) if g[0] in ("CCX", "CSWAP")]
    start = list(orig)
    if tof_idx and ntof(orig) > t_budget:
        i = rng.choice(tof_idx)
        start[i] = ("X", rng.randrange(k))
    while ntof(start) > t_budget:  # por si acaso
        idx = [i for i, g in enumerate(start) if g[0] in ("CCX", "CSWAP")]
        start[rng.choice(idx)] = ("X", 0)
    cur = start
    c_cur, m_cur, o_cur = cost(cur, T, k, t_budget)
    best, c_best = cur, c_cur
    T0, T1 = 1.5, 0.02
    for it in range(iters):
        if c_best == 0:
            break
        temp = T0 * (T1 / T0) ** (it / iters)
        cand = list(cur)
        r = rng.random()
        j = rng.randrange(L)
        if r < 0.75:
            tof_ok = ntof(cand) < t_budget + 1 or cand[j][0] in ("CCX", "CSWAP")
            cand[j] = rand_gate(k, True)
        elif r < 0.9 and L > 1:
            j2 = min(L - 1, max(0, j + rng.choice((-1, 1))))
            cand[j], cand[j2] = cand[j2], cand[j]
        else:
            cand[j] = rand_gate(k, False)
        c_new, m_new, o_new = cost(cand, T, k, t_budget)
        if c_new <= c_cur or rng.random() < math.exp(-(c_new - c_cur) / temp):
            cur, c_cur = cand, c_new
            if c_cur < c_best:
                best, c_best = cur, c_cur
    return best, c_best


def gate_text(g, Q):
    o = g[0]
    if o == "X":
        return f"X q{Q[g[1]]}"
    if o == "CX":
        return f"CX q{Q[g[1]]} q{Q[g[2]]}"
    if o == "SWAP":
        return f"SWAP q{Q[g[1]]} q{Q[g[2]]}"
    if o == "CCX":
        return f"CCX q{Q[g[1]]} q{Q[g[2]]} q{Q[g[3]]}"
    if o == "CSWAP":
        return f"CSWAP q{Q[g[1]]} q{Q[g[2]]} q{Q[g[3]]}"


def to_local(t, Q):
    """Traduce una op original a puertas locales."""
    o = t[0]
    l = [Q.index(x) for x in qids(t)]
    if o == "X":
        return ("X", l[0])
    if o == "CX":
        return ("CX", l[0], l[1])
    if o == "SWAP":
        return ("SWAP", l[0], l[1])
    if o == "CCX":
        return ("CCX", l[0], l[1], l[2])
    if o == "CSWAP":
        return ("CSWAP", l[0], l[1], l[2])


# ---------- bucle principal ----------
t_start = time.time()
replace = {}      # first op index -> list of new lines; ops removed
remove = set()
log = []
gain_total = 0
order = list(range(len(wins)))
rng.shuffle(order)
for wi in order:
    if time.time() - t_start > BUDGET:
        break
    w = wins[wi]
    Q = sorted(w["q"])
    k = len(Q)
    idxs = w["ops"]
    orig = [to_local(ops[i][1], Q) for i in idxs]
    T = apply(orig, k)
    t0 = ntof(orig)
    t_best = t0
    sol = orig
    tb = t0 - 1
    while tb >= 0 and time.time() - t_start < BUDGET:
        found = None
        for _ in range(RESTARTS):
            cand, c = sa_search(sol, T, k, tb, ITERS)
            if c == 0:
                found = cand
                break
        if found is None:
            break
        sol = found
        t_best = ntof(sol)
        tb = t_best - 1
    gain = t0 - t_best
    gain_total += gain
    log.append({"win": wi, "qubits": k, "ops": len(idxs), "tof0": t0, "tof_best": t_best, "gain": gain})
    if gain > 0:
        first = idxs[0]
        new_lines = [gate_text(g, Q) for g in sol]
        replace[ops[first][0]] = new_lines
        for i in idxs:
            remove.add(ops[i][0])
        for i in idxs[1:]:
            pass
    print(f"win {wi} k={k} ops={len(idxs)} tof {t0}->{t_best}", flush=True)

out = []
for li, line in enumerate(raw):
    if li in replace:
        out.extend(replace[li])
    if li in remove:
        continue
    out.append(line)
open(OUT, "w").write("\n".join(out))
json.dump({"K": K, "seed": SEED, "windows_tested": len(log), "gain_total": gain_total,
           "elapsed_s": round(time.time() - t_start, 1), "details": log},
          open(LOG, "w"), indent=1)
print("gain_total", gain_total, "windows", len(log), "elapsed", round(time.time() - t_start, 1))
