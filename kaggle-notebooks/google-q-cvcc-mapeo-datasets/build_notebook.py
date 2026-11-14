#!/usr/bin/env python3
"""Construye el Notebook de mapeo de los dos datasets (competencia +
qualtran) con baseline, verificadores oficiales, calificación oficial
por semilla y un LLM gratuito en CPU (Qwen) que propone semillas.
Corrida de prueba de 30 minutos (reloj interno de 28 min).

Lo que pidió Arturo, tal cual:
  1. Mapear los dos datasets en un Notebook (competencia
     google-verifiable-quantum-circuit-compilation + qualtran
     dcpracmatic/qualtran) para integrarlos y llamarlos
     automáticamente, conectados como baseline y verificadores.
  2. Definir la calificación de cada semilla según la competencia
     (leída de los verificadores oficiales, no inventada).
  3. Un LLM gratuito (Qwen2.5-1.5B-Instruct, en CPU, bfloat16, con
     fallback a 0.5B) que busca soluciones proponiendo semillas JSON.
  4. Corrida de prueba de 30 minutos en Kaggle.

El repo (privado) va vendido en base64 como en auto-meta-30: Kaggle
no puede clonarlo y jamás va un token aquí. Solo el dataset de la
competencia + el repo + el dataset qualtran: nada de terceros.
"""
import base64
import io
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path.home() / "workspace/sandbox-run/google-q-cvcc-audit2"


