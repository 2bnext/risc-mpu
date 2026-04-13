// Top-level module for iCESugar 1.5
// Bootloader loads program via UART into SPRAM, then runs the MPU.

module top (
    input  wire       clk,
    output wire       uart_tx,
    input  wire       uart_rx,
    input  wire       btn_s2,
    output wire       led_r,
    output wire       led_g,
    output wire       led_b,
    inout  wire [7:0] gpio,
    inout  wire       i2c_scl,
    inout  wire       i2c_sda,
    input  wire       adc_in,
    output wire       adc_out
);

    // ---- Power-on reset + S2 button reset ----
    reg btn_r, btn_rr;
    always @(posedge clk) begin
        btn_r  <= btn_s2;
        btn_rr <= btn_r;
    end

    reg [3:0] rst_cnt = 4'd0;
    wire rst_n = rst_cnt[3];
    always @(posedge clk) begin
        if (!btn_rr)
            rst_cnt <= 4'd0;
        else if (!rst_n)
            rst_cnt <= rst_cnt + 4'd1;
    end

    // ---- UART RX ----
    wire [7:0] rx_data;
    wire       rx_valid;

    uart_rx #(
        .CLK_FREQ (12_000_000),
        .BAUD     (115_200)
    ) u_uart_rx (
        .clk   (clk),
        .rst_n (rst_n),
        .rx    (uart_rx),
        .dout  (rx_data),
        .valid (rx_valid)
    );

    // ---- Bootloader ----
    wire        boot_wr;
    wire [31:0] boot_addr;
    wire [31:0] boot_wdata;
    wire        mpu_rst_n;

    bootloader u_boot (
        .clk       (clk),
        .rst_n     (rst_n),
        .rx_data   (rx_data),
        .rx_valid  (rx_valid),
        .wr        (boot_wr),
        .addr      (boot_addr),
        .wdata     (boot_wdata),
        .mpu_rst_n (mpu_rst_n)
    );

    // ---- MPU ----
    wire        mem_rd, mem_wr;
    wire [31:0] mem_addr, mem_wdata;
    wire [1:0]  mem_size;
    wire [31:0] mem_rdata;
    wire        mem_ready;

    mpu u_mpu (
        .clk       (clk),
        .rst_n     (mpu_rst_n),
        .mem_rd    (mem_rd),
        .mem_wr    (mem_wr),
        .mem_addr  (mem_addr),
        .mem_wdata (mem_wdata),
        .mem_size  (mem_size),
        .mem_rdata (mem_rdata),
        .mem_ready (mem_ready)
    );

    // ---- Address decode ----
    wire is_uart = (mem_addr[31:16] == 16'hFFFF);

    // ---- SPRAM ----
    wire        spram_rd = mpu_rst_n ? (mem_rd & ~is_uart) : 1'b0;
    wire        spram_wr = mpu_rst_n ? (mem_wr & ~is_uart) : boot_wr;
    wire [31:0] spram_addr  = mpu_rst_n ? mem_addr  : boot_addr;
    wire [31:0] spram_wdata = mpu_rst_n ? mem_wdata : boot_wdata;
    wire [1:0]  spram_size  = mpu_rst_n ? mem_size  : 2'b10;
    wire        spram_ready;
    wire [31:0] spram_rdata_raw;

    // Shift the write data into the addressed byte lane and compute a
    // per-nibble write mask, so byte/halfword stores don't clobber neighbours.
    reg  [31:0] spram_wdata_a;
    reg  [3:0]  spram_mask_lo;
    reg  [3:0]  spram_mask_hi;
    always @(*) begin
        case (spram_size)
            2'b00: begin // .8 — store wdata[7:0] at addr[1:0]
                case (spram_addr[1:0])
                    2'd0: begin
                        spram_wdata_a = {24'd0, spram_wdata[7:0]};
                        spram_mask_lo = 4'b0011;
                        spram_mask_hi = 4'b0000;
                    end
                    2'd1: begin
                        spram_wdata_a = {16'd0, spram_wdata[7:0], 8'd0};
                        spram_mask_lo = 4'b1100;
                        spram_mask_hi = 4'b0000;
                    end
                    2'd2: begin
                        spram_wdata_a = {8'd0, spram_wdata[7:0], 16'd0};
                        spram_mask_lo = 4'b0000;
                        spram_mask_hi = 4'b0011;
                    end
                    2'd3: begin
                        spram_wdata_a = {spram_wdata[7:0], 24'd0};
                        spram_mask_lo = 4'b0000;
                        spram_mask_hi = 4'b1100;
                    end
                endcase
            end
            2'b01: begin // .16 — store wdata[15:0] at addr[1]*2
                if (spram_addr[1] == 1'b0) begin
                    spram_wdata_a = {16'd0, spram_wdata[15:0]};
                    spram_mask_lo = 4'b1111;
                    spram_mask_hi = 4'b0000;
                end else begin
                    spram_wdata_a = {spram_wdata[15:0], 16'd0};
                    spram_mask_lo = 4'b0000;
                    spram_mask_hi = 4'b1111;
                end
            end
            default: begin // .32
                spram_wdata_a = spram_wdata;
                spram_mask_lo = 4'b1111;
                spram_mask_hi = 4'b1111;
            end
        endcase
    end

    mem u_mem (
        .clk     (clk),
        .rd      (spram_rd),
        .wr      (spram_wr),
        .addr    (spram_addr),
        .wdata   (spram_wdata_a),
        .mask_lo (spram_mask_lo),
        .mask_hi (spram_mask_hi),
        .rdata   (spram_rdata_raw),
        .ready   (spram_ready)
    );

    // Byte extraction from 32-bit SPRAM word
    reg [1:0] byte_off_r;
    reg [1:0] size_r;
    always @(posedge clk) begin
        if (spram_rd | spram_wr) begin
            byte_off_r <= spram_addr[1:0];
            size_r     <= spram_size;
        end
    end

    reg [31:0] spram_rdata;
    always @(*) begin
        case (size_r)
            2'b00: case (byte_off_r)
                2'd0: spram_rdata = {24'd0, spram_rdata_raw[7:0]};
                2'd1: spram_rdata = {24'd0, spram_rdata_raw[15:8]};
                2'd2: spram_rdata = {24'd0, spram_rdata_raw[23:16]};
                2'd3: spram_rdata = {24'd0, spram_rdata_raw[31:24]};
            endcase
            2'b01: case (byte_off_r[1])
                1'b0: spram_rdata = {16'd0, spram_rdata_raw[15:0]};
                1'b1: spram_rdata = {16'd0, spram_rdata_raw[31:16]};
            endcase
            default: spram_rdata = spram_rdata_raw;
        endcase
    end

    // ---- UART TX ----
    wire uart_busy;
    reg  uart_wr;
    reg  [7:0] uart_din;

    always @(posedge clk) begin
        uart_wr  <= mem_wr & is_uart & (mem_addr[7:0] == 8'h00);
        uart_din <= mem_wdata[7:0];
    end

    uart_tx #(
        .CLK_FREQ (12_000_000),
        .BAUD     (115_200)
    ) u_uart_tx (
        .clk   (clk),
        .rst_n (rst_n),
        .din   (uart_din),
        .wr    (uart_wr),
        .tx    (uart_tx),
        .busy  (uart_busy)
    );

    // ---- Memory bus ----
    // SPRAM and UART both have 1-cycle latency. The CPU consumes mem_rdata
    // in its S_WB state, which is one cycle AFTER mem_ready fires. SPRAM's
    // DATAOUT stays valid across that cycle, but the UART read mux must be
    // held one extra cycle so that S_WB sees the correct value (otherwise
    // the mux routes stale spram_rdata and the CPU latches garbage).
    reg sel_uart_r, sel_uart_rr;
    always @(posedge clk) begin
        sel_uart_r  <= is_uart & (mem_rd | mem_wr);
        sel_uart_rr <= sel_uart_r;
    end

    // Latched IO read result. Dispatch on the low byte of the MMIO address.
    reg [31:0] io_rdata_held;
    always @(posedge clk)
        if (sel_uart_r)
            case (mem_addr[7:0])
                8'h04:   io_rdata_held <= {31'd0, uart_busy};
                8'h10:   io_rdata_held <= {24'd0, gpio_in};
                8'h14:   io_rdata_held <= {24'd0, gpio_dir};
                8'h18:   io_rdata_held <= {24'd0, i2c_rx_data};
                8'h1C:   io_rdata_held <= {30'd0, i2c_ack_recv, i2c_busy};
                8'h20:   io_rdata_held <= {20'd0, adc_result};
                default: io_rdata_held <= 32'd0;
            endcase

    wire sel_uart_any = sel_uart_r | sel_uart_rr;
    assign mem_rdata = sel_uart_any ? io_rdata_held : spram_rdata;

    reg io_ready;
    always @(posedge clk)
        io_ready <= (mem_rd | mem_wr) & is_uart;

    assign mem_ready = sel_uart_r ? io_ready : spram_ready;

    // ---- LED register (0xFFFF0008) ----
    reg [2:0] led_reg = 3'b000;
    reg mpu_rst_n_d;
    wire led_wr = mem_wr & is_uart & (mem_addr[7:0] == 8'h08);
    always @(posedge clk) begin
        mpu_rst_n_d <= mpu_rst_n;
        if (!mpu_rst_n)
            led_reg <= 3'b010;  // red while loading
        else if (!mpu_rst_n_d)
            led_reg <= 3'b000;  // all off once program starts
        else if (led_wr)
            led_reg <= mem_wdata[2:0];
    end

    assign led_g = ~led_reg[0];
    assign led_r = ~led_reg[1];
    assign led_b = ~led_reg[2];

    // ---- GPIO (0xFFFF0010 data, 0xFFFF0014 direction) ----
    // 8 bidirectional pins. Direction bit 1 = output, 0 = input.
    // Reads return the live pad state (input or whatever is being driven).
    reg [7:0] gpio_dir = 8'd0;
    reg [7:0] gpio_out = 8'd0;
    wire [7:0] gpio_in;

    wire gpio_data_wr = mem_wr & is_uart & (mem_addr[7:0] == 8'h10);
    wire gpio_dir_wr  = mem_wr & is_uart & (mem_addr[7:0] == 8'h14);

    always @(posedge clk) begin
        if (!mpu_rst_n) begin
            gpio_dir <= 8'd0;     // all inputs on reset
            gpio_out <= 8'd0;
        end else begin
            if (gpio_dir_wr)  gpio_dir <= mem_wdata[7:0];
            if (gpio_data_wr) gpio_out <= mem_wdata[7:0];
        end
    end

    genvar gi;
    generate
        for (gi = 0; gi < 8; gi = gi + 1) begin : g_gpio
            SB_IO #(
                .PIN_TYPE (6'b1010_01),  // simple output w/ output enable, simple input
                .PULLUP   (1'b0)
            ) u_io (
                .PACKAGE_PIN  (gpio[gi]),
                .OUTPUT_ENABLE(gpio_dir[gi]),
                .D_OUT_0      (gpio_out[gi]),
                .D_IN_0       (gpio_in[gi])
            );
        end
    endgenerate

    // ---- I2C master (0xFFFF0018 data, 0xFFFF001C cmd/status) ----
    wire [7:0] i2c_rx_data;
    wire       i2c_busy;
    wire       i2c_ack_recv;
    wire       i2c_scl_drive;   // 1 = release, 0 = drive low
    wire       i2c_sda_drive;
    wire       i2c_sda_in;

    wire i2c_data_wr = mem_wr & is_uart & (mem_addr[7:0] == 8'h18);
    wire i2c_cmd_wr  = mem_wr & is_uart & (mem_addr[7:0] == 8'h1C);

    i2c_master u_i2c (
        .clk      (clk),
        .rst_n    (mpu_rst_n),
        .cmd_we   (i2c_cmd_wr),
        .cmd_in   (mem_wdata[4:0]),
        .tx_we    (i2c_data_wr),
        .tx_data  (mem_wdata[7:0]),
        .rx_data  (i2c_rx_data),
        .ack_recv (i2c_ack_recv),
        .busy     (i2c_busy),
        .scl      (i2c_scl_drive),
        .sda      (i2c_sda_drive),
        .sda_in   (i2c_sda_in)
    );

    // Open-drain pads. PULLUP enables the iCE40 weak (~100 kΩ) pull-up;
    // a stronger external pull-up (2.2–10 kΩ) is still recommended for I2C.
    SB_IO #(
        .PIN_TYPE (6'b1010_01),
        .PULLUP   (1'b1)
    ) u_scl_io (
        .PACKAGE_PIN  (i2c_scl),
        .OUTPUT_ENABLE(~i2c_scl_drive),
        .D_OUT_0      (1'b0),
        .D_IN_0       ()
    );

    SB_IO #(
        .PIN_TYPE (6'b1010_01),
        .PULLUP   (1'b1)
    ) u_sda_io (
        .PACKAGE_PIN  (i2c_sda),
        .OUTPUT_ENABLE(~i2c_sda_drive),
        .D_OUT_0      (1'b0),
        .D_IN_0       (i2c_sda_in)
    );

    // ---- Sigma-delta ADC (0xFFFF0020 result, 12 bits) ----
    wire [11:0] adc_result;
    sigma_delta_adc u_adc (
        .clk     (clk),
        .rst_n   (mpu_rst_n),
        .adc_in  (adc_in),
        .adc_out (adc_out),
        .result  (adc_result)
    );

endmodule
