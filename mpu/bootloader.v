// UART Bootloader
// Receives a program over UART and writes it to SPRAM.
//
// Protocol:
//   1. Host sends 4 bytes (little-endian): program length in bytes
//   2. Host sends the program bytes
//   3. Bootloader releases the MPU to run
//
// While loading, mpu_rst_n is held low.

module bootloader (
    input  wire        clk,
    input  wire        rst_n,

    // UART RX byte stream
    input  wire [7:0]  rx_data,
    input  wire        rx_valid,

    // Memory write port (directly to SPRAM)
    output reg         wr,
    output reg  [31:0] addr,
    output reg  [31:0] wdata,

    // MPU reset control
    output reg         mpu_rst_n
);

    localparam S_LEN0 = 3'd0;  // receive length byte 0 (LSB)
    localparam S_LEN1 = 3'd1;
    localparam S_LEN2 = 3'd2;
    localparam S_LEN3 = 3'd3;
    localparam S_DATA = 3'd4;  // receive program bytes
    localparam S_DONE = 3'd5;  // release MPU

    reg [2:0]  state;
    reg [31:0] length;     // total bytes to receive
    reg [31:0] count;      // bytes received so far
    reg [1:0]  byte_idx;   // byte position within current word
    reg [31:0] word_buf;   // accumulates 4 bytes into a word

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_LEN0;
            mpu_rst_n <= 1'b0;
            wr       <= 1'b0;
            addr     <= 32'd0;
            wdata    <= 32'd0;
            length   <= 32'd0;
            count    <= 32'd0;
            byte_idx <= 2'd0;
            word_buf <= 32'd0;
        end else begin
            wr <= 1'b0;

            case (state)
                S_LEN0: begin
                    mpu_rst_n <= 1'b0;
                    if (rx_valid) begin
                        length[7:0] <= rx_data;
                        state <= S_LEN1;
                    end
                end

                S_LEN1: if (rx_valid) begin
                    length[15:8] <= rx_data;
                    state <= S_LEN2;
                end

                S_LEN2: if (rx_valid) begin
                    length[23:16] <= rx_data;
                    state <= S_LEN3;
                end

                S_LEN3: if (rx_valid) begin
                    length[31:24] <= rx_data;
                    count    <= 32'd0;
                    byte_idx <= 2'd0;
                    word_buf <= 32'd0;
                    addr     <= 32'd0;
                    state    <= S_DATA;
                end

                S_DATA: begin
                    if (rx_valid) begin
                        case (byte_idx)
                            2'd0: word_buf[7:0]   <= rx_data;
                            2'd1: word_buf[15:8]  <= rx_data;
                            2'd2: word_buf[23:16] <= rx_data;
                            2'd3: word_buf[31:24] <= rx_data;
                        endcase

                        if (byte_idx == 2'd3 || count + 1 == length) begin
                            // Write the accumulated word
                            wr    <= 1'b1;
                            addr  <= {18'd0, count[15:2], 2'b00};
                            case (byte_idx)
                                2'd0: wdata <= {24'd0, rx_data};
                                2'd1: wdata <= {16'd0, rx_data, word_buf[7:0]};
                                2'd2: wdata <= {8'd0, rx_data, word_buf[15:8], word_buf[7:0]};
                                2'd3: wdata <= {rx_data, word_buf[23:16], word_buf[15:8], word_buf[7:0]};
                            endcase
                            byte_idx <= 2'd0;
                            word_buf <= 32'd0;
                        end else begin
                            byte_idx <= byte_idx + 2'd1;
                        end

                        count <= count + 32'd1;
                        if (count + 1 == length)
                            state <= S_DONE;
                    end
                end

                S_DONE: begin
                    mpu_rst_n <= 1'b1;
                end
            endcase
        end
    end

endmodule
