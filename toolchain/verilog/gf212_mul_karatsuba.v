// gf212_mul_karatsuba.v — Multiplicador GF(2^12) mod 0x1053, estructura Karatsuba.
//
// CREACIÓN desde cero con el toolchain (no optimización del kernel
// existente). Estructura Karatsuba documentada en auto_mvp/circuits/
// generators/mult51.py (paper 2510.10967):
//   a = a1*x^6 + a0, b = b1*x^6 + b0  (mitades de 6 bits)
//   P0 = a0*b0, P1 = a1*b1, P2 = (a0+a1)*(b0+b1)  (3 mults de 6 bits)
//   producto = P0 + (P2-P0-P1)*x^6 + P1*x^12, luego reducir mod 0x1053.
// La reducción y el combinado son lineales (solo XOR). Los ANDs
// están solo en las 3 multiplicaciones de 6 bits. Yosys/ABC las
// optimiza; la referencia cuántica usa PolyMul(6)=17T (3x17=51T).
// Aquí se crean en Verilog y Yosys mide el AND real.

module gf212_mul_karatsuba(
    input  wire [11:0] a,
    input  wire [11:0] b,
    output wire [11:0] c
);
    wire [5:0] a0 = a[5:0];
    wire [5:0] a1 = a[11:6];
    wire [5:0] b0 = b[5:0];
    wire [5:0] b1 = b[11:6];
    wire [5:0] a01 = a0 ^ a1;
    wire [5:0] b01 = b0 ^ b1;

    // Tres multiplicaciones polinómicas de 6 bits (grado <= 10).
    wire [10:0] p0 = poly_mul6(a0, b0);
    wire [10:0] p1 = poly_mul6(a1, b1);
    wire [10:0] p2 = poly_mul6(a01, b01);

    // Término medio Karatsuba: P2 - P0 - P1 = P2 ^ P0 ^ P1 (car. 2).
    wire [10:0] mid = p2 ^ p0 ^ p1;

    // Producto completo (grado <= 22): P0 + mid*x^6 + P1*x^12.
    reg [22:0] p;
    integer i;
    always @* begin
        p = 23'b0;
        p[10:0]  = p[10:0]  ^ p0;
        p[16:6]  = p[16:6]  ^ mid;
        p[22:12] = p[22:12] ^ p1;
        // Reducción mod x^12+x^6+x^4+x+1 (0x1053), de arriba abajo.
        for (i = 22; i >= 12; i = i - 1)
            if (p[i]) begin
                p[i]    = 1'b0;
                p[i-6]  = p[i-6]  ^ 1'b1;
                p[i-8]  = p[i-8]  ^ 1'b1;
                p[i-11] = p[i-11] ^ 1'b1;
                p[i-12] = p[i-12] ^ 1'b1;
            end
    end
    assign c = p[11:0];

    // Multiplicación polinómica de 6 bits (schoolbook; Yosys optimiza).
    function [10:0] poly_mul6;
        input [5:0] x;
        input [5:0] y;
        integer i, j;
        begin
            poly_mul6 = 11'b0;
            for (i = 0; i < 6; i = i + 1)
                for (j = 0; j < 6; j = j + 1)
                    poly_mul6[i+j] = poly_mul6[i+j] ^ (x[i] & y[j]);
        end
    endfunction
endmodule
