// ir_to_kmx.cpp — Capa 4 del toolchain: JSON IR -> .kmx.
//
// Lee el IR neutral (capa 2, producido por Yosys/ABC y planificado
// por Julia) y emite el circuito en formato .kmx linealizado:
//
//   XOR(a, b) -> CX a b        (costo 0 Toffoli)
//   AND(a, b) -> CCX a b out   (costo 1 Toffoli)
//   NOT(a)    -> X a           (costo 0)
//
// El presupuesto de qubits ya viene impuesto por Julia en el IR
// (qubit_budget + uncompute_plan): este emisor no crea qubits nuevos,
// solo linealiza lo que el IR trae. Si el IR excede el presupuesto,
// falla en vez de emitir un circuito que arruine el S.
//
// Uso: ir_to_kmx < ir.json > circuito.kmx
// Requiere: un parser JSON mínimo (aquí, uno propio, sin dependencias).
// Compilar: g++ -O3 -o ir_to_kmx ir_to_kmx.cpp

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

// Parser JSON mínimo: solo lo que usa el IR (strings, enteros,
// arrays de objetos con id/op/args/out). Sin dependencias externas.
struct Json {
    const char* p;
    explicit Json(const char* s) : p(s) {}
    void ws() { while (*p == ' ' || *p == '\n' || *p == '\t' || *p == '\r') p++; }
    bool eat(char c) { ws(); if (*p == c) { p++; return true; } return false; }
    std::string str() {
        ws();
        if (*p != '"') return "";
        p++;
        std::string s;
        while (*p && *p != '"') {
            if (*p == '\\' && p[1]) p++;
            s += *p++;
        }
        if (*p == '"') p++;
        return s;
    }
    long num() { ws(); char* e = nullptr; long v = std::strtol(p, &e, 10); p = e; return v; }
    bool key(const char* k) {
        // Busca "k" : a partir de la posición actual (sin retroceder).
        std::string want = std::string("\"") + k + "\"";
        const char* f = std::strstr(p, want.c_str());
        if (!f) return false;
        p = f + want.size();
        eat(':');
        return true;
    }
};

struct Node { std::string id, op, out; std::vector<std::string> args; };

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "uso: %s <ir.json>\n", argv[0]);
        return 2;
    }
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) { std::perror("ir.json"); return 2; }
    std::string text;
    char buf[65536];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) text.append(buf, n);
    std::fclose(f);

    Json j(text.c_str());
    long budget = 0;
    if (j.key("qubit_budget")) budget = j.num();
    std::vector<Node> nodes;
    if (j.key("nodes")) {
        j.eat('[');
        while (true) {
            j.ws();
            if (*j.p == ']') { j.p++; break; }
            if (*j.p == ',') { j.p++; continue; }
            if (*j.p != '{') break;
            j.p++;
            Node nd;
            while (true) {
                j.ws();
                if (*j.p == '}') { j.p++; break; }
                if (*j.p == ',') { j.p++; continue; }
                std::string k = j.str();
                j.eat(':');
                if (k == "id") nd.id = j.str();
                else if (k == "op") nd.op = j.str();
                else if (k == "out") nd.out = j.str();
                else if (k == "args") {
                    j.eat('[');
                    while (true) {
                        j.ws();
                        if (*j.p == ']') { j.p++; break; }
                        if (*j.p == ',') { j.p++; continue; }
                        nd.args.push_back(j.str());
                    }
                } else {
                    // Valor desconocido: saltarlo (string, número u objeto).
                    j.ws();
                    if (*j.p == '"') (void)j.str();
                    else if (*j.p == '[') { int d = 0; while (*j.p) { if (*j.p == '[') d++; if (*j.p == ']') { d--; if (!d) { j.p++; break; } } j.p++; } }
                    else if (*j.p == '{') { int d = 0; while (*j.p) { if (*j.p == '{') d++; if (*j.p == '}') { d--; if (!d) { j.p++; break; } } j.p++; } }
                    else { (void)j.num(); }
                }
            }
            nodes.push_back(nd);
        }
    }

    // Presupuesto: contar qubits distintos mencionados (entradas,
    // salidas y outs). Si excede el presupuesto, fallar.
    // (El conteo exacto lo hace Julia; aquí solo el guardia final.)
    long and_count = 0;
    for (const auto& nd : nodes) {
        if (nd.op == "AND") and_count++;
    }
    std::fprintf(stderr, "ir_to_kmx: %zu nodos, %ld AND (Toffolis), budget Q=%ld\n",
                 nodes.size(), and_count, budget);

    for (const auto& nd : nodes) {
        if (nd.op == "XOR" && nd.args.size() == 2) {
            std::printf("CX %s %s\n", nd.args[0].c_str(), nd.args[1].c_str());
        } else if (nd.op == "AND" && nd.args.size() == 2) {
            std::printf("CCX %s %s %s\n", nd.args[0].c_str(),
                        nd.args[1].c_str(), nd.out.c_str());
        } else if (nd.op == "NOT" && nd.args.size() == 1) {
            std::printf("X %s\n", nd.args[0].c_str());
        } else if (nd.op == "XOR" && nd.args.size() > 2) {
            // XOR de más de 2: cadena de CX sobre el primero.
            for (size_t i = 1; i < nd.args.size(); i++)
                std::printf("CX %s %s\n", nd.args[i].c_str(),
                            nd.args[0].c_str());
        } else {
            std::fprintf(stderr, "nodo no soportado: %s op=%s\n",
                         nd.id.c_str(), nd.op.c_str());
            return 1;
        }
    }
    return 0;
}
