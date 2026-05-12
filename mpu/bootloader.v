// Bootloader
//
// On reset, tries to load a program from SPI flash at offset 0x100000.
// Falls through to UART upload if no valid program is found.
//
// Flash format at 0x100000:
//   4 bytes: magic 'M' 'P' 'U' '1'  (0x4D 0x50 0x55 0x31)
//   4 bytes: length (little-endian uint32, <= 0x10000)
//   length bytes: program
//
// UART protocol (fallback):
//   4 bytes: length (little-endian uint32)
//   length bytes: program
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

    // SPI flash interface
    output reg         flash_start,
    output reg  [23:0] flash_addr,
    output reg  [23:0] flash_count,
    input  wire        flash_busy,
    input  wire        flash_done,
    input  wire [7:0]  flash_data,
    input  wire        flash_data_valid,

    // MPU reset control
    output reg         mpu_rst_n,

    // Diagnostic: 1 while bootloader is in any flash-path state
    output wire        in_flash,
    // Diagnostic: first byte read from flash (for LED display on mismatch)
    output reg  [7:0]  diag_byte
);

    // ---- States ----
    // Flash path
    localparam S_FLASH_START    = 4'd0;
    localparam S_FLASH_MAGIC    = 4'd1;
    localparam S_FLASH_LEN_REQ  = 4'd2;
    localparam S_FLASH_LEN      = 4'd3;
    localparam S_FLASH_DATA_REQ = 4'd4;
    localparam S_FLASH_DATA     = 4'd5;
    // UART path
    localparam S_LEN0           = 4'd6;
    localparam S_LEN1           = 4'd7;
    localparam S_LEN2           = 4'd8;
    localparam S_LEN3           = 4'd9;
    localparam S_DATA           = 4'd10;
    // Common
    localparam S_DONE           = 4'd11;

    reg [3:0]  state;

    assign in_flash = (state == S_FLASH_START)    ||
                      (state == S_FLASH_MAGIC)    ||
                      (state == S_FLASH_LEN_REQ)  ||
                      (state == S_FLASH_LEN)      ||
                      (state == S_FLASH_DATA_REQ) ||
                      (state == S_FLASH_DATA);
    reg [31:0] length;
    reg [31:0] count;
    reg [1:0]  byte_idx;
    reg [31:0] word_buf;
    reg [1:0]  magic_idx;

    // Magic byte sequence: 'M' 'P' 'U' '1'
    wire [7:0] magic_byte =
        (magic_idx == 2'd0) ? 8'h4D :
        (magic_idx == 2'd1) ? 8'h50 :
        (magic_idx == 2'd2) ? 8'h55 :
                              8'h31;

    // Shared byte-accumulator: push `in` into word_buf at byte_idx, and when
    // byte_idx == 3 or this is the last byte, emit a SPRAM write of the
    // assembled word. Used by both UART and flash paths.
    task accumulate_byte(input [7:0] in);
        begin
            case (byte_idx)
                2'd0: word_buf[7:0]   <= in;
                2'd1: word_buf[15:8]  <= in;
                2'd2: word_buf[23:16] <= in;
                2'd3: word_buf[31:24] <= in;
            endcase

            if (byte_idx == 2'd3 || count + 1 == length) begin
                wr   <= 1'b1;
                addr <= {16'd0, count[15:2], 2'b00};
                case (byte_idx)
                    2'd0: wdata <= {24'd0, in};
                    2'd1: wdata <= {16'd0, in, word_buf[7:0]};
                    2'd2: wdata <= {8'd0, in, word_buf[15:8], word_buf[7:0]};
                    2'd3: wdata <= {in, word_buf[23:16], word_buf[15:8], word_buf[7:0]};
                endcase
                byte_idx <= 2'd0;
                word_buf <= 32'd0;
            end else begin
                byte_idx <= byte_idx + 2'd1;
            end
            count <= count + 32'd1;
        end
    endtask

    // Reset entry state:
    //   S_FLASH_START  — try flash boot first, fall through to UART if no magic.
    //   S_LEN0         — skip flash, wait directly for UART upload (debug/default).
    // Set to S_LEN0 while the flash path is unreliable; switch back to S_FLASH_START
    // to re-enable flash boot once the SPI issue is resolved.
    localparam BOOT_ENTRY = S_LEN0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= BOOT_ENTRY;
            mpu_rst_n   <= 1'b0;
            wr          <= 1'b0;
            addr        <= 32'd0;
            wdata       <= 32'd0;
            length      <= 32'd0;
            count       <= 32'd0;
            byte_idx    <= 2'd0;
            word_buf    <= 32'd0;
            magic_idx   <= 2'd0;
            flash_start <= 1'b0;
            flash_addr  <= 24'd0;
            flash_count <= 24'd0;
            diag_byte   <= 8'hAA;  // sentinel: never-sampled
        end else begin
            wr          <= 1'b0;
            flash_start <= 1'b0;

            case (state)
                // ---- Flash path ----
                S_FLASH_START: begin
                    flash_addr  <= 24'h100000;
                    flash_count <= 24'd4;
                    flash_start <= 1'b1;
                    magic_idx   <= 2'd0;
                    state       <= S_FLASH_MAGIC;
                end

                S_FLASH_MAGIC: begin
                    if (flash_data_valid) begin
                        // Capture the first byte for diagnostic LED
                        if (magic_idx == 2'd0)
                            diag_byte <= flash_data;
                        if (flash_data != magic_byte) begin
                            state <= S_LEN0;
                        end else if (magic_idx == 2'd3) begin
                            magic_idx <= 2'd0;
                        end else begin
                            magic_idx <= magic_idx + 2'd1;
                        end
                    end
                    if (flash_done && state == S_FLASH_MAGIC) begin
                        state <= S_FLASH_LEN_REQ;
                    end
                end

                S_FLASH_LEN_REQ: begin
                    flash_addr  <= 24'h100004;
                    flash_count <= 24'd4;
                    flash_start <= 1'b1;
                    length      <= 32'd0;
                    byte_idx    <= 2'd0;
                    state       <= S_FLASH_LEN;
                end

                S_FLASH_LEN: begin
                    if (flash_data_valid) begin
                        case (byte_idx)
                            2'd0: length[7:0]   <= flash_data;
                            2'd1: length[15:8]  <= flash_data;
                            2'd2: length[23:16] <= flash_data;
                            2'd3: length[31:24] <= flash_data;
                        endcase
                        byte_idx <= byte_idx + 2'd1;
                    end
                    if (flash_done) begin
                        if (length == 32'd0 || length > 32'h10000)
                            state <= S_LEN0;
                        else
                            state <= S_FLASH_DATA_REQ;
                    end
                end

                S_FLASH_DATA_REQ: begin
                    flash_addr  <= 24'h100008;
                    flash_count <= length[23:0];
                    flash_start <= 1'b1;
                    count       <= 32'd0;
                    byte_idx    <= 2'd0;
                    word_buf    <= 32'd0;
                    addr        <= 32'd0;
                    state       <= S_FLASH_DATA;
                end

                S_FLASH_DATA: begin
                    if (flash_data_valid) begin
                        accumulate_byte(flash_data);
                        if (count + 1 == length)
                            state <= S_DONE;
                    end
                end

                // ---- UART path (fallback) ----
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
                        accumulate_byte(rx_data);
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
