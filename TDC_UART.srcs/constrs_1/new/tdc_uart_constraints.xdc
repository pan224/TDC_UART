# ============================================================================
# TDC UART 系统约束文件
# ============================================================================
# 适用于 Xilinx Kintex-7 XC7K325FFG900-2
# ============================================================================

# ============================================================================
# 系统管脚约束
# ============================================================================
# 系统复位 - 高电平有效
set_property PACKAGE_PIN AE20 [get_ports CPU_RESET]
set_property IOSTANDARD LVCMOS33 [get_ports CPU_RESET]

# 系统时钟 200MHz (差分输入)
set_property PACKAGE_PIN AD12 [get_ports SYS_CLK_P]
set_property PACKAGE_PIN AD11 [get_ports SYS_CLK_N]
set_property IOSTANDARD DIFF_SSTL15 [get_ports SYS_CLK_P]
set_property IOSTANDARD DIFF_SSTL15 [get_ports SYS_CLK_N]

# ============================================================================
# UART 管脚约束
# ============================================================================
# UART 接收引脚 (RXD) - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN F25 [get_ports UART_RXD]
set_property IOSTANDARD LVCMOS33 [get_ports UART_RXD]

# UART 发送引脚 (TXD) - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN D24 [get_ports UART_TXD]
set_property IOSTANDARD LVCMOS33 [get_ports UART_TXD]

# ============================================================================
# 像素芯片接口管脚约束
# ============================================================================
# 像素芯片激励信号 [5:0] - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN E23 [get_ports {PIXEL_CSA[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {PIXEL_CSA[0]}]

set_property PACKAGE_PIN D23 [get_ports {PIXEL_CSA[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {PIXEL_CSA[1]}]

set_property PACKAGE_PIN B22 [get_ports {PIXEL_CSA[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {PIXEL_CSA[2]}]

set_property PACKAGE_PIN A22 [get_ports {PIXEL_CSA[3]}]
set_property IOSTANDARD LVCMOS18 [get_ports {PIXEL_CSA[3]}]

set_property PACKAGE_PIN D17 [get_ports {PIXEL_CSA[4]}]
set_property IOSTANDARD LVCMOS18 [get_ports {PIXEL_CSA[4]}]

set_property PACKAGE_PIN D16 [get_ports {PIXEL_CSA[5]}]
set_property IOSTANDARD LVCMOS18 [get_ports {PIXEL_CSA[5]}]

# 像素芯片复位信号 (高有效) - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN C24 [get_ports PIXEL_RST]
set_property IOSTANDARD LVCMOS33 [get_ports PIXEL_RST]

# # 输入给像素芯片的 DOWN 信号 - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN E24 [get_ports SIGNAL_IN_DOWN]
set_property IOSTANDARD LVCMOS33 [get_ports SIGNAL_IN_DOWN]

# ============================================================================
# TDC 测量信号管脚约束
# ============================================================================
# # UP 信号输入 - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN E18 [get_ports SIGNAL_UP]
set_property IOSTANDARD LVCMOS18 [get_ports SIGNAL_UP]
set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets {SIGNAL_UP_IBUF}]
# # DOWN 信号输入 - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN D18 [get_ports SIGNAL_DOWN]
set_property IOSTANDARD LVCMOS18 [get_ports SIGNAL_DOWN]
set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets {SIGNAL_DOWN_IBUF}]
# # TDC 复位触发 - TODO: 请填写实际管脚位置
# set_property PACKAGE_PIN <填写管脚> [get_ports TDC_RESET]
# set_property IOSTANDARD LVCMOS33 [get_ports TDC_RESET]

# ============================================================================
# 状态指示 LED
# ============================================================================
# TDC 就绪 LED - TODO: 请填写实际管脚位置
set_property PACKAGE_PIN V30 [get_ports TDC_READY_LED]
set_property IOSTANDARD LVCMOS33 [get_ports TDC_READY_LED]

# ============================================================================
# 时钟约束
# ============================================================================
# 系统时钟 200MHz (差分输入)
create_clock -period 5.000 -name sys_clk_200 [get_ports SYS_CLK_P]

# ============================================================================
# TDC 时钟生成 - tdc_uart_integrated 模块内的时钟
# ============================================================================
# 260MHz TDC 主时钟（关键路径）
create_generated_clock -name clk_260MHz -source [get_pins tdc_uart_inst/clock_mgr_inst/clk_wiz_tdc_inst/clk_in1] \
    -divide_by 10 -multiply_by 13 [get_pins tdc_uart_inst/clock_mgr_inst/clk_wiz_tdc_inst/clk_out1]

# ============================================================================
# 异步时钟域约束
# ============================================================================
# 200MHz 和 260MHz 时钟域之间的异步约束
set_clock_groups -asynchronous \
    -group [get_clocks sys_clk_200] \
    -group [get_clocks clk_260MHz]

# ============================================================================
# 时序例外（False Path）
# ============================================================================

# 复位信号的异步路径
set_false_path -from [get_ports CPU_RESET]

# 跨时钟域的同步寄存器（CDC 双触发器）
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *sync_reg[0]/D}]
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *sync1_reg/D}]
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *sync2_reg/D}]

