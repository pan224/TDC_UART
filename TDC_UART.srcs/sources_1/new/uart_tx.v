// -----------------------------------------------------------------------------
// 子模块：UART 发送 (TX) - 32位数据宽度
// 使用计数器简化状态机
// -----------------------------------------------------------------------------
module uart_tx #(
    parameter CLK_FREQ = 200000000,
    parameter BAUD_RATE = 115200
)(
    input           clk,
    input           rst,
    input   [31:0]  tx_data,
    input           tx_start,
    output  reg     tx_busy,
    output  reg     uart_tx
);

    // 计算分频计数器的最大值
    localparam BAUD_CNT_MAX = CLK_FREQ / BAUD_RATE;

    // 状态机状态定义 - 只需4个状态
    localparam IDLE  = 2'd0;
    localparam START = 2'd1;
    localparam DATA  = 2'd2;
    localparam STOP  = 2'd3;

    reg [1:0]  state;
    reg [31:0] baud_cnt;     // 波特率计数器
    reg [31:0] tx_data_reg;  // 数据缓存 (32位)
    reg [2:0]  bit_cnt;      // 位计数器 (0-7)
    reg [1:0]  byte_cnt;     // 字节计数器 (0-3)

    // 波特率计数器逻辑
    always @(posedge clk or posedge rst) begin
        if (rst)
            baud_cnt <= 0;
        else if (state == IDLE)
            baud_cnt <= 0;
        else if (baud_cnt >= BAUD_CNT_MAX - 1)
            baud_cnt <= 0;
        else
            baud_cnt <= baud_cnt + 1;
    end

    // 波特率脉冲信号
    wire baud_pulse = (baud_cnt == BAUD_CNT_MAX - 1);

    // 根据字节计数器选择当前要发送的字节
    wire [7:0] current_byte = (byte_cnt == 2'd0) ? tx_data_reg[7:0]   :
                              (byte_cnt == 2'd1) ? tx_data_reg[15:8]  :
                              (byte_cnt == 2'd2) ? tx_data_reg[23:16] :
                                                   tx_data_reg[31:24] ;

    // 主状态机逻辑
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= IDLE;
            uart_tx <= 1'b1;
            tx_busy <= 1'b0;
            tx_data_reg <= 32'd0;
            bit_cnt <= 3'd0;
            byte_cnt <= 2'd0;
        end else begin
            case (state)
                IDLE: begin
                    uart_tx <= 1'b1;
                    bit_cnt <= 3'd0;
                    byte_cnt <= 2'd0;
                    if (tx_start) begin
                        state <= START;
                        tx_busy <= 1'b1;
                        tx_data_reg <= tx_data;
                    end else begin
                        tx_busy <= 1'b0;
                    end
                end

                START: begin
                    uart_tx <= 1'b0;  // 起始位：拉低
                    if (baud_pulse) begin
                        state <= DATA;
                        bit_cnt <= 3'd0;
                    end
                end

                DATA: begin
                    uart_tx <= current_byte[bit_cnt];  // 发送当前位
                    if (baud_pulse) begin
                        if (bit_cnt == 3'd7) begin
                            state <= STOP;
                        end else begin
                            bit_cnt <= bit_cnt + 1;
                        end
                    end
                end

                STOP: begin
                    uart_tx <= 1'b1;  // 停止位：拉高
                    if (baud_pulse) begin
                        if (byte_cnt == 2'd3) begin
                            // 4个字节都发送完毕
                            state <= IDLE;
                            tx_busy <= 1'b0;
                        end else begin
                            // 继续发送下一个字节
                            byte_cnt <= byte_cnt + 1;
                            state <= START;
                        end
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