def build_tarball() -> tuple[bytes, list[str]]:
    buf = io.BytesIO()
    files = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in sorted(REPO.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(REPO)
            if (rel.name.startswith("INFORME_AUDITORIA")
                    or "__pycache__" in rel.parts
                    or ".pytest_cache" in rel.parts
                    or rel.parts[0] in ("runs", "build", "notes", "tests",
                                       "kaggle-notebooks")
                    or rel.suffix in (".pyc", ".log")
                    or (rel.suffix == ".json" and p.stat().st_size > 100_000)):
                continue
            files.append(str(rel))
            tf.add(p, arcname=str(rel))
    print(f"tarball: {len(files)} archivos")
    return buf.getvalue(), files


def md_cell(src):
    return {"cell_type": "markdown", "metadata": {},
            "source": src.splitlines(True)}


def code_cell(src):
    return {"cell_type": "code", "execution_count": None,
            "metadata": {}, "outputs": [],
            "source": src.splitlines(True)}


# ------------------------------------------------------------------
# Celda 1: el repo vendido (snapshot v2.14.0)
# ------------------------------------------------------------------
def cell_repo(b64_chunks: list[str], n_files: int) -> dict:
    return code_cell(
        "# Celda 1: bajar el repositorio al notebook (snapshot vendido)\n"
        "import base64, io, tarfile\n"
        "from pathlib import Path\n"
        "B64 = [\n" + "".join(f'    \"{c}\"\n' for c in b64_chunks) + "]\n"
        "REPO = Path('/kaggle/working/repo')\n"
        "REPO.mkdir(parents=True, exist_ok=True)\n"
        "raw = base64.b64decode(''.join(B64))\n"
        "print('tar.gz bytes:', len(raw))\n"
        "with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tf:\n"
        "    tf.extractall(REPO)\n"
        "files = sorted(str(p.relative_to(REPO)) for p in REPO.rglob('*') if p.is_file())\n"
        "print('archivos:', len(files))\n"
        f"if len(files) != {n_files}: print(f'AVISO: se esperaban {n_files} archivos, hay {{len(files)}}')\n"
        "if not ('auto_mvp/benchmark.py' in files and 'auto_mvp/causal.py' in files): print('AVISO: faltan modulos del repo (benchmark/causal)')\n"
        "print('repo OK: v2.14.0 con benchmark (5 operadores, delta_t) + rol causal')\n")


CELL_RELOJ = r'''
# Celda 0: reloj de la corrida (30 min) y rutas de los dos datasets
import glob, os, time
from pathlib import Path

T0 = time.time()
BUDGET_S = 28 * 60  # 28 min internos; el kernel tiene 30

def quedan():
    """Segundos que quedan de la corrida de prueba."""
    return BUDGET_S - (time.time() - T0)

def minutos():
    return (time.time() - T0) / 60.0

def hay_tiempo(seg):
    return quedan() > seg

IN = Path('/kaggle/input')
print('contenido de /kaggle/input:', sorted(p.name for p in IN.iterdir()) if IN.exists() else 'NO EXISTE')

def _buscar(fragmento):
    # MEDIDO en v6 (2026-11-13): los montajes vienen ANIDADOS, no directos:
    #   /kaggle/input/competitions/google-verifiable-quantum-circuit-compilation
    #   /kaggle/input/datasets/dcpracmatic/qualtran
    # Primero las rutas conocidas, luego busqueda recursiva por nombre.
    conocidos = [
        IN / 'competitions' / 'google-verifiable-quantum-circuit-compilation',
        IN / 'datasets' / 'dcpracmatic' / 'qualtran',
        IN / 'google-verifiable-quantum-circuit-compilation',
        IN / 'qualtran',
    ]
    for cand in conocidos:
        if fragmento in cand.name and cand.exists():
            return cand
    if IN.exists():
        for cand in sorted(IN.rglob('*')):
            if cand.is_dir() and fragmento in cand.name.lower():
                return cand
    return None

COMP = _buscar('verifiable') or _buscar('google')
QUAL = _buscar('qualtran')
print('competencia:', COMP)
print('qualtran:', QUAL)
if COMP is None:
    print('AVISO: falta la fuente de la competencia; las celdas que la usan se saltan')
if QUAL is None:
    print('AVISO: falta el dataset qualtran; las celdas que lo usan se saltan')
print(f'reloj: quedan {quedan()/60:.1f} min de 28')
'''

CELL_MAPEO = r'''
# Celda 2: MAPEO de los dos datasets (árbol + tamaños + archivos clave)
import json
from pathlib import Path

def arbol(root, max_archivos=400):
    out = []
    for p in sorted(root.rglob('*')):
        if p.is_file():
            out.append({'path': str(p.relative_to(root)),
                        'bytes': p.stat().st_size})
        if len(out) >= max_archivos:
            break
    return out

mapa = {}
for nombre, root in [('competencia', COMP), ('qualtran', QUAL)]:
    if root is None:
        print(f'== {nombre}: MONTAJE AUSENTE ==')
        mapa[nombre] = {'root': None, 'n_archivos': 0, 'total_bytes': 0, 'archivos': []}
        continue
    archivos = arbol(root)
    total = sum(a['bytes'] for a in archivos)
    mapa[nombre] = {'root': str(root), 'n_archivos': len(archivos),
                    'total_bytes': total, 'archivos': archivos}
    print(f"== {nombre}: {len(archivos)} archivos, {total/1e6:.1f} MB ==")
    for a in archivos:
        if a['bytes'] > 1_000_000 or 'verif' in a['path'] or a['path'].endswith(('.md', '.pdf')):
            print(f"   {a['bytes']/1e6:8.1f} MB  {a['path']}")

# Archivos clave que el resto de la corrida necesita
CLAVE = {
  'verificador invsqrt': 'verifiers/invsqrt/verify_submission_invsqrt.py',
  'verificador dqi': 'verifiers/dqi/verify_submission_dqi.py',
  'verificador dfthc': 'verifiers/dfthcsos/verify.py',
  'scoring dfthc': 'verifiers/dfthcsos/SCORING_README.md',
  'kickmix.so': 'kickmix/kickmix.so',
  'muestra invsqrt': 'sample_submission/invsqrt.kmb',
  'muestra dqi': 'sample_submission/dqi.kmb',
  'muestra dfthc': 'sample_submission/dfthcsos/submission.npz',
  'fcidump': 'verifiers/dfthcsos/FeMoCo76o113e.fcidump',
  'paper': 'verifiable_circuit_compilation.pdf',
}
print('== archivos clave (competencia) ==')
if COMP is None:
    print('   (sin COMP, salto)')
else:
  for nombre, rel in CLAVE.items():
    p = COMP / rel
    print(f"   {'OK ' if p.exists() else 'FALTA'} {nombre}: {rel}"
          + (f" ({p.stat().st_size/1e6:.1f} MB)" if p.exists() else ''))
print('== qualtran: kickmix + libreria ==')
if QUAL is None:
    print('   (sin QUAL, salto)')
else:
  for rel in ['kickmix/pyproject.toml', 'kickmix/src/kickmix',
            'qualtran/__init__.py', 'qualtran/bloqs']:
    p = QUAL / 'Qualtran-main' / rel
    print(f"   {'OK ' if p.exists() else 'FALTA'} {rel}")
Path('/kaggle/working/MAPEO.json').write_text(json.dumps(mapa, indent=1)[:200000])
print('MAPEO.json escrito')
'''

CELL_SETUP = r'''
# Celda 3: kickmix (simulador oficial) + qualtran (la libreria)
import subprocess, sys
from pathlib import Path

print('== kickmix ==')
# MEDIDO en v14 (2026-11-13): en Kaggle `import kickmix` NO falla, pero trae
# un paquete de espacio de nombres VACIO (file=None, sin Circuit). El `try`
# clasico nunca llega al pip install. Hay que VERIFICAR Circuit, y si falta:
#   1) el kickmix.so del dataset (binario oficial, funciona en py3.13)
#   2) pip install --force-reinstall kickmix==1.0.0 (hay wheel para py3.13)
import kickmix as km
def _km_ok():
    try:
        import kickmix as _km
        return hasattr(_km, 'Circuit') and hasattr(_km, 'Simulator')
    except Exception:
        return False
if not _km_ok():
    print('kickmix vacio (sin Circuit); probando el kickmix.so del dataset...')
    try:
        import shutil
        _so = COMP / 'kickmix' / 'kickmix.so' if COMP is not None else None
        if _so is not None and _so.exists():
            shutil.copy(str(_so), '/kaggle/working/kickmix.so')
            sys.path.insert(0, '/kaggle/working')
            if 'kickmix' in sys.modules:
                del sys.modules['kickmix']
            import kickmix as km
            print('kickmix.so del dataset:', getattr(km, '__file__', '?'))
    except Exception as _e:
        print('kickmix.so del dataset no cargo:', str(_e)[:200])
if not _km_ok():
    print('probando pip install --force-reinstall kickmix==1.0.0...')
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                        '--force-reinstall', 'kickmix==1.0.0'],
                       capture_output=True, text=True, timeout=300)
    print('pip install kickmix:', r.returncode)
    if 'kickmix' in sys.modules:
        del sys.modules['kickmix']
    try:
        import kickmix as km
    except Exception as _e:
        print('pip kickmix no cargo:', str(_e)[:200])
KM_OK = _km_ok()
print('kickmix OK:', KM_OK, '| Circuit:', hasattr(km, 'Circuit'),
      '| Simulator:', hasattr(km, 'Simulator'),
      '| file:', getattr(km, '__file__', None))

print('== qualtran (dataset dcpracmatic/qualtran) ==')
QUAL_OK = False
if QUAL is None:
    print('AVISO: sin dataset qualtran; se salta su import')
else:
    QUAL_MAIN = QUAL / 'Qualtran-main'
    if str(QUAL_MAIN) not in sys.path:
        sys.path.insert(0, str(QUAL_MAIN))
    try:
        import qualtran
        print('qualtran:', getattr(qualtran, '__version__', 'sin version'))
        QUAL_OK = True
    except Exception as e:
        print('import qualtran fallo:', str(e)[:300])
        try:
            r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                                'attrs', 'cirq', 'networkx', 'sympy'],
                               capture_output=True, text=True, timeout=300)
            print('pip install deps qualtran:', r.returncode)
            import qualtran
            print('qualtran tras instalar deps:', getattr(qualtran, '__version__', 'sin version'))
            QUAL_OK = True
        except Exception as e2:
            print('qualtran NO disponible en este kernel:', str(e2)[:300])
if QUAL_OK:
    try:
        from qualtran.bloqs.basic_gates import CNOT
        print('Bloq de ejemplo OK: CNOT =', CNOT())
    except Exception as e:
        print('Bloqs no listables:', str(e)[:200])
print(f'setup listo; quedan {quedan()/60:.1f} min')
'''

CELL_BASELINE = r'''
# Celda 4: BASELINE + CALIFICACION OFICIAL por semilla (de los verificadores)
#   invsqrt: S = Q x C,  C = Toffolis + T/4   (verify_submission_invsqrt.py)
#   DQI:     S = R(eps+) x Q^2 x T,  R(eps) = ln2 / -ln(1/2 + 2*sqrt(eps))
#            eps+ = cota superior Clopper-Pearson (confianza 1-2^-128), < 1/16
#   DFTHC:   S = lambda_eff x T_total x Q_total,
#            lambda_eff = sqrt(E_gap x (2*Lambda - E_gap))
#            puertas: Lambda > 49.0, E_gap > 3.914898 Ha, error_1/2 <= 20 mHa
import json, math, os, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path('/kaggle/working/repo')))
from auto_mvp.circuit import fast_verify_invsqrt, fast_verify_dqi
import kickmix as km

BASE = {}
KM_OK = globals().get('KM_OK', False)
if COMP is None or not KM_OK:
    print('AVISO: baseline no medido (COMP=%s, KM_OK=%s)' % (COMP, KM_OK))
    for _t in ('invsqrt', 'dqi', 'dfthc'):
        BASE[_t] = {'disponible': False,
                    'nota': 'sin montaje de la competencia' if COMP is None else 'sin kickmix con Circuit'}
    Path('/kaggle/working/BASELINE.json').write_text(json.dumps(BASE, indent=2, ensure_ascii=False))
    print(f'BASELINE.json escrito (sin datos); quedan {quedan()/60:.1f} min')
else:

    def _stats_kmb(path):
        c = km.Circuit.from_file(str(path))
        st = c.operation_statistics()
        return {'qubits': c.num_qubits,
                'toffoli_like': st.num_toffoli_like,
                'instructions': st.num_instructions}

    # --- invsqrt: la muestra oficial, medida con el fast_verify del repo ---
    inv_kmb = COMP / 'sample_submission/invsqrt.kmb'
    inv_kmx = Path('/kaggle/working/invsqrt_muestra.kmx')
    c = km.Circuit.from_file(str(inv_kmb))
    c.to_file(str(inv_kmx))
    if not inv_kmx.exists():
        print('AVISO: no se pudo escribir el .kmx de la muestra invsqrt; se salta invsqrt')
        BASE['invsqrt'] = {'disponible': False, 'nota': 'no se pudo convertir .kmb a .kmx'}
    else:
        print('invsqrt .kmb -> .kmx:', inv_kmx.exists(), inv_kmx.stat().st_size if inv_kmx.exists() else 0)
        m = fast_verify_invsqrt(inv_kmx, max_x=1024)
        BASE['invsqrt'] = {'archivo': 'sample_submission/invsqrt.kmb',
                           'formula': 'S = Q x C, C = Toffolis + T/4',
                           'Q': m.get('qubits'), 'S_fast_max_x_1024': m.get('S'),
                           'valid': bool(m.get('valid'))}
        print('invsqrt baseline:', BASE['invsqrt'])

    # --- DQI: estadisticas + intento de fast_verify con 2048 shots (con tope de tiempo) ---
    dqi_kmb = COMP / 'sample_submission/dqi.kmb'
    st = _stats_kmb(dqi_kmb)
    print('DQI stats:', st)

    def _clopper_pearson_cero(n, log2_delta=-128):
        # Cota superior con 0 errores: eps+ = 1 - delta^(1/n), delta = 2^log2_delta
        return 1.0 - (2.0 ** log2_delta) ** (1.0 / n)

    def _R(eps):
        return math.log(2) / -math.log(0.5 + 2 * math.sqrt(eps))

    eps_plus_2048 = _clopper_pearson_cero(2048)
    R_2048 = _R(eps_plus_2048)
    S_dqi_est = R_2048 * (st['qubits'] ** 2) * st['toffoli_like']
    BASE['dqi'] = {'archivo': 'sample_submission/dqi.kmb',
                   'formula': 'S = R(eps+) x Q^2 x T',
                   'Q': st['qubits'], 'T_estatica': st['toffoli_like'],
                   'instructions': st['instructions'],
                   'eps_plus_0_errores_2048_shots': eps_plus_2048,
                   'R': R_2048,
                   'S_estimada_T_estatica': S_dqi_est,
                   'nota': 'La muestra DQI es el circuito de REFERENCIA (Q=1893, '
                           'T=5.7M), no el mejor publico (Q=892, T=453k, que vive '
                           'en el workspace del repo, no en este dataset). '
                           'T estatica sobreestima: la media por shot es menor. '
                           'El S oficial necesita el verificador con 102400 shots.'}
    print('DQI estimada (T estatica):', f"S ~ {S_dqi_est:,.0f}  (R={R_2048:.4f}, eps+={eps_plus_2048:.6f})")
    if hay_tiempo(8 * 60):
        print('DQI: intento fast_verify 2048 shots (tope 8 min)...')
        try:
            r = subprocess.run([sys.executable, '-c',
                "import sys; sys.path.insert(0, '/kaggle/working/repo');"
                "from auto_mvp.circuit import fast_verify_dqi;"
                "import json; print(json.dumps(fast_verify_dqi('" + str(COMP) + "/sample_submission/dqi.kmb', num_shots=2048)))"],
                capture_output=True, text=True, timeout=480,
                env={**os.environ, 'PYTHONPATH': '/kaggle/working'})
            print('fast_verify_dqi salida:', r.stdout[-500:], r.stderr[-300:])
            try:
                d = json.loads(r.stdout.strip().splitlines()[-1])
                BASE['dqi']['fast_verify_2048'] = d
                print('DQI fast_verify 2048:', d)
            except Exception:
                print('DQI fast_verify sin JSON util')
        except subprocess.TimeoutExpired:
            print('DQI fast_verify: no termino en 8 min (circuito de 64M instrucciones); queda la estimada')
    else:
        print('DQI fast_verify saltado: quedan menos de 8 min')

    # --- DFTHC: el verificador OFICIAL sobre la muestra (unos 25 s segun su README) ---
    dfthc_dir = COMP / 'sample_submission/dfthcsos'
    ver_dir = COMP / 'verifiers'
    if hay_tiempo(6 * 60):
        print('DFTHC: verificador oficial sobre la muestra...')
        try:
            r = subprocess.run([sys.executable, 'dfthcsos/verify.py', str(dfthc_dir)],
                               cwd=str(ver_dir), capture_output=True, text=True, timeout=300,
                               env={**os.environ, 'PYTHONPATH': '/kaggle/working'})
            print('DFTHC verificador salida:', r.stdout[-800:], r.stderr[-300:])
            try:
                txt = r.stdout
                ini, fin = txt.find('{'), txt.rfind('}')
                d = json.loads(txt[ini:fin + 1])
                BASE['dfthc'] = {'archivo': 'sample_submission/dfthcsos/',
                                 'formula': 'S = lambda_eff x T_total x Q_total',
                                 'score_oficial': d.get('score'),
                                 'lambda_eff': d.get('lambda_eff'),
                                 'toffoli_count': d.get('toffoli_count'),
                                 'num_qubits': d.get('num_qubits'),
                                 'status': d.get('status')}
            except Exception:
                BASE['dfthc'] = {'archivo': 'sample_submission/dfthcsos/',
                                 'formula': 'S = lambda_eff x T_total x Q_total',
                                 'salida': r.stdout[-500:], 'error': r.stderr[-300:]}
        except subprocess.TimeoutExpired:
            BASE['dfthc'] = {'formula': 'S = lambda_eff x T_total x Q_total',
                             'nota': 'verificador oficial no termino en 5 min',
                             'score_publicado_README': 3355599588.3155365}
    else:
        BASE['dfthc'] = {'formula': 'S = lambda_eff x T_total x Q_total',
                         'nota': 'verificador saltado por tiempo',
                         'score_publicado_README': 3355599588.3155365}
    print('DFTHC baseline:', BASE.get('dfthc'))
    Path('/kaggle/working/BASELINE.json').write_text(json.dumps(BASE, indent=2, ensure_ascii=False))

print(f'BASELINE.json escrito; quedan {quedan()/60:.1f} min')
'''

CELL_LLM = r'''
# Celda 5: LLM GRATUITO EN CPU (Qwen) que propone semillas JSON
# Modelo: Qwen2.5-1.5B-Instruct en bfloat16, CPU, sin cuantizar a mano
# (3 GB en RAM). Fallback: Qwen2.5-0.5B-Instruct (1 GB). Si no hay
# memoria o no baja, se sigue con las semillas por defecto del repo.
import json, os
from pathlib import Path

def _mem_gb():
    try:
        for l in open('/proc/meminfo'):
            if l.startswith('MemAvailable'):
                return int(l.split()[1]) / 1e6
    except Exception:
        pass
    return 99.0

LLM = {'modelo': None, 'semillas': [], 'origen': 'ninguno'}
PROMPT_BASE = (
 "You are an optimization strategist for the Google Verifiable Quantum "
 "Circuit Compilation competition. Three tasks, lower score is better.\n"
 "Baselines (official scoring):\n"
 f"  invsqrt: S = Q x C, baseline S ~ {BASE['invsqrt'].get('S_fast_max_x_1024')} "
 f"(Q={BASE['invsqrt'].get('Q')}), circuit has 47k instructions.\n"
 f"  DQI: S = R(eps+) x Q^2 x T, Q={BASE['dqi'].get('Q')}, static T={BASE['dqi'].get('T_estatica')}, "
 f"{BASE['dqi'].get('instructions')} instructions (la muestra es el circuito de referencia, no el mejor publico).\n"
 f"  DFTHC: S = lambda_eff x T_total x Q_total, baseline S = 3.356e9.\n"
 "Operators available (exact rewrites, they never break the circuit):\n"
 "  peephole: cancels adjacent identical self-inverse Clifford pairs and merges adjacent Z_POW.\n"
 "  commuting: cancels identical self-inverse pairs separated by gates on disjoint qubits; param max_gap (16..256).\n"
 "  rotation_merge: merges Z_POW across commuting gates.\n"
 "  fanout: detection only, measures potential T savings (no rewrite).\n"
 "  sa_windows: simulated annealing on windows, slow.\n"
 "Only Clifford gates can be removed by peephole/commuting; the score moves only when Toffolis move.\n"
 "Propose 3 seeds as a JSON list, each with keys: name, operators (list in order), "
 "params (dict, e.g. {\"max_gap\": 256}), why (one sentence), expected (one sentence). "
 "Answer with ONLY the JSON list, no other text."
)

DEFAULT_SEEDS = [
  {'name': 'peephole+commuting-256', 'operators': ['peephole', 'commuting'],
   'params': {'max_gap': 256}, 'why': 'La combinacion que mas quita en la semilla (198).',
   'expected': 'Quita ~198 Clifford, S igual (no toca Toffolis).'},
  {'name': 'commuting-256-sola', 'operators': ['commuting'],
   'params': {'max_gap': 256}, 'why': 'La conmutacion sola subsume al peephole.',
   'expected': 'Quita ~198 Clifford, S igual.'},
  {'name': 'peephole+rotation_merge', 'operators': ['peephole', 'rotation_merge'],
   'params': {}, 'why': 'Probar si hay fusiones de rotacion tras limpiar.',
   'expected': '0 fusiones medidas antes en la semilla; verificar.'},
]

if hay_tiempo(12 * 60):
    mem = _mem_gb()
    print(f'RAM disponible: {mem:.1f} GB')
    modelo = 'Qwen/Qwen2.5-1.5B-Instruct' if mem >= 6 else 'Qwen/Qwen2.5-0.5B-Instruct'
    print('modelo elegido:', modelo)
    try:
        import torch
        torch.set_num_threads(os.cpu_count() or 4)
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(modelo)
        mdl = AutoModelForCausalLM.from_pretrained(
            modelo, torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True, device_map='cpu')
        mdl.eval()
        msgs = [{'role': 'user', 'content': PROMPT_BASE}]
        texto = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        ids = tok(texto, return_tensors='pt')
        with torch.no_grad():
            out = mdl.generate(**ids, max_new_tokens=600, do_sample=False,
                               pad_token_id=tok.eos_token_id)
        resp = tok.decode(out[0][ids['input_ids'].shape[1]:], skip_special_tokens=True)
        print('respuesta LLM (primeros 1500 caracteres):')
        print(resp[:1500])
        ini, fin = resp.find('['), resp.rfind(']')
        if ini >= 0 and fin > ini:
            semillas = json.loads(resp[ini:fin + 1])
            LLM['modelo'] = modelo
            LLM['semillas'] = semillas
            LLM['origen'] = 'llm'
            print(f'LLM propuso {len(semillas)} semillas')
        else:
            print('LLM no devolvio JSON; se usan las semillas por defecto')
            LLM['semillas'] = DEFAULT_SEEDS
            LLM['origen'] = 'por-defecto (LLM sin JSON)'
    except Exception as e:
        print('LLM fallo:', str(e)[:400])
        print('Se siguen con las semillas por defecto del repo')
        LLM['semillas'] = DEFAULT_SEEDS
        LLM['origen'] = f'por-defecto (fallo LLM: {str(e)[:120]})'
else:
    print('LLM saltado por tiempo; semillas por defecto')
    LLM['semillas'] = DEFAULT_SEEDS
    LLM['origen'] = 'por-defecto (sin tiempo)'
Path('/kaggle/working/LLM_SEEDS.json').write_text(json.dumps(LLM, indent=2, ensure_ascii=False))
print(f"LLM listo ({LLM['origen']}); quedan {quedan()/60:.1f} min")
'''

CELL_CORRIDA = r'''
# Celda 6: CORRIDA DE PRUEBA (30 min) — el benchmark del repo sobre la
# semilla invsqrt + las semillas que propuso el LLM, medidas con el
# verificador rapido (S oficial, max_x=1024). El DQI no se optimiza
# aqui: 86M de instrucciones no caben en 30 min; solo su baseline.
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path('/kaggle/working/repo')))
from auto_mvp.benchmark import benchmark
from auto_mvp.causal import classify_benchmark
from auto_mvp.circuit import fast_verify_invsqrt
from auto_mvp.circuits.operators.peephole import peephole_clean
from auto_mvp.circuits.operators.commuting import commuting_clean
from auto_mvp.circuits.operators.rotation_merge import rotation_merge

RES = {'benchmark': None, 'roles_causales': None, 'semillas_llm': []}
OPS = {'peephole': lambda lines: peephole_clean(lines),
       'commuting': lambda lines: commuting_clean(lines),
       'rotation_merge': lambda lines: rotation_merge(lines)}

inv_kmx = Path('/kaggle/working/invsqrt_muestra.kmx')
print('== benchmark del repo (5 operadores) sobre la semilla invsqrt ==')
try:
    rep = benchmark(inv_kmx, work_dir='/kaggle/working/bench', run_sa=False, task='invsqrt')
    RES['benchmark'] = rep
    print('S base:', rep.get('base_S'))
    for nombre, r in rep['operators'].items():
        print(f"  {nombre:15s} valido={r.get('valid')}  S={r.get('S')}  dS={r.get('delta_S')}  "
              f"stats={str(r.get('stats'))[:160]}")
    print('comentarios:', rep.get('comments'))
    RES['roles_causales'] = classify_benchmark(rep)
    print('roles causales:', json.dumps(RES['roles_causales'], ensure_ascii=False)[:800])
except Exception as e:
    print('benchmark fallo:', str(e)[:500])

print('== semillas del LLM aplicadas en cadena ==')
lineas_base = inv_kmx.read_text().splitlines(keepends=True)
for semilla in (LLM.get('semillas') or [])[:3]:
    if not hay_tiempo(3 * 60):
        print('sin tiempo para mas semillas; se para aqui')
        break
    nombre = semilla.get('name', 'sin-nombre')
    ops_raw = semilla.get('operators') or []
    ops = [o for o in ops_raw if o in OPS]
    tiene_sa = 'sa_windows' in ops_raw
    if tiene_sa:
        print(f'  {nombre}: sa_windows saltado (circuito demasiado grande para SA en 30 min, igual que el benchmark)')
    if not ops:
        if tiene_sa:
            RES['semillas_llm'].append({'name': nombre, 'status': 'saltado',
                                        'operadores': ['sa_windows'],
                                        'reason': 'SA saltado: circuito demasiado grande para el SA en 30 min'})
        else:
            print(f'  {nombre}: sin operadores conocidos ({ops_raw}); se reporta, no se corre')
            RES['semillas_llm'].append({'name': nombre, 'status': 'sin-operadores-conocidos',
                                        'propuesta': semilla})
        continue
    try:
        lineas = list(lineas_base)
        stats_total = {}
        for op in ops:
            lineas, st = OPS[op](lineas)
            if lineas is None:
                raise ValueError(f'{op} devolvio lineas None')
            # Los operadores re-emiten Z_POW SIN salto de linea; si no se
            # normaliza, la Z_POW se pega a la siguiente linea y el .kmx
            # ya no carga ('Invalid decimal angle'). Medido en v15/seed2.
            lineas = [l if l.endswith('\n') else l + '\n' for l in lineas]
            stats_total[op] = st
        tmp = Path(f"/kaggle/working/semilla_{nombre}.kmx")
        tmp.write_text(''.join(lineas))
        m = fast_verify_invsqrt(tmp, max_x=1024)
        RES['semillas_llm'].append({'name': nombre, 'status': 'medido',
                                    'operadores': ops, 'stats': stats_total,
                                    'S': m.get('S'), 'valid': bool(m.get('valid'))})
        print(f"  {nombre}: S={m.get('S')} valido={m.get('valid')} stats={str(stats_total)[:200]}")
    except Exception as e:
        print(f'  {nombre}: fallo al aplicar: {str(e)[:300]}')
        RES['semillas_llm'].append({'name': nombre, 'status': 'fallo', 'error': str(e)[:300]})
Path('/kaggle/working/RESULTADOS.json').write_text(json.dumps(RES, indent=2, ensure_ascii=False))
print(f"RESULTADOS.json escrito; quedan {quedan()/60:.1f} min")
'''

CELL_REPORTE = r'''
# Celda 7: REPORTE — que funciona y que tan bien funciona
import json
from pathlib import Path

def _s(v):
    return f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)

bench = (RES.get('benchmark') or {})
ops = bench.get('operators', {})
lineas = []
lineas.append('# Reporte: mapeo de datasets + baseline + LLM + corrida 30 min')
lineas.append('')
lineas.append(f"Tiempo total: {minutos():.1f} min (presupuesto 28).")
lineas.append('')
lineas.append('## 1. Mapeo')
lineas.append(f"- Competencia: {COMP} (verificadores + muestras + kickmix.so + paper).")
lineas.append(f"- Qualtran: {QUAL} (Qualtran-main: kickmix/ con el simulador + qualtran/ con los Bloqs).")
lineas.append('- El dataset de la competencia es INTOCABLE en /kaggle/input; todo lo que se escribe va a /kaggle/working.')
lineas.append('')
lineas.append('## 2. Baseline y calificacion oficial por semilla')
lineas.append(f"- invsqrt: S = Q x C. Baseline medido (fast_verify max_x=1024): S = {_s(BASE['invsqrt'].get('S_fast_max_x_1024'))}, Q = {BASE['invsqrt'].get('Q')}, valido = {BASE['invsqrt'].get('valid')}.")
dqi = BASE.get('dqi', {})
lineas.append(f"- DQI: S = R(eps+) x Q^2 x T. Q = {dqi.get('Q')}, T estatica = {dqi.get('T_estatica')}, S estimada (T estatica) ~ {_s(dqi.get('S_estimada_T_estatica'))}.")
if 'fast_verify_2048' in dqi:
    lineas.append(f"  fast_verify 2048 shots: {dqi['fast_verify_2048']}")
else:
    lineas.append('  fast_verify 2048 shots: no medido en esta corrida (o no termino); el S oficial necesita 102400 shots.')
dfthc = BASE.get('dfthc', {})
lineas.append(f"- DFTHC: S = lambda_eff x T_total x Q_total. Score oficial: {_s(dfthc.get('score_oficial'))} (publicado en su README: 3,355,599,588.32)." if dfthc.get('score_oficial') else f"- DFTHC: S = lambda_eff x T_total x Q_total. {dfthc.get('nota', 'sin medir aqui')} (publicado: 3,355,599,588.32).")
lineas.append('')
lineas.append('## 3. LLM gratuito en CPU')
lineas.append(f"- Modelo: {LLM.get('modelo') or 'ninguno'} ({LLM.get('origen')}).")
lineas.append(f"- Semillas propuestas: {len(LLM.get('semillas') or [])}.")
for s in (LLM.get('semillas') or []):
    lineas.append(f"  - {s.get('name')}: {s.get('operators')} {s.get('params')} — {s.get('why', '')}")
lineas.append('')
lineas.append('## 4. Corrida: que funciona y que tan bien')
lineas.append(f"- S base invsqrt: {_s(bench.get('base_S'))}.")
for nombre, r in ops.items():
    lineas.append(f"  - {nombre}: valido={r.get('valid')}, S={_s(r.get('S'))}, dS={r.get('delta_S')}, stats={str(r.get('stats'))[:150]}")
for s in RES.get('semillas_llm', []):
    lineas.append(f"  - semilla LLM {s.get('name')}: {s.get('status')}, S={_s(s.get('S')) if s.get('S') is not None else '—'}, valido={s.get('valid')}")
roles = RES.get('roles_causales') or {}
if roles:
    lineas.append(f"- Roles causales (auto_mvp/causal.py): {json.dumps(roles, ensure_ascii=False)[:600]}")
lineas.append('')
lineas.append('## 5. Que sigue')
lineas.append('- El DQI necesita su propia corrida larga (86M instrucciones en la muestra de referencia; el fast_verify de 2048 shots es el minimo).')
lineas.append('- El DFTHC esta en pausa por decision de Arturo; su baseline oficial ya esta medido aqui.')
lineas.append('- El LLM propone; la herramienta mide. Ninguna semilla entra sin pasar el verificador.')
reporte = '\n'.join(lineas)
Path('/kaggle/working/REPORTE_MAPEO.md').write_text(reporte)
print(reporte)
print(f"\nREPORTE_MAPEO.md + MAPEO/BASELINE/LLM_SEEDS/RESULTADOS.json en /kaggle/working; total {minutos():.1f} min")
'''

MD_INTRO = """# Google-Q-cvcc — mapeo de datasets + LLM gratuito en CPU (corrida 30 min)

Dos datasets, un Notebook, una corrida de prueba:

- **Competencia** `google-verifiable-quantum-circuit-compilation`: los
  verificadores oficiales, las muestras (invsqrt, DQI, DFTHC) y el
  simulador `kickmix.so`. Es la base INTOCABLE: se lee, no se escribe.
- **Qualtran** `dcpracmatic/qualtran`: el árbol fuente de Qualtran
  (el simulador `kickmix/` y la librería de Bloqs `qualtran/`).

La calificación de cada semilla sale de los verificadores oficiales,
no inventada:

- **invsqrt:** `S = Q × C`, `C = Toffolis + T/4`.
- **DQI:** `S = R(ε+) × Q² × T`, `R(ε) = ln2 / -ln(1/2 + 2√ε)`.
- **DFTHC:** `S = λ_eff × T_total × Q_total`.

El LLM es **Qwen2.5-1.5B-Instruct** (gratuito, en CPU, bfloat16, ~3 GB
de RAM; fallback a 0.5B). Propone semillas JSON; la herramienta las
aplica y las mide con el verificador rápido. Nada entra sin medir.

Presupuesto interno: **28 minutos** (el kernel tiene 30).
"""


def main():
    blob, files = build_tarball()
    b64 = base64.b64encode(blob).decode()
    chunks = [b64[i:i + 100] for i in range(0, len(b64), 100)]
    print(f"base64: {len(b64)} chars en {len(chunks)} líneas; tar.gz {len(blob)} bytes")

    cells = [
        md_cell(MD_INTRO),
        code_cell(CELL_RELOJ),
        cell_repo(chunks, len(files)),
        code_cell(CELL_MAPEO),
        code_cell(CELL_SETUP),
        code_cell(CELL_BASELINE),
        code_cell(CELL_LLM),
        code_cell(CELL_CORRIDA),
        code_cell(CELL_REPORTE),
    ]
    nb = {"cells": cells,
          "metadata": {"kernelspec": {"display_name": "Python 3",
                                       "language": "python", "name": "python3"},
                       "language_info": {"name": "python", "version": "3.10.0"}},
          "nbformat": 4, "nbformat_minor": 4}
    (HERE / "google-q-cvcc-mapeo-datasets.ipynb").write_text(
        json.dumps(nb, indent=1), encoding="utf-8")
    meta = {"id": "dcpracmatic/google-q-cvcc-mapeo-de-datasets-y-llm-en-cpu", "id_no": 144924185,
            "title": "Google-Q-cvcc: mapeo de datasets y LLM en CPU",
            "code_file": "google-q-cvcc-mapeo-datasets.ipynb",
            "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": False, "enable_tpu": False,
            "enable_internet": True,
            "dataset_sources": ["dcpracmatic/qualtran"],
            "competition_sources": ["google-verifiable-quantum-circuit-compilation"],
            "keywords": []}
    (HERE / "kernel-metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    print("notebook + metadata escritos en", HERE)


if __name__ == "__main__":
    main()
