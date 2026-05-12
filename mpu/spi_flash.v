// SPI flash reader.
//
// Issues a standard 0x03 READ command with a 24-bit address and streams
// back the requested number of bytes. Mode 0 SPI at half the input clock
// rate (so at 12 MHz system clock, SPI runs at 6 MHz).
//
// Usage:
//   - Pulse `start` high for one cycle with `addr` and `count` valid.
//   - `busy` goes high immediately and stays high until `done` pulses.
//   - For each byte read, `data_valid` pulses high for one cycle with
//     the byte on `data`.
//   - When all `count` bytes have been streamed, `done` pulses high for
//     one cycle and `busy` drops.
//
// The module keeps CS_n asserted for the whole transaction and uses the
// flash's address auto-increment to read consecutive bytes — one command
// + one address, then as many data bytes as needed.

module spi_flash (
    input  wire        clk,
    input  wire        rst_n,

    // Command interface
    input  wire        start,
    input  wire [23:0] addr,
    input  wire [23:0] count,
    output reg         busy,
    output reg         done,

    // Data output
    output reg  [7:0]  data,
    output reg         data_valid,

    // SPI pins (active-low CS)
    output reg         sck,
    output reg         cs_n,
    output reg         mosi,
    input  wire        miso
);

    localparam S_IDLE   = 3'd0;
    localparam S_CMD    = 3'd1;   // shift out 0x03 READ command
    localparam S_ADDR   = 3'd2;   // shift out 24-bit address
    localparam S_DATA   = 3'd3;   // shift in data bytes
    localparam S_DONE   = 3'd4;

    reg [2:0]  state;
    reg [7:0]  shift_out;   // bits to shift out MSB first
    reg [7:0]  shift_in;    // bits coming in MSB first
    reg [5:0]  bit_cnt;     // bits remaining in current phase
    reg        sck_phase;   // 0 = first half of bit period, 1 = second half
    reg [23:0] addr_r;
    reg [23:0] bytes_left;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            busy       <= 1'b0;
            done       <= 1'b0;
            data_valid <= 1'b0;
            data       <= 8'd0;
            sck        <= 1'b0;
            cs_n       <= 1'b1;
            mosi       <= 1'b0;
            shift_out  <= 8'd0;
            shift_in   <= 8'd0;
            bit_cnt    <= 6'd0;
            sck_phase  <= 1'b0;
            addr_r     <= 24'd0;
            bytes_left <= 24'd0;
        end else begin
            done       <= 1'b0;
            data_valid <= 1'b0;

            case (state)
                S_IDLE: begin
                    sck   <= 1'b0;
                    cs_n  <= 1'b1;
                    if (start) begin
                        busy       <= 1'b1;
                        cs_n       <= 1'b0;     // assert CS
                        addr_r     <= addr;
                        bytes_left <= count;
                        shift_out  <= 8'h03;    // READ command
                        bit_cnt    <= 6'd8;
                        sck_phase  <= 1'b0;
                        mosi       <= 8'h03 >> 7; // set first bit
                        state      <= S_CMD;
                    end
                end

                S_CMD: begin
                    if (sck_phase == 1'b0) begin
                        sck       <= 1'b1;
                        sck_phase <= 1'b1;
                    end else begin
                        sck       <= 1'b0;
                        sck_phase <= 1'b0;
                        if (bit_cnt == 6'd1) begin
                            shift_out <= addr_r[23:16];
                            mosi      <= addr_r[23];
                            addr_r    <= {addr_r[15:0], 8'd0};
                            bit_cnt   <= 6'd24;
                            state     <= S_ADDR;
                        end else begin
                            shift_out <= {shift_out[6:0], 1'b0};
                            mosi      <= shift_out[6];
                            bit_cnt   <= bit_cnt - 6'd1;
                        end
                    end
                end

                S_ADDR: begin
                    if (sck_phase == 1'b0) begin
                        sck       <= 1'b1;
                        sck_phase <= 1'b1;
                    end else begin
                        sck       <= 1'b0;
                        sck_phase <= 1'b0;
                        if (bit_cnt == 6'd1) begin
                            bit_cnt  <= 6'd8;
                            shift_in <= 8'd0;
                            mosi     <= 1'b0;
                            state    <= S_DATA;
                        end else begin
                            if (bit_cnt[2:0] == 3'd1) begin
                                shift_out <= addr_r[23:16];
                                mosi      <= addr_r[23];
                                addr_r    <= {addr_r[15:0], 8'd0};
                            end else begin
                                shift_out <= {shift_out[6:0], 1'b0};
                                mosi      <= shift_out[6];
                            end
                            bit_cnt <= bit_cnt - 6'd1;
                        end
                    end
                end

                S_DATA: begin
                    if (sck_phase == 1'b0) begin
                        sck       <= 1'b1;
                        sck_phase <= 1'b1;
                        shift_in  <= {shift_in[6:0], miso};
                    end else begin
                        sck       <= 1'b0;
                        sck_phase <= 1'b0;
                        if (bit_cnt == 6'd1) begin
                            // Phase-0 of bit_cnt=1 already shifted in the
                            // last bit; shift_in now holds all 8 bits.
                            data       <= shift_in;
                            data_valid <= 1'b1;
                            bytes_left <= bytes_left - 24'd1;
                            shift_in   <= 8'd0;
                            bit_cnt    <= 6'd8;
                            if (bytes_left == 24'd1) begin
                                state <= S_DONE;
                            end
                        end else begin
                            bit_cnt <= bit_cnt - 6'd1;
                        end
                    end
                end

                S_DONE: begin
                    cs_n  <= 1'b1;
                    sck   <= 1'b0;
                    busy  <= 1'b0;
                    done  <= 1'b1;
                    state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
