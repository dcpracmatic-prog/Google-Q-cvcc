# Toolchain multilenguaje — Quantum EDA (Verilog + JSON + Julia + C++ + Python)

Cadena de compilación cuántica de alto nivel. Cada lenguaje hace lo
que mejor hace; ninguno procesa todo solo.

## Las 5 capas

```
Verilog ──► Yosys/ABC ──► JSON IR ──► Julia ──► C++ ──► Python
  (RTL)      (síntesis)    (bus)    (ancillas)  (.kmx)  (verificar)
```

| Capa | Lenguaje | Rol | Salida |
|------|----------|-----|--------|
| 1 | Verilog | Especificación RTL de la aritmética (GF(2^12), EEA, comparadores) | `verilog/*.v` |
| 1b | Yosys/ABC | Síntesis lógica: minimiza compuertas AND | netlist JSON |
| 2 | JSON | IR neutral: grafo AND/XOR + presupuesto de qubits | `ir/*.json` (ver `ir/schema.json`) |
| 3 | Julia | Ajuste simbólico (polinomios minimax) y plan de descomputación (Bennett) | IR con `uncompute_plan` |
| 4 | C++ (-O3) | Emisor rápido: IR -> .kmx linealizado (XOR->CX, AND->CCX) | `cpp/ir_to_kmx` |
| 5 | Python | Arnés Kickmix: carga el .kmx, verifica con el verificador oficial | PASS / S medido |

## La regla de oro (Q^2)

El mayor riesgo es que Yosys cree cables temporales ilimitados y Q
se dispare (de 890 a >2,000), arruinando S = R·Q²·T. Por eso:

- **Julia (capa 3) impone el presupuesto**: `qubit_budget` en el IR
  (ej. Q ≤ 892 para el DQI). Si el netlist lo excede, Julia fuerza
  descomputación por bloques (Bennett) ANTES de que C++ emita.
- **C++ (capa 4) no crea qubits**: solo linealiza lo que el IR trae.
  Si el IR excede el presupuesto, falla en vez de emitir.

## Estado (2026-11-19)

- Capa 1: `verilog/gf212_mul.v` — multiplicador GF(2^12) mod 0x1053,
  verificado 500/500 contra `auto_mvp/gf212.py`. Pendiente: correr
  Yosys/ABC y contar AND (meta: < 42 Toffolis por producto, que es
  el kernel Mastrovito actual del DQI).
- Capa 2: `ir/schema.json` — esquema del IR (nodos AND/XOR/NOT,
  qubit_budget, uncompute_plan).
- Capa 3: Julia — la síntesis de polinomios minimax para invsqrt se
  construye en otro chat (herramienta Julia, algoritmo de Remez).
  Aquí solo vive la interfaz (el IR que Julia lee y escribe).
- Capa 4: `cpp/ir_to_kmx.cpp` — compila con g++ -O3, probado:
  AND->CCX, XOR->CX. Sin dependencias externas.
- Capa 5: Python — el repo ya la tiene (`auto_mvp/circuit.py`,
  verificadores oficiales en `auto_mvp/circuits/verifiers/`).

## La base 28.23 para el LLM

El LLM ya no genera desde cero. `auto_mvp/portfolio_28_23.py` le da
la base medida (ingeniería inversa del portfolio GM 28.23163) con
los puntos a mejorar por tarea y lo ya medido que no funciona
(Toom-3, limpieza exacta, J≠5). Ver `prompt_mejorar_portfolio(tarea)`.
