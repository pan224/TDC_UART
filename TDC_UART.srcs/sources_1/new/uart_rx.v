// -----------------------------------------------------------------------------
// 子模块：UART 接收 (RX) - 32位数据宽度
// 使用计数器简化状态机
// -----------------------------------------------------------------------------
module uart_rx #(
    parameter CLK_FREQ = 200000000,
    parameter BAUD_RATE = 115200
)(
    input           clk,
    input           rst,
    input           uart_rx,
    output reg [31:0] rx_data,
    output reg      rx_valid
);

    // 计算分频计数器的最大值
    localparam BAUD_CNT_MAX = CLK_FREQ / BAUD_RATE;
    localparam BAUD_CNT_HALF = BAUD_CNT_MAX / 2;

    // 状态机状态定义
    localparam IDLE      = 3'd0;
    localparam START     = 3'd1;
    localparam DATA      = 3'd2;
    localparam STOP      = 3'd3;
    localparam WAIT_NEXT = 3'd4;  // 等待下一个字节

    reg [2:0]  state;
    reg [31:0] baud_cnt;
    reg [31:0] rx_data_reg;  // 数据缓存 (32位)
    reg [2:0]  bit_cnt;      // 位计数器 (0-7)
    reg [1:0]  byte_cnt;     // 字节计数器 (0-3)
    
    // 对输入的 uart_rx 进行双寄存器同步，消除亚稳态
    reg uart_rx_d1, uart_rx_d2, uart_rx_d3;
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            uart_rx_d1 <= 1'b1;
            uart_rx_d2 <= 1'b1;
            uart_rx_d3 <= 1'b1;
        end else begin
            uart_rx_d1 <= uart_rx;
            uart_rx_d2 <= uart_rx_d1;
            uart_rx_d3 <= uart_rx_d2;
        end
    end
    
    // 下降沿检测：用于精确捕获起始位开始时刻
    wire rx_falling_edge = uart_rx_d3 & ~uart_rx_d2;

    // 波特率计数器逻辑
    reg baud_cnt_en;
    always @(posedge clk or posedge rst) begin
        if (rst)
            baud_cnt <= 0;
        else if (!baud_cnt_en)
            baud_cnt <= 0;
        else if (baud_cnt >= BAUD_CNT_MAX - 1)
            baud_cnt <= 0;
        else
            baud_cnt <= baud_cnt + 1;
    end

    // 采样脉冲：在数据位中间采样
    wire sample_pulse = (baud_cnt == BAUD_CNT_HALF);
    // 状态跳转脉冲
    wire baud_pulse = (baud_cnt == BAUD_CNT_MAX - 1);

    // 计算当前接收位在32位数据中的位置
    wire [4:0] bit_index = {byte_cnt, bit_cnt};  // 0-31

    // 主状态机逻辑
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= IDLE;
            rx_data <= 32'd0;
            rx_valid <= 1'b0;
            rx_data_reg <= 32'd0;
            bit_cnt <= 3'd0;
            byte_cnt <= 2'd0;
            baud_cnt_en <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    rx_valid <= 1'b0;
                    bit_cnt <= 3'd0;
                    byte_cnt <= 2'd0;      // 在 IDLE 才重置 byte_cnt
                    rx_data_reg <= 32'd0;  // 清空数据缓存
                    baud_cnt_en <= 1'b0;
                    // 检测到起始位下降沿（更精确）
                    if (rx_falling_edge) begin
                        state <= START;
                        baud_cnt_en <= 1'b1;
                    end
                end

                START: begin
                    // 等待起始位结束，然后进入数据接收
                    // 使用 baud_pulse 确保进入 DATA 时 baud_cnt 归零
                    // 这样第一个 sample_pulse 采样 D0 时 bit_cnt=0
                    if (baud_pulse) begin
                        state <= DATA;
                        bit_cnt <= 3'd0;
                    end
                end

                DATA: begin
                    // 在中间采样数据位
                    if (sample_pulse) begin
                        rx_data_reg[bit_index] <= uart_rx_d2;
                    end
                    if (baud_pulse) begin
                        if (bit_cnt == 3'd7) begin
                            state <= STOP;
                        end else begin
                            bit_cnt <= bit_cnt + 1;
                        end
                    end
                end

                STOP: begin
                    // 在停止位中间就切换状态，避免错过下一个字节的起始位下降沿
                    if (sample_pulse) begin
                        if (byte_cnt == 2'd3) begin
                            // 4个字节都接收完毕
                            rx_data <= rx_data_reg;
                            rx_valid <= 1'b1;
                            state <= IDLE;
                            baud_cnt_en <= 1'b0;
                        end else begin
                            // 还有字节需要接收，等待下一个起始位
                            byte_cnt <= byte_cnt + 1;
                            state <= WAIT_NEXT;
                            baud_cnt_en <= 1'b0;
                        end
                    end
                end

                WAIT_NEXT: begin
                    // 等待下一个字节的起始位，不重置 byte_cnt
                    rx_valid <= 1'b0;
                    bit_cnt <= 3'd0;
                    // 检测到起始位下降沿（更精确）
                    if (rx_falling_edge) begin
                        state <= START;
                        baud_cnt_en <= 1'b1;
                    end
                end

                default: begin
                    state <= IDLE;
                    baud_cnt_en <= 1'b0;
                end
            endcase
        end
    end

    // ========================================================================
    // ILA 调试模块 - 分离 RX 和 TX 监控
    // ========================================================================
    
    // ========================================================================
    // ILA_RX: ila_uart_rx - 监控接收相关信号
    // ========================================================================
    // probe0 宽度: 73 bits
    // ========================================================================
    // ila_uart_rx ila_uart_rx_inst (
    //     .clk(clk),
    //     .probe0({
    //         bit_index,           // [72:68] 当前接收位索引 0-31
    //         rx_data,           // [67:36] 接收数据 32bit
    //         rx_valid,          // [35]    接收有效
    //         sample_pulse,
    //         baud_pulse,              // [34:33] 波特率采样脉冲和状态跳转脉冲
    //         rx_data_reg,          // [32:1]  接收锁存数据 32bit
    //         uart_rx                // [0]     UART RX引脚
    //     })
    // );

endmodule
