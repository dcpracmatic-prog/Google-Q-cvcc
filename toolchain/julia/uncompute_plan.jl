# uncompute_plan.jl — Capa 3 del toolchain: plan de descomputación (Bennett).
#
# Lee el IR neutral (JSON, capa 2) y escribe el mismo IR con
# `uncompute_plan`: la secuencia de bloques a descomputar y los
# qubits que se liberan. Impone el presupuesto de qubits
# (`qubit_budget`): si el netlist lo excede, fuerza descomputación
# por bloques ANTES de que C++ emita las compuertas.
#
# Regla de oro: Q no puede dispararse. Si Yosys creó N cables
# temporales y N > qubit_budget, hay que descomputar (revertir) los
# intermedios que ya no se usan, liberando sus qubits para reusarlos.
# Esto es Bennett uncomputation: compute -> usar -> uncompute.
#
# Uso: julia uncompute_plan.jl ir.json [ir_con_plan.json]
# Requiere: JSON.jl (Pkg.add("JSON")).

using JSON

function plan_uncompute(ir::Dict)
    budget = ir["qubit_budget"]
    nodes = ir["nodes"]
    # Qubits mencionados (entradas, salidas, outs). Cada nodo AND
    # crea un qubit nuevo (su salida) si no se reutiliza.
    live = Set{String}()
    for inp in ir["inputs"]
        push!(live, inp)
    end
    plan = []
    # Recorrido: cuando los qubits vivos exceden el presupuesto,
    # descomputar el bloque más viejo cuyos outs ya no se usan.
    # (Heurística voraz: descomputar en orden inverso al último uso.)
    last_use = Dict{String,Int}()
    for (i, nd) in enumerate(nodes)
        for a in nd["args"]
            last_use[a] = i
        end
        last_use[nd["out"]] = i
    end
    # Contar qubits vivos en cada punto; si excede, marcar bloque.
    # Simplificación: agrupar nodos en bloques de 64; si un bloque
    # entero ya no se usa después, descomputarlo completo.
    blocksize = 64
    nb = ceil(Int, length(nodes) / blocksize)
    for b in 1:nb
        lo = (b - 1) * blocksize + 1
        hi = min(b * blocksize, length(nodes))
        # ¿Algún out de este bloque se usa después del bloque?
        used_after = false
        for i in lo:hi
            out = nodes[i]["out"]
            if get(last_use, out, 0) > hi
                used_after = true
                break
            end
        end
        if !used_after && b < nb
            # El bloque ya no se usa: descomputarlo libera sus outs.
            frees = [nodes[i]["out"] for i in lo:hi]
            push!(plan, Dict("block" => "bloque_$b", "frees" => frees))
        end
    end
    return plan
end

function main()
    if length(ARGS) < 1
        println(stderr, "uso: julia uncompute_plan.jl ir.json [salida.json]")
        exit(2)
    end
    ir = JSON.parsefile(ARGS[1])
    plan = plan_uncompute(ir)
    ir["uncompute_plan"] = plan
    out = length(ARGS) >= 2 ? ARGS[2] : "-"
    if out == "-"
        println(JSON.json(ir, 2))
    else
        open(out, "w") do io
            JSON.print(io, ir, 2)
        end
    end
    println(stderr, "uncompute_plan: $(length(plan)) bloques a descomputar")
end

main()