# 校准使能控制信号（静态或慢速变化）
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *calib_sel_reg/C}] -to [get_pins -hierarchical -filter {NAME =~ *BUFGCTRL*/CE*}]

# ============================================================================
# 异步 FIFO 复位路径约束
# ============================================================================
# UP 方向异步 FIFO（260MHz 写入，200MHz 读取）
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *uart_comm_inst/up_async_fifo/*/RST}]

# DOWN 方向异步 FIFO
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *uart_comm_inst/down_async_fifo/*/RST}]

# 通用匹配：所有到 FIFO36E1 RST 引脚的路径
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *fifo_36_72*/RST}]

# CDC 同步模块中的异步清除信号
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *cdc_sync_inst/*/CLR}]
set_false_path -to [get_pins -hierarchical -filter {NAME =~ *cdc_sync_inst/*/PRE}]

# Reset sync 模块到所有异步复位目标的路径
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *reset_sync_inst/reset_sync_260_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ */RST}]
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *reset_sync_inst/reset_sync_260_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ */CLR}]
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *reset_sync_inst/reset_sync_200_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ */RST}]
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *reset_sync_inst/reset_sync_200_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ */CLR}]

# ============================================================================
# 跨时钟域 CDC 同步器路径约束
# ============================================================================
# scan_param 信号从 uart_comm (200MHz) 传输到 cdc_sync (260MHz)
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *uart_comm_inst/scan_cmd_param_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *cdc_sync_inst/scan_param_sync1_reg*/D}]

# manual_calib 信号的 CDC 路径
set_false_path -from [get_pins -hierarchical -filter {NAME =~ *uart_comm_inst/manual_calib_trigger_reg/C}] -to [get_pins -hierarchical -filter {NAME =~ *cdc_sync_inst/manual_calib_sync1_reg/D}]

# ============================================================================
# 多周期路径约束 - 针对 TDC 关键路径
# ============================================================================

# channel valid 信号到 timestamp_capture 的路径
set_max_delay -from [get_pins -hierarchical -filter {NAME =~ *channel_up_inst/valid_reg/C}] -to [get_pins -hierarchical -filter {NAME =~ *timestamp_capture_inst/up_event_id_cnt_reg*/R}] 5.0 -datapath_only
set_max_delay -from [get_pins -hierarchical -filter {NAME =~ *channel_down_inst/valid_reg/C}] -to [get_pins -hierarchical -filter {NAME =~ *timestamp_capture_inst/down_event_id_cnt_reg*/R}] 5.0 -datapath_only

