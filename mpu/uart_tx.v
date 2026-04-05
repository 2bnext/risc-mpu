// UART Transmitter – 8N1, active-high busy flag.
// Write a byte to `din` and pulse `wr` for one cycle.
// `busy` is high while a byte is being shifted out.

module uart_tx #(
    parameter CLK_FREQ = 12_000_000,
    parameter BAUD     = 115_200
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] din,
    input  wire       wr,
    output reg        tx,
    output wire       busy
);

    localparam CLKS_PER_BIT = CLK_FREQ / BAUD;

    reg [3:0]  bit_idx;
    reg [15:0] clk_cnt;
    reg [9:0]  shift;  // {stop, data[7:0], start}
    reg        active;

    assign busy = active;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx      <= 1'b1;
            active  <= 1'b0;
            clk_cnt <= 16'd0;
            bit_idx <= 4'd0;
            shift   <= 10'h3FF;
        end else if (!active && wr) begin
            shift   <= {1'b1, din, 1'b0};  // stop + data + start
            active  <= 1'b1;
            bit_idx <= 4'd0;
            clk_cnt <= 16'd0;
            tx      <= 1'b0;               // start bit
        end else if (active) begin
            if (clk_cnt == CLKS_PER_BIT - 1) begin
                clk_cnt <= 16'd0;
                if (bit_idx == 4'd9) begin
                    active <= 1'b0;
                    tx     <= 1'b1;
                end else begin
                    bit_idx <= bit_idx + 4'd1;
                    tx      <= shift[bit_idx + 1];
                end
            end else begin
                clk_cnt <= clk_cnt + 16'd1;
            end
        end
    end

endmodule
