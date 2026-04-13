// UART Transmitter with 16-byte ring buffer (FIFO).
//
// Protocol (unchanged from the caller's point of view):
//   - Write a byte to `din` and pulse `wr` high for one cycle.
//   - Read `busy`: if high, the FIFO is full — do NOT pulse `wr`.
//                  if low, there's room for at least one more byte.
//
// Previously `busy` meant "a byte is being shifted out right now", which
// forced the CPU to spin after every single putchar. With the ring buffer
// the CPU can burst 16 bytes at full speed and only stall when the FIFO is
// actually full. At 12 MHz / 115200 baud that's ~1040 clocks per byte, so
// a 16-byte buffer absorbs ~17 ms of back-to-back writes.

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
    localparam FIFO_DEPTH   = 16;
    localparam FIFO_ABITS   = 4;   // log2(FIFO_DEPTH)

    // ---- Ring buffer ----
    reg [7:0]  fifo [0:FIFO_DEPTH-1];
    reg [FIFO_ABITS:0] head;   // one extra bit to distinguish full from empty
    reg [FIFO_ABITS:0] tail;

    wire fifo_empty = (head == tail);
    wire fifo_full  = (head[FIFO_ABITS-1:0] == tail[FIFO_ABITS-1:0])
                   && (head[FIFO_ABITS] != tail[FIFO_ABITS]);

    // `busy` now means "FIFO is full, can't accept another byte right now".
    // The CPU's existing busy-wait loop still works — it just rarely trips.
    assign busy = fifo_full;

    // ---- Shifter state (unchanged) ----
    reg [3:0]  bit_idx;
    reg [15:0] clk_cnt;
    reg [9:0]  shift;      // {stop, data[7:0], start}
    reg        active;

    // ---- FIFO push / shifter fetch / shift out ----
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx      <= 1'b1;
            active  <= 1'b0;
            clk_cnt <= 16'd0;
            bit_idx <= 4'd0;
            shift   <= 10'h3FF;
            head    <= 0;
            tail    <= 0;
            for (i = 0; i < FIFO_DEPTH; i = i + 1)
                fifo[i] <= 8'd0;
        end else begin
            // FIFO push (only if not full — callers should check busy first,
            // but if they ignore it we silently drop the byte).
            if (wr && !fifo_full) begin
                fifo[tail[FIFO_ABITS-1:0]] <= din;
                tail <= tail + 1'b1;
            end

            // Shifter: pull the next byte from the FIFO when idle.
            if (!active && !fifo_empty) begin
                shift   <= {1'b1, fifo[head[FIFO_ABITS-1:0]], 1'b0};
                head    <= head + 1'b1;
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
    end

endmodule
