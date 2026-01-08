// ============================================================================
// 双通道 UART 通信控制模块 - TDC专用版 (使用异步FIFO进行CDC)
// ============================================================================
// 处理 UP 和 DOWN 两个通道的时间戳数据
// 跨时钟域：260MHz (TDC) -> 200MHz (UART)
// 替代原以太网通信模块
// ============================================================================

`timescale 1ns / 1ps

module uart_comm_ctrl_tdc #(
    parameter FINE_BITS = 13,       // 精细时间位宽
    parameter COARSE_BITS = 16,     // 粗计数位宽
    parameter CLK_FREQ = 200000000, // 系统时钟频率
    parameter BAUD_RATE = 115200    // UART 波特率
)(
    // ========================================================================
    // 时钟和复位
    // ========================================================================
    input wire                      clk_200MHz,     // UART 时钟域
    input wire                      clk_260MHz,     // TDC 时钟域
    input wire                      rst_200MHz,
    input wire                      rst_260MHz,
    
    // ========================================================================
    // UP 通道数据输入 (260MHz 域)
    // ========================================================================
    input wire                      up_valid,
    input wire [FINE_BITS-1:0]      up_fine,        // 精细时间
    input wire [COARSE_BITS-1:0]    up_coarse,      // 粗计数
    input wire [7:0]                up_id,          // 测量ID
    
    // ========================================================================
    // DOWN 通道数据输入 (260MHz 域)
    // ========================================================================
    input wire                      down_valid,
    input wire [FINE_BITS-1:0]      down_fine,
    input wire [COARSE_BITS-1:0]    down_coarse,
    input wire [7:0]                down_id,
    
    // ========================================================================
    // UART 物理接口 (200MHz 域)
    // ========================================================================
    input wire                      uart_rxd,       // UART 接收引脚
    output wire                     uart_txd,       // UART 发送引脚
    
    // ========================================================================
    // 状态和控制
    // ========================================================================
    input wire                      system_ready,
    
    // 校准控制输出
    output reg                      manual_calib_trigger,
    
    // 扫描测试控制输出
    output reg                      scan_cmd_trigger,
    output reg [10:0]               scan_cmd_param,
    
    // ========================================================================
    // 像素芯片命令输出
    // ========================================================================
    output reg                      pixel_cmd_trigger,  // 像素芯片命令触发
    output reg [7:0]                pixel_cmd_param     // 像素芯片命令参数[7:0]
                                                        // [7]=RST, [6:1]=CSA[5:0], [0]=保留
);

    // ========================================================================
    // 数据包格式定义
    // ========================================================================
    // [31:30] = 数据类型 (2'b00=UP, 2'b01=DOWN, 2'b10=保留, 2'b11=控制)
    // [29:24] = 测量ID (6位)
    // [23:11] = 精细时间 [12:0]
    // [10]    = 通道标志 (1=UP, 0=DOWN)
    // [9:0]   = 粗计数低10位
    
    localparam TYPE_UP   = 2'b00;
    localparam TYPE_DOWN = 2'b01;
    localparam TYPE_INFO = 2'b10;
    localparam TYPE_CMD  = 2'b11;
    
    // ========================================================================
    // UART 模块信号
    // ========================================================================
    reg  [31:0] uart_tx_data;
    reg         uart_tx_start;
    wire        uart_tx_busy;
    wire [31:0] uart_rx_data;
    wire        uart_rx_valid;
    
    // ========================================================================
    // UART 顶层模块实例化
    // ========================================================================
    UART #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD_RATE(BAUD_RATE)
    ) uart_inst (
        .clk(clk_200MHz),
        .rst(rst_200MHz),
        .uart_rxd(uart_rxd),
        .uart_txd(uart_txd),
        .tx_data(uart_tx_data),
        .tx_start(uart_tx_start),
        .tx_busy(uart_tx_busy),
        .rx_data(uart_rx_data),
        .rx_valid(uart_rx_valid)
    );
    
    // ========================================================================
    // UP 通道异步FIFO - CDC处理（260MHz -> 200MHz）
    // ========================================================================
    wire [63:0] up_fifo_din, up_fifo_dout;
    wire        up_fifo_full, up_fifo_empty;
    reg         up_fifo_rden;
    wire [3:0]  up_fifo_unused0;
    wire [8:0]  up_fifo_unused1, up_fifo_unused2;
    
    // 打包数据（260MHz域）
    assign up_fifo_din = {
        26'b0,                          // [63:38] 填充
        1'b1,                           // [37] up通道标记
        up_id,                          // [36:29]
        up_coarse,                      // [28:13]
        up_fine                         // [12:0]
    };
    
    // 异步FIFO实例 - UP通道
    FIFO_DUALCLOCK_MACRO #(
        .DATA_WIDTH(64),
        .FIFO_SIZE("36Kb"),
        .FIRST_WORD_FALL_THROUGH("TRUE")
    ) up_async_fifo (
        .WRCLK(clk_260MHz),
        .RDCLK(clk_200MHz),
        .RST(rst_200MHz | rst_260MHz),
        .DI(up_fifo_din),
        .WREN(up_valid),                // 260MHz域写入
        .DO(up_fifo_dout),
        .RDEN(up_fifo_rden),            // 200MHz域读取
        .EMPTY(up_fifo_empty),
        .FULL(up_fifo_full),
        .ALMOSTEMPTY(up_fifo_unused0[0]),
        .ALMOSTFULL(up_fifo_unused0[1]),
        .RDERR(up_fifo_unused0[2]),
        .WRERR(up_fifo_unused0[3]),
        .RDCOUNT(up_fifo_unused1),
        .WRCOUNT(up_fifo_unused2)
    );
    
    // 解包数据（200MHz域）
    wire [7:0]              up_id_200;
    wire [COARSE_BITS-1:0]  up_coarse_200;
    wire [FINE_BITS-1:0]    up_fine_200;
    wire                    flag_up_channel;
    assign flag_up_channel = up_fifo_dout[37];
    assign up_id_200       = up_fifo_dout[36:29];
    assign up_coarse_200   = up_fifo_dout[28:13];
    assign up_fine_200     = up_fifo_dout[12:0];
    
    // ========================================================================
    // DOWN 通道异步FIFO - CDC处理（260MHz -> 200MHz）
    // ========================================================================
    wire [63:0] down_fifo_din, down_fifo_dout;
    wire        down_fifo_full, down_fifo_empty;
    reg         down_fifo_rden;
    wire [3:0]  down_fifo_unused0;
    wire [8:0]  down_fifo_unused1, down_fifo_unused2;
    
    // 打包数据（260MHz域）
    assign down_fifo_din = {
        26'b0,                          // [63:38] 填充
        1'b0,                           // [37] down通道标记
        down_id,                        // [36:29]
        down_coarse,                    // [28:13]
        down_fine                       // [12:0]
    };
    
    // 异步FIFO实例 - DOWN通道
    FIFO_DUALCLOCK_MACRO #(
        .DATA_WIDTH(64),
        .FIFO_SIZE("36Kb"),
        .FIRST_WORD_FALL_THROUGH("TRUE")
    ) down_async_fifo (
        .WRCLK(clk_260MHz),
        .RDCLK(clk_200MHz),
        .RST(rst_200MHz | rst_260MHz),
        .DI(down_fifo_din),
        .WREN(down_valid),              // 260MHz域写入
        .DO(down_fifo_dout),
        .RDEN(down_fifo_rden),          // 200MHz域读取
        .EMPTY(down_fifo_empty),
        .FULL(down_fifo_full),
        .ALMOSTEMPTY(down_fifo_unused0[0]),
        .ALMOSTFULL(down_fifo_unused0[1]),
        .RDERR(down_fifo_unused0[2]),
        .WRERR(down_fifo_unused0[3]),
        .RDCOUNT(down_fifo_unused1),
        .WRCOUNT(down_fifo_unused2)
    );
    
    // 解包数据（200MHz域）
    wire [7:0]              down_id_200;
    wire [COARSE_BITS-1:0]  down_coarse_200;
    wire [FINE_BITS-1:0]    down_fine_200;
    wire                    flag_down_channel;
    assign flag_down_channel = down_fifo_dout[37];
    assign down_id_200       = down_fifo_dout[36:29];
    assign down_coarse_200   = down_fifo_dout[28:13];
    assign down_fine_200     = down_fifo_dout[12:0];
    
    // ========================================================================
    // 发送状态机（200MHz 域）- 从异步FIFO读取并通过UART发送
    // ========================================================================
    // 严格配对发送策略：等待UP和DOWN都有数据后，先发UP再发DOWN
    localparam TX_IDLE      = 3'd0;
    localparam TX_PREPARE   = 3'd1;
    localparam TX_SEND      = 3'd2;
    localparam TX_WAIT      = 3'd3;   // 等待busy拉低（在确认busy曾经拉高之后）
    localparam TX_POP       = 3'd4;
    localparam TX_WAIT_BUSY = 3'd5;   // 等待busy拉高，避免start后一拍busy尚未置位造成误判
    
    reg [2:0] tx_state;
    reg       send_up;        // 标记当前发送的是UP还是DOWN
    
    always @(posedge clk_200MHz) begin
        if (rst_200MHz) begin
            tx_state <= TX_IDLE;
            uart_tx_start <= 1'b0;
            uart_tx_data <= 32'b0;
            send_up <= 1'b0;
            up_fifo_rden <= 1'b0;
            down_fifo_rden <= 1'b0;
        end
        else begin
            // 默认值
            up_fifo_rden <= 1'b0;
            down_fifo_rden <= 1'b0;
            uart_tx_start <= 1'b0;
            
            case (tx_state)
                TX_IDLE: begin
                    // 严格配对：等待UP和DOWN都有数据时才开始发送
                    // 保证顺序：先UP后DOWN
                    if (!up_fifo_empty && !down_fifo_empty && !uart_tx_busy) begin
                        send_up <= 1'b1;  // 先发UP
                        tx_state <= TX_PREPARE;
                    end
                end
                
                TX_PREPARE: begin
                    // FWFT模式：数据已在输出端口可用
                    if (send_up) begin
                        uart_tx_data <= {
                            TYPE_UP,                    // [31:30]
                            up_id_200[5:0],             // [29:24] ID 6位
                            up_fine_200,                // [23:11] Fine 13位
                            flag_up_channel,            // [10]
                            up_coarse_200[9:0]          // [9:0] Coarse 10位
                        };
                    end else begin
                        uart_tx_data <= {
                            TYPE_DOWN,                  // [31:30]
                            down_id_200[5:0],           // [29:24] ID 6位
                            down_fine_200,              // [23:11] Fine 13位
                            flag_down_channel,          // [10]
                            down_coarse_200[9:0]        // [9:0] Coarse 10位
                        };
                    end
                    tx_state <= TX_SEND;
                end
                
                TX_SEND: begin
                    // 触发UART发送
                    uart_tx_start <= 1'b1;
                    // 发送启动后，先等待tx_busy拉高再进入等待完成的阶段
                    tx_state <= TX_WAIT_BUSY;
                end
                
                TX_WAIT_BUSY: begin
                    // 确认UART进入忙状态（busy=1），防止在busy尚未置位时误判完成
                    if (uart_tx_busy) begin
                        tx_state <= TX_WAIT;
                    end
                end

                TX_WAIT: begin
                    // 等待UART发送完成
                    if (!uart_tx_busy) begin
                        // 弹出已处理的FIFO数据
                        if (send_up) begin
                            up_fifo_rden <= 1'b1;
                        end else begin
                            down_fifo_rden <= 1'b1;
                        end
                        tx_state <= TX_POP;
                    end
                end
                
                TX_POP: begin
                    if (send_up) begin
                        // UP已发送完成，继续发送DOWN
                        send_up <= 1'b0;
                        tx_state <= TX_PREPARE;  // 复用TX_PREPARE发送DOWN
                    end
                    else begin
                        // DOWN也发送完成，一对数据发送完毕
                        tx_state <= TX_IDLE;
                    end
                end
                
                default: begin
                    tx_state <= TX_IDLE;
                end
            endcase
        end
    end
    
    // ========================================================================
    // 接收状态机（200MHz 域）- 命令解析
    // ========================================================================
    /*
    UART 接收数据格式 (32位)：
    [31]     : 1=重新校准; 0=扫描测试/像素芯片控制
    [30]     : 扫描模式 (0=单步, 1=全扫描)
    [29:28]  : 通道选择 (00=无, 10=UP, 01=DOWN, 11=UP+DOWN)
    [27:20]  : 相位参数（8位）
    [19]     : 像素芯片RST控制（产生复位脉冲）
    [18:13]  : 像素芯片CSA控制（Pixel_CSA_5~0，产生激励脉冲）
    [12]     : 保留（固定为0）
    [11:0]   : 保留
    
    scan_cmd_param 输出格式（11位）：
    [10]     : 扫描模式 (0=单步, 1=全扫描)
    [9:8]    : 通道选择 (00=无, 10=UP, 01=DOWN, 11=UP+DOWN)
    [7:0]    : 相位参数
    
    pixel_cmd_param 输出格式（8位）：
    [7]      : RST控制
    [6:1]    : CSA[5:0]控制
    [0]      : 保留
    */
    
    localparam RX_IDLE    = 2'd0;
    localparam RX_PROCESS = 2'd1;
    localparam RX_DONE    = 2'd2;
    
    reg [1:0] rx_state;
    reg [31:0] rx_data_latch;
    
    always @(posedge clk_200MHz) begin
        if (rst_200MHz) begin
            rx_state <= RX_IDLE;
            manual_calib_trigger <= 1'b0;
            scan_cmd_trigger <= 1'b0;
            scan_cmd_param <= 11'b0;
            pixel_cmd_trigger <= 1'b0;
            pixel_cmd_param <= 8'b0;
            rx_data_latch <= 32'b0;
        end
        else begin
            // 默认清除触发信号
            manual_calib_trigger <= 1'b0;
            scan_cmd_trigger <= 1'b0;
            pixel_cmd_trigger <= 1'b0;
            
            case (rx_state)
                RX_IDLE: begin
                    // 检测到UART接收有效数据
                    if (uart_rx_valid) begin
                        rx_data_latch <= uart_rx_data;
                        rx_state <= RX_PROCESS;
                    end
                end
                
                RX_PROCESS: begin
                    case (rx_data_latch[31])
                        1'b1: begin
                            // 重新校准命令
                            manual_calib_trigger <= 1'b1;
                        end
                        1'b0: begin
                            // 扫描模式命令：提取 [30:20] 共 11 位
                            scan_cmd_param <= rx_data_latch[30:20];
                            scan_cmd_trigger <= 1'b1;
                            
                            // 像素芯片控制：检查 [19:12] 是否有控制信号
                            if (rx_data_latch[19:12] != 8'b0) begin
                                pixel_cmd_param <= rx_data_latch[19:12];
                                pixel_cmd_trigger <= 1'b1;
                            end
                        end
                    endcase
                    rx_state <= RX_DONE;
                end
                
                RX_DONE: begin
                    rx_state <= RX_IDLE;
                end
                
                default: begin
                    rx_state <= RX_IDLE;
                end
            endcase
        end
    end
    
    
    // // ========================================================================
    // // ILA: ila_uart_tx_pixel - 监控UART发送和像素数据传输
    // // ========================================================================
    // // 监控信号：
    // //   - uart_tx_data[31:0]     : 发送的数据包
    // //   - tx_state[2:0]          : 发送状态机
    // //   - send_up                : 当前发送UP(1)还是DOWN(0)
    // //   - up_fifo_empty          : UP FIFO空标志
    // //   - down_fifo_empty        : DOWN FIFO空标志
    // //   - up_fifo_rden           : UP FIFO读使能
    // //   - down_fifo_rden         : DOWN FIFO读使能
    // //   - uart_tx_start          : UART发送启动
    // //   - uart_tx_busy           : UART发送忙
    // // ========================================================================
    // ila_uart_tx_pixel ila_uart_tx_pixel_inst (
    //     .clk(clk_200MHz),
    //     .probe0({
    //         uart_tx_data,           // [63:32] 发送数据包 32bit
    //         22'b0,                  // [31:10] 保留
    //         uart_tx_busy,           // [9]     UART发送忙
    //         uart_tx_start,          // [8]     UART发送启动
    //         down_fifo_rden,         // [7]     DOWN FIFO读使能
    //         up_fifo_rden,           // [6]     UP FIFO读使能
    //         down_fifo_empty,        // [5]     DOWN FIFO空
    //         up_fifo_empty,          // [4]     UP FIFO空
    //         send_up,                // [3]     当前发送UP/DOWN
    //         tx_state               // [2:0]   发送状态机全3位
    //     })
    // );

endmodule
