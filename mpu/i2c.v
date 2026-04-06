// Simple I2C master, ~100 kHz from 12 MHz clock.
// Open-drain SCL/SDA: outputs are 1=release, 0=drive low.
// External pull-ups required on the board.
//
// MMIO:
//   0xFFFF0018  RW  data:  W = byte to shift out, R = last byte shifted in
//   0xFFFF001C  RW  cmd:   W = command bits (see below)
//                          R = status: [0]=busy, [1]=ack_recv (0 = slave ACKed)
//
// Command bits (any combination, processed in order start→write→read→stop):
//   [0] start    — generate START condition
//   [1] stop     — generate STOP condition
//   [2] write    — shift out the data register, capture slave ACK
//   [3] read     — shift in 8 bits into the data register
//   [4] ack_send — ACK polarity to drive after read (0=ACK, 1=NACK)
//
// Typical sequence to write one byte to slave 0x76, register 0xD0, and read it:
//   data <= 0xEC; cmd <= start|write    ; addr+W
//   data <= 0xD0; cmd <= write          ; reg
//   data <= 0xED; cmd <= start|write    ; repeated start, addr+R
//                 cmd <= read|nack|stop ; read one byte, NACK, STOP
//   read data
//
module i2c_master (
    input  wire        clk,
    input  wire        rst_n,

    // CPU interface (single-cycle pulses)
    input  wire        cmd_we,
    input  wire [4:0]  cmd_in,
    input  wire        tx_we,
    input  wire [7:0]  tx_data,
    output reg  [7:0]  rx_data,
    output reg         ack_recv,
    output wire        busy,

    // Open-drain pads (1 = release/Hi-Z, 0 = drive low)
    output reg         scl,
    output reg         sda,
    input  wire        sda_in
);
    // 12 MHz / 30 = 400 kHz tick → 4 ticks per I2C bit → 100 kHz SCL.
    reg [4:0] div;
    wire tick = (div == 5'd29);
    always @(posedge clk)
        if (!rst_n || tick) div <= 5'd0;
        else                div <= div + 5'd1;

    // Pending operations to perform, in order: start, write, read, stop.
    reg [3:0] todo;        // {stop, read, write, start}
    reg       ack_send;    // ACK bit to drive after a read

    localparam S_IDLE  = 3'd0,
               S_START = 3'd1,
               S_WRITE = 3'd2,
               S_WACK  = 3'd3,
               S_READ  = 3'd4,
               S_RACK  = 3'd5,
               S_STOP  = 3'd6;
    reg [2:0] state;
    reg [1:0] q;     // quarter within a bit period
    reg [2:0] bn;    // bit counter (0..7)
    reg [7:0] sh;    // shift register

    assign busy = (state != S_IDLE) || (todo != 4'd0);

    always @(posedge clk) begin
        if (!rst_n) begin
            scl <= 1'b1;
            sda <= 1'b1;
            state <= S_IDLE;
            todo <= 4'd0;
            q <= 2'd0;
            bn <= 3'd0;
            sh <= 8'd0;
            rx_data <= 8'd0;
            ack_recv <= 1'b1;
            ack_send <= 1'b1;
        end else begin
            if (tx_we) sh <= tx_data;
            if (cmd_we) begin
                todo     <= todo | {cmd_in[1], cmd_in[3], cmd_in[2], cmd_in[0]};
                ack_send <= cmd_in[4];
            end

            if (tick) begin
                case (state)
                    S_IDLE: begin
                        q  <= 2'd0;
                        bn <= 3'd0;
                        if (todo[0]) begin
                            state   <= S_START;
                            todo[0] <= 1'b0;
                        end else if (todo[1]) begin
                            state   <= S_WRITE;
                            todo[1] <= 1'b0;
                        end else if (todo[2]) begin
                            state   <= S_READ;
                            todo[2] <= 1'b0;
                        end else if (todo[3]) begin
                            state   <= S_STOP;
                            todo[3] <= 1'b0;
                        end
                    end

                    // START: SDA falls while SCL high (covers repeated start too).
                    S_START: begin
                        case (q)
                            2'd0: sda <= 1'b1;
                            2'd1: scl <= 1'b1;
                            2'd2: sda <= 1'b0;
                            2'd3: begin scl <= 1'b0; state <= S_IDLE; end
                        endcase
                        q <= q + 2'd1;
                    end

                    // Shift one byte out, MSB first.
                    S_WRITE: begin
                        case (q)
                            2'd0: sda <= sh[7];
                            2'd1: scl <= 1'b1;
                            2'd2: ; // slave samples
                            2'd3: begin
                                scl <= 1'b0;
                                sh  <= {sh[6:0], 1'b0};
                                if (bn == 3'd7) begin
                                    state <= S_WACK;
                                    bn    <= 3'd0;
                                end else begin
                                    bn <= bn + 3'd1;
                                end
                            end
                        endcase
                        q <= q + 2'd1;
                    end

                    // Release SDA, sample slave's ACK.
                    S_WACK: begin
                        case (q)
                            2'd0: sda <= 1'b1;
                            2'd1: scl <= 1'b1;
                            2'd2: ack_recv <= sda_in;
                            2'd3: begin scl <= 1'b0; state <= S_IDLE; end
                        endcase
                        q <= q + 2'd1;
                    end

                    // Shift one byte in, MSB first.
                    S_READ: begin
                        case (q)
                            2'd0: sda <= 1'b1;          // release for slave to drive
                            2'd1: scl <= 1'b1;
                            2'd2: rx_data <= {rx_data[6:0], sda_in};
                            2'd3: begin
                                scl <= 1'b0;
                                if (bn == 3'd7) begin
                                    state <= S_RACK;
                                    bn    <= 3'd0;
                                end else begin
                                    bn <= bn + 3'd1;
                                end
                            end
                        endcase
                        q <= q + 2'd1;
                    end

                    // Drive ACK/NACK to slave.
                    S_RACK: begin
                        case (q)
                            2'd0: sda <= ack_send;
                            2'd1: scl <= 1'b1;
                            2'd2: ; // slave sees our ack
                            2'd3: begin scl <= 1'b0; state <= S_IDLE; end
                        endcase
                        q <= q + 2'd1;
                    end

                    // STOP: SDA rises while SCL high.
                    S_STOP: begin
                        case (q)
                            2'd0: sda <= 1'b0;
                            2'd1: scl <= 1'b1;
                            2'd2: sda <= 1'b1;
                            2'd3: state <= S_IDLE;
                        endcase
                        q <= q + 2'd1;
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end
endmodule
