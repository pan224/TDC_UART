// ============================================================================
// TDC UART 测试顶层模块
// ============================================================================
// 整合 TDC 测量系统与 UART 通信
// 替代原 test_tdc_eth.v 架构
// ============================================================================

`timescale 1ns / 1ps

module test_tdc_uart(
    input wire CPU_RESET,
    input wire SYS_CLK_P,           // 200MHz 差分时钟
    input wire SYS_CLK_N,

    // ========================================================================
    // UART 接口
    // ========================================================================
    input  wire UART_RXD,           // UART 接收引脚
    output wire UART_TXD,           // UART 发送引脚
    
    // ========================================================================
    // 像素芯片接口
    // ========================================================================
    output wire [5:0] PIXEL_CSA,    // 像素芯片激励信号[5:0]
    output wire       PIXEL_RST,    // 像素芯片复位信号(高有效)
    output wire       SIGNAL_IN_DOWN,   // 像素芯片的DOWN 信号输入，手动接地处理，UP信号像素芯片内部已经自动接地
    // ========================================================================
    // TDC 测量信号 (可选外部输入)
    // ========================================================================
    input  wire SIGNAL_UP,          // UP 信号输入
    input  wire SIGNAL_DOWN,        // DOWN 信号输入
    // input  wire TDC_RESET,          // TDC 复位触发
    
    // ========================================================================
    // 状态指示
    // ========================================================================
    output wire TDC_READY_LED       // TDC 就绪 LED 指示
);

    // ========================================================================
    // 参数定义
    // ========================================================================
    parameter CLK_FREQ  = 200000000;    // 200MHz
    parameter BAUD_RATE = 115200;       // UART 波特率

    // ========================================================================
    // 内部信号声明
    // ========================================================================
    wire reset, sys_clk;
    wire clk_50MHz, clk_100MHz, clk_10MHz, clk_250MHz;
    // wire SIGNAL_UP;          // UP 信号输入
    // wire SIGNAL_DOWN;        // DOWN 信号输入
    wire TDC_RESET;          // TDC 复位触发和像素芯片复位信号
    wire tdc_ready;
    wire PIXEL_RST_wire;

    assign SIGNAL_IN_DOWN = 1'b0; // 默认接地

    // ========================================================================
    // 时钟生成 (差分到单端) 和复位
    // ========================================================================
    IBUFDS #(
        .DIFF_TERM("FALSE"),
        .IBUF_LOW_PWR("TRUE")
    ) IBUFDS_sys_clk (
        .I(SYS_CLK_P),
        .IB(SYS_CLK_N),
        .O(sys_clk)
    );

    assign PIXEL_RST = PIXEL_RST_wire;// 像素芯片复位信号，低有效
    assign TDC_RESET = ~PIXEL_RST_wire; // TDC 复位触发（时间基准）,高有效
    // ========================================================================
    // 上电复位生成 - 等待时钟稳定后释放复位
    // ========================================================================
    // CPU_RESET 是低电平有效（与以太网版本一致：FORCE_RST(~CPU_RESET)）
    // MMCM/PLL 典型锁定时间约 100us，200MHz 下需要约 20000 个时钟周期
    // 使用 24 位计数器，延迟约 80ms 确保稳定
    wire       force_rst;
    reg [23:0] reset_cnt;
    reg        reset_done;
    wire       reset_internal;
    
    // CPU_RESET 低电平有效，取反变成高电平触发
    assign force_rst = ~CPU_RESET;
    
    always @(posedge sys_clk or posedge force_rst) begin
        if (force_rst) begin
            reset_cnt <= 24'd0;
            reset_done <= 1'b0;
        end else begin
            if (!reset_done) begin
                if (reset_cnt == 24'hFFFFFF) begin
                    reset_done <= 1'b1;
                end else begin
                    reset_cnt <= reset_cnt + 1'b1;
                end
            end
        end
    end
    
    // 复位信号：force_rst 或 上电延迟期间都保持复位
    assign reset_internal = force_rst | (~reset_done);
    assign reset = reset_internal;

    // ========================================================================
    // TDC UART 集成系统
    // ========================================================================
    tdc_uart_integrated #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD_RATE(BAUD_RATE)
    ) tdc_uart_inst (
        // 系统时钟和复位
        .sys_clk_200MHz(sys_clk),
        .sys_reset(reset),
        
        // TDC 测量信号
        .signal_up(SIGNAL_UP),
        .signal_down(SIGNAL_DOWN),
        .tdc_reset_trigger(TDC_RESET),// TDC 复位触发，高有效
        
        // 扫描测试使能 (默认启用)1'b1表示使用内部信号，1'b0表示使用外部信号
        .scan_test_en(1'b0),
        
        // UART 接口
        .uart_rxd(UART_RXD),
        .uart_txd(UART_TXD),
        
        // 像素芯片接口
        .Pixel_CSA(PIXEL_CSA),
        .Pixel_RST(PIXEL_RST_wire),// 像素芯片复位信号,低有效
        
        // 调试输出
        .tdc_ready_out(tdc_ready)
    );

    // ========================================================================
    // 状态输出
    // ========================================================================
    assign TDC_READY_LED = tdc_ready;


//    // ========================================================================
//    // ILA 信号监控 (用于调试)    
//     ila_test ila_inst (
//         .clk(sys_clk), // 输入时钟
//         .probe0({PIXEL_CSA,PIXEL_RST})// 像素芯片激励信号
//     );

endmodule
