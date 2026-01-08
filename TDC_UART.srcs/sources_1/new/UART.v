// =============================================================================
// UART 顶层模块 - 适用于 Kintex-7 XC7K325FFG900-2
// 系统时钟：200MHz
// 波特率：115200 (可通过参数修改)
// 数据宽度：32位
// =============================================================================
module UART #(
    parameter CLK_FREQ = 200000000,     // 系统时钟频率 200MHz
    parameter BAUD_RATE = 115200        // 波特率 115200
)(
    // 系统信号
    input           clk,                // 系统时钟 200MHz
    input           rst,                // 高电平复位
    
    // UART物理接口
    input           uart_rxd,           // UART接收引脚
    output          uart_txd,           // UART发送引脚
    
    // 发送接口
    input   [31:0]  tx_data,            // 要发送的数据 (32位)
    input           tx_start,           // 发送启动信号(脉冲)
    output          tx_busy,            // 发送忙信号
    
    // 接收接口
    output  [31:0]  rx_data,            // 接收到的数据 (32位)
    output          rx_valid            // 接收数据有效信号(脉冲)
);

    // -------------------------------------------------------------------------
    // 实例化 UART 发送模块
    // -------------------------------------------------------------------------
    uart_tx #(
        .CLK_FREQ   (CLK_FREQ),
        .BAUD_RATE  (BAUD_RATE)
    ) u_uart_tx (
        .clk        (clk),
        .rst        (rst),
        .tx_data    (tx_data),
        .tx_start   (tx_start),
        .tx_busy    (tx_busy),
        .uart_tx    (uart_txd)
    );

    // -------------------------------------------------------------------------
    // 实例化 UART 接收模块
    // -------------------------------------------------------------------------
    uart_rx #(
        .CLK_FREQ   (CLK_FREQ),
        .BAUD_RATE  (BAUD_RATE)
    ) u_uart_rx (
        .clk        (clk),
        .rst        (rst),
        .uart_rx    (uart_rxd),
        .rx_data    (rx_data),
        .rx_valid   (rx_valid)
    );

endmodule
