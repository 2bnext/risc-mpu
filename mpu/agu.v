// Address Generation Unit (AGU)
// Decodes the addressing mode from a 32-bit instruction and computes
// the effective address for LD/ST operations.
//
// Instruction layout (bits 31..0):
//   [31:27] opcode      (5)
//   [26:24] dest/src reg(3)
//   [23:22] size        (2)  00=.8, 01=.16, 10=.32
//   [21]    reg_value        0=register addressing, 1=immediate/absolute
//   [20]    addr_imm         when reg_value=1: 0=absolute addr, 1=immediate
//   [19:0]  payload     (20)
//
// Payload when reg_value=0 (register modes):
//   [19:17] base_reg    (3)
//   [16:15] mode        (2)  00=indirect, 01=indexed, 10=idx+off, 11=idx+off+wb
//   [14:12] index_reg   (3)
//   [11:0]  offset      (12) sign-extended
//
// Payload when reg_value=1:
//   [19:0]  immediate or absolute address (20 bits, sign-extended to 32)

module agu (
    // Instruction fields (already decoded externally or passed raw)
    input  wire        reg_value,      // bit [21]
    input  wire        addr_imm,       // bit [20]
    input  wire [19:0] payload,        // bits [19:0]

    // Register file read ports
    input  wire [31:0] base_reg_val,   // value of reg selected by payload[19:17]
    input  wire [31:0] index_reg_val,  // value of reg selected by payload[14:12]

    // Outputs
    output reg  [31:0] eff_addr,       // computed effective address
    output reg         is_immediate,   // high when operand is an immediate value
    output reg  [31:0] imm_value,      // the immediate (valid when is_immediate=1)

    // Writeback channel (for post-increment / stride modes)
    output reg         wb_en,          // writeback enable
    output reg  [2:0]  wb_reg,         // which register to write back
    output reg  [31:0] wb_val          // new value for that register
);

    // Internal decode wires
    wire [2:0]  base_sel  = payload[19:17];
    wire [1:0]  mode      = payload[16:15];
    wire [2:0]  index_sel = payload[14:12];
    wire [11:0] offset    = payload[11:0];

    // Sign-extend helpers
    wire [31:0] offset_sx = {{20{offset[11]}}, offset};
    wire [31:0] payload_sx = {{12{payload[19]}}, payload};

    always @(*) begin
        // Defaults
        eff_addr     = 32'b0;
        is_immediate = 1'b0;
        imm_value    = 32'b0;
        wb_en        = 1'b0;
        wb_reg       = 3'b0;
        wb_val       = 32'b0;

        if (reg_value) begin
            // ---- Immediate / absolute addressing ----
            if (addr_imm) begin
                // Immediate: operand is the literal value
                is_immediate = 1'b1;
                imm_value    = payload_sx;
            end else begin
                // Absolute: payload is the memory address
                eff_addr = payload_sx;
            end
        end else begin
            // ---- Register-based addressing ----
            case (mode)
                2'b00: begin
                    // Register direct: operand IS base register value
                    is_immediate = 1'b1;
                    imm_value    = base_reg_val;
                end

                2'b01: begin
                    // [Rbase + Ridx]
                    eff_addr = base_reg_val + index_reg_val;
                end

                2'b10: begin
                    // [Rbase + Ridx + offset], no writeback
                    eff_addr = base_reg_val + index_reg_val + offset_sx;
                end

                2'b11: begin
                    // [Rbase + Ridx], then Ridx += offset (post-increment)
                    eff_addr = base_reg_val + index_reg_val;
                    wb_en    = 1'b1;
                    wb_reg   = index_sel;
                    wb_val   = index_reg_val + offset_sx;
                end
            endcase
        end
    end

endmodule
