// First-order sigma-delta ADC built from one digital input, one digital
// output, two equal resistors and a small capacitor. The comparator is
// the FPGA's input buffer (threshold ≈ Vcc/2).
//
//   adc_in_pin  ───┐                       ┌── analog Vin
//                  │                       │
//                  R2                      R1
//                  │                       │
//      ┌───────────┴───────────────────────┘
//      │
//      C  (a few nF, to GND)
//      │
//      ▼ GND
//
// The FPGA drives `adc_out = ~adc_in` so the feedback loop holds the
// summing node near the input threshold. With R1 == R2 the average
// duty cycle of adc_in equals Vin/Vcc, so counting the number of 1s in
// a fixed window yields a digital code proportional to Vin.
//
// Window: 4096 clocks at 12 MHz = ~340 µs per sample, ~2.9 kSPS,
// 12-bit resolution. The result register holds the last completed
// conversion and is updated continuously.
//
module sigma_delta_adc (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        adc_in,
    output wire        adc_out,
    output reg  [11:0] result
);
    // Two-stage synchroniser for the asynchronous comparator output.
    reg adc_in_r, adc_in_rr;
    always @(posedge clk) begin
        adc_in_r  <= adc_in;
        adc_in_rr <= adc_in_r;
    end

    // Negative feedback: drive the opposite of what we read.
    assign adc_out = ~adc_in_rr;

    reg [11:0] cnt;
    reg [12:0] acc;   // 13 bits so 4096 ones don't overflow
    always @(posedge clk) begin
        if (!rst_n) begin
            cnt <= 12'd0;
            acc <= 13'd0;
            result <= 12'd0;
        end else if (cnt == 12'hFFF) begin
            result <= acc[12] ? 12'hFFF : acc[11:0];
            acc <= {12'd0, adc_in_rr};
            cnt <= 12'd0;
        end else begin
            acc <= acc + {12'd0, adc_in_rr};
            cnt <= cnt + 12'd1;
        end
    end
endmodule
