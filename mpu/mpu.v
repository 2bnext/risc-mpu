// MPU – Minimal Processing Unit
// Main execution loop with LD/ST support.
// More instructions to be added later.

module mpu (
    input  wire        clk,
    input  wire        rst_n,

    // Memory interface (active-high, active for 1 cycle)
    output reg         mem_rd,
    output reg         mem_wr,
    output reg  [31:0] mem_addr,
    output reg  [31:0] mem_wdata,
    output reg  [1:0]  mem_size,      // 00=u8, 01=u16, 10=u32
    input  wire [31:0] mem_rdata,
    input  wire        mem_ready
);

    // ---- State machine ----
    localparam S_FETCH   = 3'd0;
    localparam S_DECODE  = 3'd1;
    localparam S_EXECUTE = 3'd2;
    localparam S_MEM     = 3'd3;
    localparam S_WB      = 3'd4;

    reg [2:0] state;

    // ---- Program counter ----
    reg [31:0] pc;

    // ---- Instruction register ----
    reg [31:0] ir;

    // ---- Instruction field decode ----
    wire [4:0] opcode   = ir[31:27];
    wire [2:0] rd       = ir[26:24];
    wire [1:0] size     = ir[23:22];
    wire       reg_val  = ir[21];
    wire       addr_imm = ir[20];
    wire [19:0] payload = ir[19:0];

    // ---- Opcodes ----

    // Control
    localparam OP_NOP   = 5'b00000;  // 0

    // Data movement
    localparam OP_LD    = 5'b00001;  // 1
    localparam OP_LDH   = 5'b00010;  // 2
    localparam OP_ST    = 5'b00011;  // 3

    // Arithmetic
    localparam OP_ADD   = 5'b00100;  // 4
    localparam OP_SUB   = 5'b00101;  // 5

    // Branch
    localparam OP_BEQ   = 5'b00110;  // 6
    localparam OP_BNE   = 5'b00111;  // 7
    localparam OP_BLT   = 5'b01000;  // 8
    localparam OP_BGT   = 5'b01001;  // 9
    localparam OP_BLE   = 5'b01010;  // 10
    localparam OP_BGE   = 5'b01011;  // 11

    // Logic
    localparam OP_AND   = 5'b01100;  // 12
    localparam OP_OR    = 5'b01101;  // 13
    localparam OP_XOR   = 5'b01110;  // 14
    localparam OP_SHL   = 5'b01111;  // 15
    localparam OP_SHR   = 5'b10000;  // 16

    // Subroutine (r7 = stack pointer)
    localparam OP_CALL  = 5'b10001;  // 17
    localparam OP_RET   = 5'b10010;  // 18

    // ---- Register file (r0 is hardwired to 0) ----
    reg [31:0] regs [0:7];

    // ---- Latched call target ----
    reg [31:0] call_target;

    // Register read values for AGU
    wire [2:0]  base_sel  = payload[19:17];
    wire [2:0]  index_sel = payload[14:12];
    wire [31:0] base_reg_val  = (base_sel  == 0) ? 32'd0 : regs[base_sel];
    wire [31:0] index_reg_val = (index_sel == 0) ? 32'd0 : regs[index_sel];

    // ---- AGU instance ----
    wire [31:0] agu_eff_addr;
    wire        agu_is_imm;
    wire [31:0] agu_imm_value;
    wire        agu_wb_en;
    wire [2:0]  agu_wb_reg;
    wire [31:0] agu_wb_val;

    agu u_agu (
        .reg_value     (reg_val),
        .addr_imm      (addr_imm),
        .payload       (payload),
        .base_reg_val  (base_reg_val),
        .index_reg_val (index_reg_val),
        .eff_addr      (agu_eff_addr),
        .is_immediate  (agu_is_imm),
        .imm_value     (agu_imm_value),
        .wb_en         (agu_wb_en),
        .wb_reg        (agu_wb_reg),
        .wb_val        (agu_wb_val)
    );

    // ---- Branch decode ----
    // payload[19]    = reg_or_imm: 0=register, 1=3-bit immediate
    // payload[18:16] = compare register select OR 3-bit immediate
    // payload[15:0]  = branch target address
    wire        br_is_imm  = payload[19];
    wire [2:0]  br_cmp_sel = payload[18:16];
    wire [15:0] br_target  = payload[15:0];

    wire [31:0] rd_val_raw  = (rd == 0) ? 32'd0 : regs[rd];
    wire [31:0] cmp_val_raw = br_is_imm ? {29'd0, br_cmp_sel} : ((br_cmp_sel == 0) ? 32'd0 : regs[br_cmp_sel]);

    // Size-masked compare values
    reg [31:0] rd_val;
    reg [31:0] cmp_val;
    always @(*) begin
        case (size)
            2'b00: begin  // .b — sign-extend from 8 bits
                rd_val  = {{24{rd_val_raw[7]}},  rd_val_raw[7:0]};
                cmp_val = {{24{cmp_val_raw[7]}}, cmp_val_raw[7:0]};
            end
            2'b01: begin  // .w — sign-extend from 16 bits
                rd_val  = {{16{rd_val_raw[15]}},  rd_val_raw[15:0]};
                cmp_val = {{16{cmp_val_raw[15]}}, cmp_val_raw[15:0]};
            end
            default: begin  // .l — full 32 bits
                rd_val  = rd_val_raw;
                cmp_val = cmp_val_raw;
            end
        endcase
    end

    wire signed [31:0] rd_val_s  = rd_val;
    wire signed [31:0] cmp_val_s = cmp_val;
    reg branch_taken;

    always @(*) begin
        case (opcode)
            OP_BEQ:  branch_taken = (rd_val  == cmp_val);
            OP_BNE:  branch_taken = (rd_val  != cmp_val);
            OP_BLT:  branch_taken = (rd_val_s <  cmp_val_s);
            OP_BGT:  branch_taken = (rd_val_s >  cmp_val_s);
            OP_BLE:  branch_taken = (rd_val_s <= cmp_val_s);
            OP_BGE:  branch_taken = (rd_val_s >= cmp_val_s);
            default: branch_taken = 1'b0;
        endcase
    end

    // ---- Latched AGU outputs (captured in EXECUTE) ----
    reg        agu_wb_en_r;
    reg [2:0]  agu_wb_reg_r;
    reg [31:0] agu_wb_val_r;

    // ---- Main state machine ----
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_FETCH;
            pc       <= 32'd0;
            ir       <= 32'd0;
            mem_rd   <= 1'b0;
            mem_wr   <= 1'b0;
            mem_addr <= 32'd0;
            mem_wdata<= 32'd0;
            mem_size <= 2'b00;
            agu_wb_en_r   <= 1'b0;
            agu_wb_reg_r  <= 3'd0;
            agu_wb_val_r  <= 32'd0;
            call_target   <= 32'd0;
            for (i = 0; i < 8; i = i + 1)
                regs[i] <= 32'd0;
            regs[7] <= 32'h00010000;  // r7 = SP, top of 64KB RAM
        end else begin
            // Default: deassert memory strobes
            mem_rd <= 1'b0;
            mem_wr <= 1'b0;

            case (state)
                // ---- FETCH: request instruction from memory ----
                S_FETCH: begin
                    mem_addr <= pc;
                    mem_size <= 2'b10;       // instructions are 32-bit
                    mem_rd   <= 1'b1;
                    state    <= S_DECODE;
                end

                // ---- DECODE: latch instruction & AGU results ----
                S_DECODE: begin
                    if (mem_ready) begin
                        ir <= mem_rdata;
                        state <= S_EXECUTE;
                    end
                    // AGU outputs are combinational from ir, so they
                    // settle once ir is loaded; we latch them next cycle.
                end

                // ---- EXECUTE: latch AGU, compute result or start memory op ----
                S_EXECUTE: begin
                    agu_wb_en_r  <= agu_wb_en;
                    agu_wb_reg_r <= agu_wb_reg;
                    agu_wb_val_r <= agu_wb_val;

                    case (opcode)
                        OP_NOP: begin
                            pc    <= pc + 32'd4;
                            state <= S_FETCH;
                        end

                        OP_LDH: begin
                            if (rd != 0)
                                regs[rd] <= {payload, regs[rd][11:0]};
                            pc    <= pc + 32'd4;
                            state <= S_FETCH;
                        end

                        OP_BEQ, OP_BNE, OP_BLT, OP_BGT, OP_BLE, OP_BGE: begin
                            pc    <= branch_taken ? {16'd0, br_target} : pc + 32'd4;
                            state <= S_FETCH;
                        end

                        OP_ST: begin
                            if (agu_is_imm) begin
                                mem_addr  <= (rd == 0) ? 32'd0 : regs[rd];
                                mem_wdata <= agu_imm_value;
                            end else begin
                                mem_addr  <= agu_eff_addr;
                                mem_wdata <= (rd == 0) ? 32'd0 : regs[rd];
                            end
                            mem_size <= size;
                            mem_wr   <= 1'b1;
                            state    <= S_MEM;
                        end

                        OP_LD, OP_ADD, OP_SUB, OP_AND, OP_OR, OP_XOR, OP_SHL, OP_SHR: begin
                            if (agu_is_imm) begin
                                if (rd != 0) begin
                                    case (opcode)
                                        OP_LD:  regs[rd] <= agu_imm_value;
                                        OP_ADD: regs[rd] <= regs[rd] + agu_imm_value;
                                        OP_SUB: regs[rd] <= regs[rd] - agu_imm_value;
                                        OP_AND: regs[rd] <= regs[rd] & agu_imm_value;
                                        OP_OR:  regs[rd] <= regs[rd] | agu_imm_value;
                                        OP_XOR: regs[rd] <= regs[rd] ^ agu_imm_value;
                                        OP_SHL: regs[rd] <= regs[rd] << agu_imm_value[4:0];
                                        OP_SHR: regs[rd] <= regs[rd] >> agu_imm_value[4:0];
                                    endcase
                                end
                                pc    <= pc + 32'd4;
                                state <= S_FETCH;
                            end else begin
                                // Memory path: read operand from memory
                                mem_addr    <= agu_eff_addr;
                                mem_size    <= size;
                                mem_rd      <= 1'b1;
                                state       <= S_MEM;
                            end
                        end

                        OP_CALL: begin
                            // r7 -= 4, [r7] = PC+4, jump to target
                            regs[7]     <= regs[7] - 32'd4;
                            mem_addr    <= regs[7] - 32'd4;
                            mem_wdata   <= pc + 32'd4;
                            mem_size    <= 2'b10;
                            mem_wr      <= 1'b1;
                            call_target <= {{12{payload[19]}}, payload};
                            state       <= S_MEM;
                        end

                        OP_RET: begin
                            // PC = [r7], r7 += 4
                            mem_addr <= regs[7];
                            mem_size <= 2'b10;
                            mem_rd   <= 1'b1;
                            state    <= S_MEM;
                        end

                        default: begin
                            pc    <= pc + 32'd4;
                            state <= S_FETCH;
                        end
                    endcase
                end

                // ---- MEM: wait for memory ----
                S_MEM: begin
                    if (mem_ready)
                        state <= S_WB;
                end

                // ---- WB: apply mem_rdata result to register file ----
                S_WB: begin
                    case (opcode)
                        OP_CALL: begin
                            pc    <= call_target;
                            state <= S_FETCH;
                        end

                        OP_RET: begin
                            regs[7] <= regs[7] + 32'd4;
                            pc      <= mem_rdata;
                            state   <= S_FETCH;
                        end

                        OP_ST: begin
                            pc    <= pc + 32'd4;
                            state <= S_FETCH;
                        end

                        default: begin
                            // ALU ops with memory operand
                            if (rd != 0) begin
                                case (opcode)
                                    OP_LD:  regs[rd] <= mem_rdata;
                                    OP_ADD: regs[rd] <= regs[rd] + mem_rdata;
                                    OP_SUB: regs[rd] <= regs[rd] - mem_rdata;
                                    OP_AND: regs[rd] <= regs[rd] & mem_rdata;
                                    OP_OR:  regs[rd] <= regs[rd] | mem_rdata;
                                    OP_XOR: regs[rd] <= regs[rd] ^ mem_rdata;
                                    OP_SHL: regs[rd] <= regs[rd] << mem_rdata[4:0];
                                    OP_SHR: regs[rd] <= regs[rd] >> mem_rdata[4:0];
                                endcase
                            end
                            pc    <= pc + 32'd4;
                            state <= S_FETCH;
                        end
                    endcase
                    // AGU writeback (post-increment)
                    if (agu_wb_en_r && agu_wb_reg_r != 0)
                        regs[agu_wb_reg_r] <= agu_wb_val_r;
                end
            endcase
        end
    end

endmodule
