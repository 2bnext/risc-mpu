// Top-level module for iCESugar 1.5
// Bootloader loads program via UART into SPRAM, then runs the MPU.

module top (
    input  wire clk,
    output wire uart_tx,
    input  wire uart_rx,
    input  wire btn_s2,
    output wire led_r,
    output wire led_g,
    output wire led_b
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

    mem u_mem (
        .clk   (clk),
        .rd    (spram_rd),
        .wr    (spram_wr),
        .addr  (spram_addr),
        .wdata (spram_wdata),
        .rdata (spram_rdata_raw),
        .ready (spram_ready)
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
        uart_wr  <= mem_wr & is_uart & (mem_addr[3:0] == 4'h0);
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
    // SPRAM and UART both have 1-cycle latency, so use spram_ready directly.
    // Latch which device was accessed for the read mux.
    reg sel_uart_r;
    always @(posedge clk)
        sel_uart_r <= is_uart & (mem_rd | mem_wr);

    reg [31:0] uart_rdata_r;
    always @(posedge clk)
        uart_rdata_r <= {31'd0, uart_busy};

    assign mem_rdata = sel_uart_r ? uart_rdata_r : spram_rdata;
    reg io_ready;
    always @(posedge clk)
        io_ready <= (mem_rd | mem_wr) & is_uart;

    assign mem_ready = sel_uart_r ? io_ready : spram_ready;

    // ---- LED register (0xFFFF0008) ----
    reg [2:0] led_reg = 3'b000;
    wire led_wr = mem_wr & is_uart & (mem_addr[3:0] == 4'h8);
    always @(posedge clk) begin
        if (!mpu_rst_n)
            led_reg <= 3'b010;  // red while loading
        else if (led_wr)
            led_reg <= mem_wdata[2:0];
    end

    assign led_g = ~led_reg[0];
    assign led_r = ~led_reg[1];
    assign led_b = ~led_reg[2];

endmodule
