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

## Resultado medido — multiplicador GF(2^12) (2026-11-19)
- Yosys 0.48+5 (OSS CAD Suite, precompilado) + ABC `-g AND` sobre
  `verilog/gf212_mul.v` (schoolbook + reducción mod 0x1053):
  **144 ANDs** (309 nodos en el IR, budget Q=892).
- 144 es el conteo schoolbook (12x12 productos parciales). ABC no
  lo baja: los 144 ANDs son independientes.
- **No mejora**: el kernel Mastrovito actual del DQI cuesta 42
  Toffolis por producto. 144 > 42. El Verilog ingenuo no le gana
  a un kernel hecho a mano para este campo.
- La vía para bajar de 42 es otra: escribir el Verilog con
  estructura Mastrovito/Karatsuba (no schoolbook), o usar Yosys
  para OTROS bloques (EEA, comparadores) donde no hay un kernel
  hecho a mano. El pipeline (Verilog->Yosys->IR->C++->.kmx) ya
  funciona de punta a punta; lo que falta es el bloque que sí
  mejore.
- Yosys vive en `~/workspace/sandbox-run/yosys/` (precompilado).

## Resultado medido — multiplicador Karatsuba (creación desde 0, 2026-11-19)
- `verilog/gf212_mul_karatsuba.v` (Karatsuba 6+6, 3 mults de 6 bits
  + reducción mod 0x1053): verificado 500/500 contra gf212.py.
- Yosys/ABC `-g AND`: **108 ANDs** (227 nodos en el IR, 108 CCX
  en el .kmx emitido por C++). Pipeline completo funciona.
- 108 = 3x36 (las 3 mults de 6 bits en schoolbook). Mejor que el
  schoolbook 144, pero peor que el Mastrovito 42 del DQI.
- Conclusión: la creación con Yosys sí produce un multiplicador
  nuevo y correcto, pero la síntesis genérica no descubre la
  estructura profunda (PolyMul(6)=17, Mastrovito 42) que ya trae
  el kernel hecho a mano. Para bajar de 42 hace falta el circuito
  optimizado específico, no solo otra estructura en Verilog.
