// gf212_mul.v — Multiplicador GF(2^12) mod 0x1053 (x^12+x^6+x^4+x+1).
//
// Capa 1 del toolchain (Verilog -> Yosys/ABC -> JSON IR).
// El DQI multiplica en GF(2^12) miles de veces. El kernel actual
// (Mastrovito) cuesta 42 Toffolis por producto. Si Yosys/ABC encuentra
// una red con menos compuertas AND, eso es menos Toffolis directo:
// XOR -> CX (0 Toffoli), AND -> CCX (1 Toffoli).
//
// La reducción mod 0x1053: el bit i (>=12) del producto se reduce
// xoreando (0x1053 << (i-12)). El polinomio es irreducible y el
// elemento primitivo es alpha=2 (igual que en auto_mvp/gf212.py).
//
// REGLA DE ORO: Yosys puede crear cables temporales ilimitados. El
// presupuesto de qubits (Q) lo impone Julia (capa 3) en el IR, no
// aquí. Este módulo es solo la especificación aritmética.

module gf212_mul(
    input  wire [11:0] a,
    input  wire [11:0] b,
    output wire [11:0] c
);
    // Producto polinómico completo (grado hasta 22): 23 bits.
    reg [22:0] p;
    integer i, j;
    always @* begin
        p = 23'b0;
        for (i = 0; i < 12; i = i + 1)
            for (j = 0; j < 12; j = j + 1)
                p[i+j] = p[i+j] ^ (a[i] & b[j]);
        // Reducción mod x^12+x^6+x^4+x+1 (0x1053), de arriba abajo.
        for (i = 22; i >= 12; i = i - 1)
            if (p[i]) begin
                p[i]     = 1'b0;
                p[i-6]   = p[i-6]   ^ 1'b1;
                p[i-8]   = p[i-8]   ^ 1'b1;
                p[i-11]  = p[i-11]  ^ 1'b1;
                p[i-12]  = p[i-12]  ^ 1'b1;
            end
    end
    assign c = p[11:0];
endmodule
