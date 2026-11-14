# Notebook de mapeo de datasets + LLM en CPU (Kaggle)

Mapea los dos datasets (competencia `google-verifiable-quantum-circuit-compilation`
y `dcpracmatic/qualtran`), mide el baseline oficial de las tres tareas
(invsqrt, DQI, DFTHC) con los verificadores, propone semillas con un LLM
gratuito en CPU (Qwen 2.5 1.5B) y corre el benchmark de la herramienta
sobre la muestra invsqrt. Todo en un Notebook de Kaggle, en ~5 min.

## Archivos

- `build_notebook.py` — construye el `.ipynb` desde el repo (snapshot en
  base64, sin `runs/`, `build/`, `notes/`, `tests/` ni `kaggle-notebooks/`).
- `google-q-cvcc-mapeo-datasets.ipynb` — el Notebook listo para subir.
- `kernel-metadata.json` — id/título del kernel en Kaggle.
- `push_notebook.py` — sube el Notebook a Kaggle (API de kernels).
- `watch.py` — vigila la corrida y baja las salidas.

## Uso

```bash
python3 build_notebook.py   # reconstruye el .ipynb
python3 push_notebook.py .  # lo sube a Kaggle
python3 watch.py            # espera a que termine y baja el zip
```

## Resultado medido (v16, 2026-11-13, 4,9 min)

- invsqrt: S = 2.068.518,26, Q = 260, válido.
- DQI (referencia): Q = 1893, T = 5.725.461, fast_verify 2048 válido,
  S = 154.025.541.234.591,47, R = 7,5077, ε+ = 0,0424, 0 errores.
- DFTHC: verificador oficial PASS, score = 3.355.599.588,32 (el publicado).
- LLM Qwen 1.5B en CPU: 3 semillas; seed1 y seed2 medidas y válidas.
- Benchmark invsqrt: peephole 4, commuting 4.216, rotation_merge 0,
  fanout 0, SA saltado (circuito demasiado grande para 30 min).

Kernel: https://www.kaggle.com/code/dcpracmatic/google-q-cvcc-mapeo-de-datasets-y-llm-en-cpu
