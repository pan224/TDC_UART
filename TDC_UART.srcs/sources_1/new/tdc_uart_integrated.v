// ============================================================================
// TDC UART 集成系统
// ============================================================================
// 整合新TDC测量核心与UART通信功能
// 测量 UP 和 DOWN 信号在 RESET 后的绝对时间
// 替代原以太网集成系统
// ============================================================================

`timescale 1ns / 1ps
`include "tdc_pkg.vh"


module tdc_uart_integrated #(
    parameter CLK_FREQ = 200000000,     // 系统时钟频率
    parameter BAUD_RATE = 115200        // UART 波特率
)(
    // ========================================================================
    // 系统时钟和复位
    // ========================================================================
    input  wire         sys_clk_200MHz,     // 系统时钟 200MHz
    input  wire         sys_reset,          // 系统复位
    
    // ========================================================================
    // TDC 测量信号
    // ========================================================================
    input  wire         signal_up,          // UP 信号
    input  wire         signal_down,        // DOWN 信号
    input  wire         tdc_reset_trigger,  // TDC 复位触发（时间基准）
    
    // 扫描测试使能（高电平启用扫描测试模式）
    input  wire         scan_test_en,       // 扫描测试使能
    
    // ========================================================================
    // UART 物理接口 (200MHz 时钟域)
    // ========================================================================
    input  wire         uart_rxd,           // UART 接收引脚
    output wire         uart_txd,           // UART 发送引脚
    
    // ========================================================================
    // 像素芯片接口
    // ========================================================================
    output wire [5:0]   Pixel_CSA,          // 像素芯片激励信号[5:0]
    output wire         Pixel_RST,          // 像素芯片复位信号(低有效)

    // ========================================================================
    // 调试输出
    // ========================================================================
    output wire         tdc_ready_out       // TDC就绪状态输出
);

    // ========================================================================
    // 参数定义
    // ========================================================================
    // 260MHz 时钟周期 = 3846ps (~3.85ns)
    localparam CLK_PERIOD_PS = `CLK_IN_PS;
    
    // 粗计数位宽（16位粗计数 + 13位精细 = 29位，适合32位传输）
    localparam COARSE_BITS = 16;        // 粗计数 16位（0-65535 周期 = 0-252us @ 260MHz）
    
    // ========================================================================
    // 时钟生成模块
    // ========================================================================
    wire        clk_260MHz;             // TDC 工作时钟 260MHz
    wire        clk_260MHz_p0;          // TDC 0度相位时钟
    wire        clk_260MHz_p90;         // TDC 90度相位时钟
    wire        clk_260MHz_p180;        // TDC 180度相位时钟
    wire        clk_260MHz_p270;        // TDC 270度相位时钟
    
    tdc_clock_manager clock_mgr_inst (
        .sys_clk_200MHz(sys_clk_200MHz),
        .clk_260MHz(clk_260MHz),
        .clk_260MHz_p0(clk_260MHz_p0),
        .clk_260MHz_p90(clk_260MHz_p90),
        .clk_260MHz_p180(clk_260MHz_p180),
        .clk_260MHz_p270(clk_260MHz_p270)
    );
    
    // ========================================================================
    // 复位同步模块
    // ========================================================================
    wire        rst_260MHz;
    wire        rst_200MHz;
    
    tdc_reset_sync reset_sync_inst (
        .sys_reset(sys_reset),
        .clk_260MHz(clk_260MHz),
        .clk_200MHz(sys_clk_200MHz),
        .rst_260MHz(rst_260MHz),
        .rst_200MHz(rst_200MHz)
    );
    
    // ========================================================================
    // TDC 通道实例化
    // ========================================================================
    // 通道1 (UP信号)
    wire        ch1_ready, ch1_valid;
    wire [12:0] ch1_time_fine;

    // 通道2 (DOWN信号)
    wire        ch2_ready, ch2_valid;
    wire [12:0] ch2_time_fine;

    // 就绪信号
    wire tdc_ready = ch1_ready & ch2_ready;
    
    // ========================================================================
    // 跨时钟域同步模块
    // ========================================================================
    wire        manual_calib_trigger_200;   // 200MHz 域校准触发
    wire        manual_calib_trigger_260;   // 260MHz 域校准触发
    wire        scan_cmd_trigger_200;       // 200MHz 域扫描命令
    wire        scan_cmd_trigger_260;       // 260MHz 域扫描命令
    wire [10:0] scan_cmd_param_200;         // 200MHz 域扫描参数
    wire [10:0] scan_cmd_param_260;         // 260MHz 域扫描参数
    wire        pixel_cmd_trigger_200;      // 200MHz 域像素命令触发
    wire [7:0]  pixel_cmd_param_200;        // 200MHz 域像素命令参数
    
    tdc_cdc_sync cdc_sync_inst (
        .clk_260MHz(clk_260MHz),
        .clk_200MHz(sys_clk_200MHz),
        .rst_260MHz(rst_260MHz),
        .rst_200MHz(rst_200MHz),
        .manual_calib_trigger_200(manual_calib_trigger_200),
        .scan_cmd_trigger_200(scan_cmd_trigger_200),
        .scan_cmd_param_200(scan_cmd_param_200),
        .manual_calib_trigger_260(manual_calib_trigger_260),
        .scan_cmd_trigger_260(scan_cmd_trigger_260),
        .scan_cmd_param_260(scan_cmd_param_260)
    );
    
    // ========================================================================
    // 像素芯片激励控制模块 (200MHz 域)
    // ========================================================================
    pixel_stimulus_ctrl #(
        .PULSE_LOW_TIME(8'd8),        // 脉冲低电平时间：8 @ 200MHz = 40ns
        .PULSE_HIGH_TIME(8'd93),      // 脉冲高电平时间：93 @ 200MHz = 465ns
        .PULSE_COUNT(14'd100),      // 每次指令产生的脉冲数量
        .RST_WAIT_TIME(8'd100),       // 复位后等待时间：100 @ 200MHz = 500ns
        .PULSE_GAP_TIME(16'd40000)      // 脉冲间隔时间：500 @ 200MHz = 2.5us
    ) pixel_stimulus_inst (
        .clk(sys_clk_200MHz),
        .rst(rst_200MHz),
        .pixel_cmd_trigger(pixel_cmd_trigger_200),
        .pixel_cmd_param(pixel_cmd_param_200),
        .Pixel_CSA(Pixel_CSA),
        .Pixel_RST(Pixel_RST)
    );
    
    // ========================================================================
    // 校准控制模块
    // ========================================================================
    wire        calib_sel;
    wire        ro_clk;
    
    tdc_calib_ctrl calib_ctrl_inst (
        .clk_260MHz(clk_260MHz),
        .rst_260MHz(rst_260MHz),
        .sys_reset(sys_reset),
        .tdc_ready(tdc_ready),
        .manual_calib_trigger(manual_calib_trigger_260),
        .calib_sel(calib_sel),
        .ro_clk(ro_clk)
    );
    
    // ========================================================================
    // 扫描测试控制模块
    // ========================================================================
    wire        scan_running;
    wire [7:0]  scan_status;
    wire        test_pulse_up;
    wire        test_pulse_down;
    wire        tdc_reset_scan;

    tdc_scan_ctrl scan_ctrl_inst (
        .clk_260MHz(clk_260MHz),
        .sys_reset(rst_260MHz),
        .scan_cmd_trigger(scan_cmd_trigger_260),
        .scan_cmd_param(scan_cmd_param_260),
        .scan_running(scan_running),
        .scan_status(scan_status),
        .test_pulse_up(test_pulse_up),
        .test_pulse_down(test_pulse_down),
        .tdc_reset_trigger(tdc_reset_scan)
    );
    
    // ========================================================================
    // 信号多路复用模块
    // ========================================================================
    wire signal_up_mux;
    wire signal_down_mux;
    wire tdc_reset_mux;
    
    tdc_signal_mux signal_mux_inst (
        .signal_up(signal_up),
        .signal_down(signal_down),
        .tdc_reset_trigger(tdc_reset_trigger),
        .scan_test_en(scan_test_en),
        .test_pulse_up(test_pulse_up),
        .test_pulse_down(test_pulse_down),
        .tdc_reset_scan(tdc_reset_scan),
        .calib_sel(calib_sel),
        .ro_clk(ro_clk),
        .signal_up_mux(signal_up_mux),
        .signal_down_mux(signal_down_mux),
        .tdc_reset_mux(tdc_reset_mux)
    );
    
    // ========================================================================
    // 时间戳捕获模块
    // ========================================================================
    wire                    up_valid;
    wire [12:0]             up_fine;
    wire [COARSE_BITS-1:0]  up_coarse;
    wire [7:0]              up_id;
    wire                    down_valid;
    wire [12:0]             down_fine;
    wire [COARSE_BITS-1:0]  down_coarse;
    wire [7:0]              down_id;
    wire [7:0]              measurement_id;
    
    tdc_timestamp_capture #(
        .COARSE_BITS(COARSE_BITS)
    ) timestamp_capture_inst (
        .clk_260MHz(clk_260MHz),
        .rst_260MHz(rst_260MHz),
        .ch1_valid(ch1_valid),
        .ch1_time_fine(ch1_time_fine),
        .ch2_valid(ch2_valid),
        .ch2_time_fine(ch2_time_fine),
        .tdc_reset_trigger(tdc_reset_mux),
        .up_valid(up_valid),
        .up_fine(up_fine),
        .up_coarse(up_coarse),
        .up_id(up_id),
        .down_valid(down_valid),
        .down_fine(down_fine),
        .down_coarse(down_coarse),
        .down_id(down_id),
        .measurement_id(measurement_id)
    );
    
    // ========================================================================
    // TDC 通道1实例化 (UP 信号测量)
    // ========================================================================
    channel #(
        .CH("ch_up")
    ) channel_up_inst (
        .CLK_P0(clk_260MHz_p0),
        .CLK_P90(clk_260MHz_p90),
        .CLK_P180(clk_260MHz_p180),
        .CLK_P270(clk_260MHz_p270),
        .RST(rst_260MHz),
        .clk_period(CLK_PERIOD_PS),
        .sensor(signal_up_mux),
        .calib_en(calib_sel),
        .ready(ch1_ready),
        .valid(ch1_valid),
        .time_out(ch1_time_fine)
    );
    
    // ========================================================================
    // TDC 通道2实例化 (DOWN 信号测量)
    // ========================================================================
    channel #(
        .CH("ch_down")
    ) channel_down_inst (
        .CLK_P0(clk_260MHz_p0),
        .CLK_P90(clk_260MHz_p90),
        .CLK_P180(clk_260MHz_p180),
        .CLK_P270(clk_260MHz_p270),
        .RST(rst_260MHz),
        .clk_period(CLK_PERIOD_PS),
        .sensor(signal_down_mux),
        .calib_en(calib_sel),
        .ready(ch2_ready),
        .valid(ch2_valid),
        .time_out(ch2_time_fine)
    );
    
    // ========================================================================
    // UART 通信控制模块 (双通道版)
    // ========================================================================
    uart_comm_ctrl_tdc #(
        .FINE_BITS(13),
        .COARSE_BITS(COARSE_BITS),
        .CLK_FREQ(CLK_FREQ),
        .BAUD_RATE(BAUD_RATE)
    ) uart_comm_inst (
        .clk_200MHz(sys_clk_200MHz),
        .clk_260MHz(clk_260MHz),
        .rst_200MHz(rst_200MHz),
        .rst_260MHz(rst_260MHz),
        .up_valid(up_valid),
        .up_fine(up_fine),
        .up_coarse(up_coarse),
        .up_id(up_id),
        .down_valid(down_valid),
        .down_fine(down_fine),
        .down_coarse(down_coarse),
        .down_id(down_id),
        .uart_rxd(uart_rxd),
        .uart_txd(uart_txd),
        .system_ready(tdc_ready),
        .manual_calib_trigger(manual_calib_trigger_200),
        .scan_cmd_trigger(scan_cmd_trigger_200),
        .scan_cmd_param(scan_cmd_param_200),
        .pixel_cmd_trigger(pixel_cmd_trigger_200),
        .pixel_cmd_param(pixel_cmd_param_200)
    );
    
    // ========================================================================
    // 调试输出
    // ========================================================================
    assign tdc_ready_out = tdc_ready;

endmodule
