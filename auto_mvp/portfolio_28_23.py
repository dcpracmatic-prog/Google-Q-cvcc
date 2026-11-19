"""La base 28.23 para el LLM: ingeniería inversa del portfolio.

El portfolio de kernel repro-qcc-28-23163-verify (GM 28.23163,
verificado con los verificadores oficiales en Kaggle y en sandbox)
es la mejor submission medida. Esta es la base que se le da al LLM
como punto de partida: ya no genera desde cero, mejora ESTO.

Datos medidos (verificadores oficiales):
- invsqrt (maoxin123): S=74,405.67, Q=44, T=1,451.44, ratio 27.91x
- DQI (super-merged, 4 autores): S=345,256,821,434, Q=890,
  T=365,894.2, ratio 70.79x, 0 errores a 102,400 shots
- química (leotang09): S=294,642,170.57, Q=427, T=14,706,
  lambda_eff=46.92, ratio 11.39x
- GM = 28.23163. Meta: GM > 32 (necesita +46% en el producto de
  las tres mejoras).

Lo que YA se midió que NO funciona (no proponerlo de nuevo):
- Limpieza exacta (peephole, rotation_merge, commuting, fanout, SA):
  0 Toffoli en las 3 tareas. Agotada.
- Toom-3 en el DQI: empeora (45 Toffolis por producto vs 42 del
  kernel Mastrovito actual; GM baja a ~27.99).
- Toom-4: empata en 42 y pide 12 ancillas más (Q sube, S sube).
- Química J=6, J=10, J=3: peores que J=5. brot: cerrado.
- invsqrt: quitar cualquier rotación rompe el PASS.

Los puntos a mejorar (medidos, con el número que hace falta):
- DQI: bajar T (multiplicador < 42 Toffolis por producto) o bajar Q
  (890 -> menos qubits). El multiplicador actual es un kernel
  Mastrovito de 42 Toffolis, probado 12/12. 3,136 kernels en total.
- invsqrt: bajar Q de 44 a 43, o bajar Toffolis de 1,517. La vía
  prometedora es un polinomio minimax mejor (síntesis en Julia).
- química: bajar Lambda de 283.14 a ~229 (reentrenar U, W) o bajar T.
  Lambda es la palanca grande: 283 -> 229 da GM ~30.29 solo.
"""

from __future__ import annotations

from typing import Any

# Medido con los verificadores oficiales (kernel repro-qcc-28-23163).
PORTFOLIO_28_23: dict[str, Any] = {
    "gm": 28.23163018384455,
    "meta_gm": 32.0,
    "invsqrt": {
        "autor": "maoxin123",
        "S": 74405.67,
        "Q": 44,
        "T_toffoli_mean": 1451.44,
        "ratio": 27.91150,
        "ccx": 1517,
        "ccz": 32,
        "hmr": 1266,
        "cx": 12333,
        "swap": 11,
        "worst_error_over_tolerance": 0.99946,
        "estructura": (
            "x en [1, 3133452], registro x de 22 qubits, normaliza a "
            "[1,4), QROM cúbico minimax para y0, un paso Newton, "
            "41 rotaciones Z_POW finas en escalera diádica, reuso "
            "agresivo de scratch con HMR."
        ),
        "puntos_a_mejorar": [
            "Bajar Q de 44 a 43 qubits.",
            "Bajar Toffolis de 1,517 (CCX) con un polinomio minimax "
            "mejor (síntesis en Julia, grado y segmentos).",
            "NO quitar rotaciones: rompe el PASS.",
        ],
    },
    "dqi": {
        "autor": "super-merged (Balram Srinivasan, Grant Prater, "
                 "Boristown, ManWithACat)",
        "S": 345256821434.0,
        "Q": 890,
        "T_toffoli_mean": 365894.2,
        "ratio": 70.78633,
        "ccx_total": 349415,
        "multiplicador_toffoli": 42,
        "num_kernels": 3136,
        "errores_valor_102400": 0,
        "errores_fase_102400": 0,
        "estructura": (
            "m=4095, n=70, GF(2^12). Decodifica in situ sobre S "
            "(840 qubits), sin reg_b. Intermedios en bits clásicos. "
            "Reciclaje MBUC extremo (HMR). Solo 82 inversiones "
            "compartidas. 11 fases: mask_projection -> initial -> "
            "extract -> synthesis -> convert -> scan -> unconvert -> "
            "padded_unsynthesis -> unextract -> uninitial -> "
            "restore_masks. El multiplicador es un kernel Mastrovito "
            "de 42 Toffolis por producto, probado 12/12."
        ),
        "puntos_a_mejorar": [
            "Bajar T: un multiplicador con MENOS de 42 Toffolis por "
            "producto (Toom-3 cuesta 45 y empeora; Toom-4 empata).",
            "Bajar Q de 890 (quitar ancillas o reciclar más).",
            "Chien sin inversión por posición; espejos del EEA.",
            "NO limpieza exacta: ya midió 0.",
        ],
    },
    "quimica": {
        "autor": "leotang09",
        "S": 294642170.57,
        "Q": 427,
        "T": 14706,
        "lambda_eff": 46.92,
        "Lambda": 283.14,
        "ratio": 11.38873,
        "brot": 8,
        "J": 5,
        "num_circuitos": 15,
        "error_2_mHa": 20.0,
        "estructura": (
            "FeMoCo N=76, factorización DFTHC (R,B,C,N)=(9,143,40,76), "
            "1,363 angle_words, brot=8, keep_bits=10, J=5, 15 "
            "circuitos, Lambda=283.14, lambda_eff=46.92, "
            "error_2=20 mHa (al límite)."
        ),
        "puntos_a_mejorar": [
            "Bajar Lambda de 283.14 a ~229 reentrenando U, W "
            "(la palanca grande: solo eso da GM ~30.29).",
            "Bajar T de 14,706.",
            "J=5 es el óptimo (J=6, J=10, J=3 peores). brot cerrado.",
        ],
    },
}

