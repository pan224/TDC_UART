// ============================================================================
// 像素芯片激励控制模块
// ============================================================================
// 处理像素芯片的激励脉冲生成
// 接收命令触发信号和参数，生成固定宽度的脉冲
// ============================================================================

`timescale 1ns / 1ps

module pixel_stimulus_ctrl #(
    parameter PULSE_LOW_TIME = 8'd8,        // 脉冲低电平时间：8 @ 200MHz = 40ns
    parameter PULSE_HIGH_TIME = 8'd93,      // 脉冲高电平时间：93 @ 200MHz = 465ns
    parameter PULSE_COUNT = 14'd10000,      // 每次指令产生的脉冲数量
    parameter RST_WAIT_TIME = 8'd100,       // 复位后等待时间：100 @ 200MHz = 500ns
    parameter PULSE_GAP_TIME = 16'd40000    // 脉冲间隔时间：40000 @ 200MHz = 200us（等待UART发送完成）
)(
    // 时钟和复位
    input  wire         clk,            // 系统时钟 (200MHz)
    input  wire         rst,            // 复位信号
    
    // 命令输入
    input  wire         pixel_cmd_trigger,  // 像素命令触发（单周期脉冲）
    input  wire [7:0]   pixel_cmd_param,    // 像素命令参数
                                            // [7] = RST控制
                                            // [6:1] = CSA[5:0]控制
                                            // [0] = 保留
    
    // 像素芯片输出
    output reg  [5:0]   Pixel_CSA,      // 像素芯片激励信号[5:0]
    output reg          Pixel_RST       // 像素芯片复位信号（低有效）
);

    // ========================================================================
    // 状态机定义
    // ========================================================================
    localparam IDLE         = 3'd0;     // 空闲状态
    localparam RST_PULSE    = 3'd1;     // 执行复位脉冲序列
    localparam RST_WAIT     = 3'd2;     // 复位后等待
    localparam CSA_PULSE    = 3'd3;     // 执行激励脉冲序列
    localparam CSA_GAP      = 3'd4;     // 脉冲间隔等待（等待UART发送）
    
    reg [2:0]   state;                  // 状态寄存器
    reg [7:0]   pulse_counter;          // 单个脉冲周期内的计数器
    reg [15:0]  gap_counter;            // 脉冲间隔计数器
    reg [13:0]  pulse_num_counter;      // 脉冲数量计数器（支持0-16383）
    reg [5:0]   csa_cmd_latch;          // 锁存的CSA命令
    reg         rst_cmd_flag;           // 标记本次命令是否包含RST
    
    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            pulse_counter <= 8'b0;
            gap_counter <= 16'b0;
            pulse_num_counter <= 14'b0;
            csa_cmd_latch <= 6'b0;
            rst_cmd_flag <= 1'b0;
            Pixel_CSA <= 6'b0;
            Pixel_RST <= 1'b1;  // 复位时默认高电平
        end
        else begin
            case (state)
                IDLE: begin
                    // 空闲状态，RST保持高电平，CSA输出低电平
                    Pixel_RST <= 1'b1;
                    Pixel_CSA <= 6'b0;
                    
                    // 等待命令触发
                    if (pixel_cmd_trigger) begin
                        pulse_counter <= 8'b0;
                        pulse_num_counter <= 14'b0;
                        
                        // 判断是否有复位命令
                        if (pixel_cmd_param[7]) begin
                            // 有复位命令，产生一个低电平脉冲
                            Pixel_RST <= 1'b0;  // 开始低电平脉冲
                            rst_cmd_flag <= 1'b1;
                            // 锁存CSA命令（如果有的话）
                            csa_cmd_latch <= pixel_cmd_param[6:1];
                            state <= RST_PULSE;
                        end
                        else if (pixel_cmd_param[6:1] != 6'b0) begin
                            // 只有CSA激励命令，RST保持高电平
                            rst_cmd_flag <= 1'b0;
                            csa_cmd_latch <= pixel_cmd_param[6:1];
                            state <= CSA_PULSE;
                        end
                        // else: 无有效命令，保持IDLE
                    end
                end
                
                RST_PULSE: begin
                    // 产生低电平脉冲（40ns低 + 465ns高 = 505ns）
                    pulse_counter <= pulse_counter + 1'b1;
                    
                    // 脉冲波形生成：40ns低 + 465ns恢复高
                    if (pulse_counter < PULSE_LOW_TIME) begin
                        Pixel_RST <= 1'b0;  // 低电平（复位动作）
                    end
                    else if (pulse_counter < (PULSE_LOW_TIME + PULSE_HIGH_TIME)) begin
                        Pixel_RST <= 1'b1;  // 恢复高电平
                    end
                    else begin
                        // 一个脉冲周期结束
                        Pixel_RST <= 1'b1;  // 确保恢复高电平
                        pulse_counter <= 8'b0;
                        
                        // 检查是否需要执行CSA激励
                        if (csa_cmd_latch != 6'b0) begin
                            state <= RST_WAIT;
                        end
                        else begin
                            // 没有CSA命令，完成操作
                            rst_cmd_flag <= 1'b0;
                            state <= IDLE;
                        end
                    end
                end
                
                RST_WAIT: begin
                    // RST保持高电平，等待后续CSA操作
                    Pixel_RST <= 1'b1;
                    pulse_counter <= pulse_counter + 1'b1;
                    
                    if (pulse_counter >= RST_WAIT_TIME) begin
                        // 等待结束，开始执行CSA激励
                        pulse_counter <= 8'b0;
                        pulse_num_counter <= 14'b0;
                        Pixel_CSA <= 6'b0;  // 初始低电平
                        state <= CSA_PULSE;
                    end
                end
                
                CSA_PULSE: begin
                    // RST保持高电平
                    Pixel_RST <= 1'b1;
                    
                    // 执行CSA激励脉冲序列
                    pulse_counter <= pulse_counter + 1'b1;
                    
                    // 脉冲波形生成：40ns低 + 465ns高
                    if (pulse_counter < PULSE_LOW_TIME) begin
                        Pixel_CSA <= 6'b0;  // 低电平
                    end
                    else if (pulse_counter < (PULSE_LOW_TIME + PULSE_HIGH_TIME)) begin
                        Pixel_CSA <= csa_cmd_latch;  // 高电平（根据命令参数）
                    end
                    else begin
                        // 一个脉冲周期结束
                        pulse_counter <= 8'b0;
                        pulse_num_counter <= pulse_num_counter + 1'b1;
                        Pixel_CSA <= 6'b0;
                        
                        // 检查是否完成所有脉冲
                        if (pulse_num_counter >= (PULSE_COUNT - 1)) begin
                            Pixel_CSA <= 6'b0;
                            Pixel_RST <= 1'b1;
                            pulse_counter <= 8'b0;
                            pulse_num_counter <= 14'b0;
                            csa_cmd_latch <= 6'b0;
                            rst_cmd_flag <= 1'b0;
                            state <= IDLE;
                        end
                        else begin
                            // 进入间隔等待状态，等待UART发送完成
                            gap_counter <= 16'b0;
                            state <= CSA_GAP;
                        end
                    end
                end
                
                CSA_GAP: begin
                    // 脉冲间隔等待，让UART有时间发送数据
                    Pixel_RST <= 1'b1;
                    Pixel_CSA <= 6'b0;
                    gap_counter <= gap_counter + 1'b1;
                    
                    if (gap_counter >= PULSE_GAP_TIME) begin
                        // 间隔结束，开始下一个脉冲
                        gap_counter <= 16'b0;
                        pulse_counter <= 8'b0;
                        state <= CSA_PULSE;
                    end
                end
                
                default: begin
                    state <= IDLE;
                    Pixel_CSA <= 6'b0;
                    Pixel_RST <= 1'b1;  // 默认高电平
                    rst_cmd_flag <= 1'b0;
                end
            endcase
        end
    end
    
    // ========================================================================
    // ILA: ila_pixel_stimulus - 调试像素芯片激励控制
    // ========================================================================
    // probe0 宽度: 64 bits (建议)
    // 监控信号：
    //   - state[2:0]              : 状态机状态
    //   - pulse_counter[7:0]      : 脉冲周期内计数器
    //   - pulse_num_counter[13:0] : 脉冲数量计数器(0-9999)
    //   - pixel_cmd_trigger       : 命令触发
    //   - pixel_cmd_param[7:0]    : 命令参数
    //   - csa_cmd_latch[5:0]      : 锁存的CSA命令
    //   - Pixel_CSA[5:0]          : CSA输出信号
    //   - Pixel_RST               : RST输出信号
    // ========================================================================
    // ila_pixel_stimulus ila_pixel_stimulus_inst (
    //     .clk(clk),
    //     .probe0({
    //         22'b0,                  // [63:42] 保留
    //         pixel_cmd_param,        // [41:34] 命令参数 8bit
    //         pulse_num_counter,      // [33:20] 脉冲数量计数 14bit
    //         pulse_counter,          // [19:12] 脉冲计数器 8bit
    //         csa_cmd_latch,          // [11:6]  锁存的CSA命令 6bit
    //         Pixel_CSA,              // [5:0]   CSA输出 6bit (可选择放在这里或下面)
    //         // 或者选择监控更多状态：
    //         Pixel_RST,           // [6]     RST输出
    //         pixel_cmd_trigger,   // [5]     命令触发
    //         state                // [4:2]   状态机
    //     })
    // );
    //
    // 备选probe配置（更详细的状态监控）：
    // ila_pixel_stimulus ila_pixel_stimulus_inst (
    //     .clk(clk),
    //     .probe0({
    //         20'b0,                  // [63:44] 保留
    //         pixel_cmd_param,        // [43:36] 命令参数 8bit
    //         pulse_num_counter,      // [35:28] 脉冲数量计数 8bit
    //         pulse_counter,          // [27:20] 脉冲计数器 8bit
    //         csa_cmd_latch,          // [19:14] 锁存的CSA命令 6bit
    //         Pixel_CSA,              // [13:8]  CSA输出 6bit
    //         3'b0,                   // [7:5]   保留
    //         pixel_cmd_trigger,      // [4]     命令触发
    //         state,                  // [3:1]   状态机 3bit
    //         Pixel_RST               // [0]     RST输出
    //     })
    // );

endmodule
