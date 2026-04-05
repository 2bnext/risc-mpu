// UART Receiver – 8N1

module uart_rx #(
    parameter CLK_FREQ = 12_000_000,
    parameter BAUD     = 115_200
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx,
    output reg  [7:0] dout,
    output reg        valid
);

    localparam CLKS_PER_BIT = CLK_FREQ / BAUD;

    reg       rx_r, rx_rr;          // double-sync
    reg [3:0] bit_idx;
    reg [15:0] clk_cnt;
    reg [7:0] shift;

    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_DATA  = 2'd2;
    localparam S_STOP  = 2'd3;

    reg [1:0] state;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_r  <= 1'b1;
            rx_rr <= 1'b1;
        end else begin
            rx_r  <= rx;
            rx_rr <= rx_r;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= S_IDLE;
            valid   <= 1'b0;
            dout    <= 8'd0;
            clk_cnt <= 16'd0;
            bit_idx <= 4'd0;
            shift   <= 8'd0;
        end else begin
            valid <= 1'b0;

            case (state)
                S_IDLE: begin
                    if (!rx_rr) begin
                        // Falling edge — start bit detected
                        clk_cnt <= 16'd0;
                        state   <= S_START;
                    end
                end

                S_START: begin
                    // Wait until mid-start-bit to verify
                    if (clk_cnt == (CLKS_PER_BIT / 2) - 1) begin
                        if (!rx_rr) begin
                            // Still low — valid start bit
                            clk_cnt <= 16'd0;
                            bit_idx <= 4'd0;
                            state   <= S_DATA;
                        end else begin
                            // Glitch — back to idle
                            state <= S_IDLE;
                        end
                    end else begin
                        clk_cnt <= clk_cnt + 16'd1;
                    end
                end

                S_DATA: begin
                    // Wait one full bit period, sample at center
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        clk_cnt <= 16'd0;
                        shift[bit_idx] <= rx_rr;
                        if (bit_idx == 4'd7) begin
                            state <= S_STOP;
                        end else begin
                            bit_idx <= bit_idx + 4'd1;
                        end
                    end else begin
                        clk_cnt <= clk_cnt + 16'd1;
                    end
                end

                S_STOP: begin
                    // Wait for mid-stop-bit
                    if (clk_cnt == CLKS_PER_BIT - 1) begin
                        dout  <= shift;
                        valid <= 1'b1;
                        state <= S_IDLE;
                    end else begin
                        clk_cnt <= clk_cnt + 16'd1;
                    end
                end
            endcase
        end
    end

endmodule
