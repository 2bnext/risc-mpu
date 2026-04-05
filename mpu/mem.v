// Memory module using iCE40UP5K SPRAM
// One SPRAM block, 16-bit wide, 16K deep (32KB).
// Reads/writes 16-bit words. 32-bit access done as two halves externally.

module mem (
    input  wire        clk,
    input  wire        rd,
    input  wire        wr,
    input  wire [31:0] addr,
    input  wire [31:0] wdata,
    output wire [31:0] rdata,
    output reg         ready
);

    // Two reads per 32-bit access would complicate things.
    // Instead: use two SPRAM blocks but with only one 16K address space (32KB).
    wire [13:0] spram_addr = addr[15:2];
    wire [15:0] rdata_lo, rdata_hi;

    SB_SPRAM256KA spram_lo (
        .ADDRESS    (spram_addr),
        .DATAIN     (wdata[15:0]),
        .MASKWREN   (4'b1111),
        .WREN       (wr),
        .CHIPSELECT (1'b1),
        .CLOCK      (clk),
        .STANDBY    (1'b0),
        .SLEEP      (1'b0),
        .POWEROFF   (1'b1),
        .DATAOUT    (rdata_lo)
    );

    SB_SPRAM256KA spram_hi (
        .ADDRESS    (spram_addr),
        .DATAIN     (wdata[31:16]),
        .MASKWREN   (4'b1111),
        .WREN       (wr),
        .CHIPSELECT (1'b1),
        .CLOCK      (clk),
        .STANDBY    (1'b0),
        .SLEEP      (1'b0),
        .POWEROFF   (1'b1),
        .DATAOUT    (rdata_hi)
    );

    assign rdata = {rdata_hi, rdata_lo};

    always @(posedge clk)
        ready <= rd | wr;

endmodule