# pulse_gen 状态机到 scan_ctrl 状态机的路径
set_multicycle_path -setup 2 -from [get_pins -hierarchical -filter {NAME =~ *pulse_gen_up/FSM_sequential_state_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *scan_ctrl_inst/FSM_sequential_state_reg*/CE}]
set_multicycle_path -hold 1 -from [get_pins -hierarchical -filter {NAME =~ *pulse_gen_up/FSM_sequential_state_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *scan_ctrl_inst/FSM_sequential_state_reg*/CE}]

set_multicycle_path -setup 2 -from [get_pins -hierarchical -filter {NAME =~ *pulse_gen_down/FSM_sequential_state_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *scan_ctrl_inst/FSM_sequential_state_reg*/CE}]
set_multicycle_path -hold 1 -from [get_pins -hierarchical -filter {NAME =~ *pulse_gen_down/FSM_sequential_state_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *scan_ctrl_inst/FSM_sequential_state_reg*/CE}]

# reset_sync 到 timestamp_capture 的复位路径
set_multicycle_path -setup 2 -from [get_pins -hierarchical -filter {NAME =~ *reset_sync_inst/reset_sync_260_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *timestamp_capture_inst/*_event_id_cnt_reg*/R}]
set_multicycle_path -hold 1 -from [get_pins -hierarchical -filter {NAME =~ *reset_sync_inst/reset_sync_260_reg*/C}] -to [get_pins -hierarchical -filter {NAME =~ *timestamp_capture_inst/*_event_id_cnt_reg*/R}]

# ============================================================================
# 物理约束 - 优化布局布线
# ============================================================================

# 环形振荡器需要允许组合环路
set_property ALLOW_COMBINATORIAL_LOOPS true [get_nets -hierarchical -filter {NAME =~ *ro_clk*}]
set_property ALLOW_COMBINATORIAL_LOOPS true [get_nets -hierarchical -filter {NAME =~ *ro_inst*}]

# ============================================================================
# TDC Sensor信号路径延迟平衡约束
# ============================================================================
# UP通道：从 up_mux_inst (BUFGCTRL) 到 4个delay_line的sensor_ff
set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/up_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_0/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/up_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_90/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/up_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_180/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/up_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_270/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

# DOWN通道：从 down_mux_inst (BUFGCTRL) 到 4个delay_line的sensor_ff
set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/down_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_0/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/down_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_90/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/down_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_180/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

set_max_delay -from [get_pins tdc_uart_inst/signal_mux_inst/down_mux_inst/O] \
              -to [get_pins tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_270/gen_sensor_ff_real.sensor_ff/C] \
              1.800 -datapath_only

# ============================================================================
# TDC 延迟线物理位置约束
# ============================================================================
# DOWN通道
set_property LOC SLICE_X0Y0 [get_cells tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_0/gen_carry0_real.carry4_0]
set_property LOC SLICE_X10Y0 [get_cells tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_90/gen_carry0_real.carry4_0]
set_property LOC SLICE_X20Y0 [get_cells tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_180/gen_carry0_real.carry4_0]
set_property LOC SLICE_X30Y0 [get_cells tdc_uart_inst/channel_down_inst/dl_sync_inst/dl_270/gen_carry0_real.carry4_0]
# UP通道
set_property LOC SLICE_X40Y0 [get_cells tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_0/gen_carry0_real.carry4_0]
set_property LOC SLICE_X50Y0 [get_cells tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_90/gen_carry0_real.carry4_0]
set_property LOC SLICE_X60Y0 [get_cells tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_180/gen_carry0_real.carry4_0]
set_property LOC SLICE_X70Y0 [get_cells tdc_uart_inst/channel_up_inst/dl_sync_inst/dl_270/gen_carry0_real.carry4_0]

# ============================================================================
# DRC 约束放宽
# ============================================================================
set_property SEVERITY {Warning} [get_drc_checks LUTLP-1]
set_property SEVERITY {Warning} [get_drc_checks LCCH-1]

# ============================================================================