# Lo ya medido que NO funciona (el LLM no debe proponerlo de nuevo).
NO_REINTENTAR = [
    "Limpieza exacta en cualquier tarea (peephole, rotation_merge, "
    "commuting, fanout, SA): 0 Toffoli, agotada.",
    "Toom-3 en el DQI (45 > 42, empeora a GM ~27.99).",
    "Toom-4 en el DQI (empata en 42, +12 ancillas, Q sube).",
    "Química J=6, J=10, J=3 (peores que J=5).",
    "Quitar rotaciones en invsqrt (rompe el PASS).",
]


def prompt_mejorar_portfolio(tarea: str) -> str:
    """El prompt del LLM para mejorar UNA tarea del portfolio 28.23.

    Le da la base medida (la ingeniería inversa) y los puntos a
    mejorar, y le pide UNA propuesta concreta y construible: no
    knobs abstractos, sino el cambio exacto (código o parámetros)
    que la herramienta puede construir y verificar.
    """
    if tarea not in ("invsqrt", "dqi", "quimica"):
        raise ValueError(f"tarea debe ser invsqrt, dqi o quimica, got {tarea!r}")
    base = PORTFOLIO_28_23[tarea]
    no_reintentar = "\n".join(f"- {x}" for x in NO_REINTENTAR)
    puntos = "\n".join(f"- {x}" for x in base["puntos_a_mejorar"])
    return (
        "Eres el estratega de un optimizador de circuitos cuánticos. "
        "Responde SOLO con un JSON, sin texto fuera del JSON.\n\n"
        f"Tarea: {tarea}. La mejor submission medida es el portfolio "
        f"GM 28.23163. Tu trabajo es MEJORAR esta tarea, no generar "
        "una nueva desde cero. La base es la siguiente (medida con "
        "los verificadores oficiales):\n\n"
        f"S={base['S']}, Q={base['Q']}, "
        f"estructura: {base['estructura']}\n\n"
        "Puntos a mejorar (medidos, con el número que hace falta):\n"
        f"{puntos}\n\n"
        "Lo ya medido que NO funciona (no lo propongas de nuevo):\n"
        f"{no_reintentar}\n\n"
        "Propón UNA mejora concreta como JSON: "
        '{"propuesta": "<qué cambiar, exacto>", '
        '"codigo": "<el código Python que construye el cambio, '
        'completo y autocontenido>", '
        '"razon": "<por qué baja S, con el número estimado>"}.\n'
        "El código debe ser construible por la herramienta y "
        "verificable con el verificador oficial. Si no baja S, no "
        "vale. No propongas limpieza exacta ni Toom-3."
    )
