// Memory module using iCE40UP5K SPRAM
// One SPRAM block, 16-bit wide, 16K deep (32KB).
// Reads/writes 16-bit words. 32-bit access done as two halves externally.

module mem (
    input  wire        clk,
    input  wire        rd,
    input  wire        wr,
    input  wire [31:0] addr,
    input  wire [31:0] wdata,
    input  wire [3:0]  mask_lo,    // per-nibble write enable for low half
    input  wire [3:0]  mask_hi,    // per-nibble write enable for high half
    output wire [31:0] rdata,
    output reg         ready
);

    // Two SPRAM blocks in parallel, one address space, 32-bit data.
    // Byte/halfword stores are realised via per-nibble MASKWREN inputs;
    // the caller is responsible for shifting wdata into the right lane.
    wire [13:0] spram_addr = addr[15:2];
    wire [15:0] rdata_lo, rdata_hi;

    SB_SPRAM256KA spram_lo (
        .ADDRESS    (spram_addr),
        .DATAIN     (wdata[15:0]),
        .MASKWREN   (mask_lo),
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
        .MASKWREN   (mask_hi),
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
