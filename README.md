# TDC (Time-to-Digital Converter) UART 集成系统

## 项目概述

本项目是一个基于 Xilinx Kintex-7 (xc7k325t-ffg900-2) 的双通道高精度 TDC 设计，通信链路由千兆以太网切换为 UART 串口。系统集成 TDC 核心、像素芯片激励、扫描测试与上位机交互，可通过 UART 完成测量数据回传、相位扫描、校准和像素控制。

### 主要特性
- 分辨率约 xxxps（待测）（96-tap 延迟线 + 四相位插值）
- 时钟架构：260MHz TDC 时钟 + 200MHz 系统时钟
- 双通道测量：UP 与 DOWN 同时采集
- 自校准：基于环振统计的 LUT 线性化
- UART 通信：115200 8N1，小端 32 位字传输
- 扫描/像素控制：相位扫描、像素复位与激励脉冲控制

---

## 系统架构

```
┌─────────────────────────────────────────────┐
│               test_tdc_uart                 │
├─────────────────────────────────────────────┤
│  IBUFDS + 上电复位延时 (200MHz)             │
│  ┌───────────────────────────────────────┐ │
│  │           tdc_uart_integrated         │ │
│  │  ┌────────────┐  ┌──────────────────┐ │ │
│  │  │ clock_mgr  │  │ channel_up/down │ │ │
│  │  └────────────┘  └──────────────────┘ │ │
│  │        │              │               │ │
│  │  ┌────────────┐  ┌──────────┐        │ │
│  │  │ uart_comm  │──│ uart_tx/rx│        │ │
│  │  └────────────┘  └──────────┘        │ │
│  │  ┌────────────┐  ┌──────────┐        │ │
│  │  │ scan_ctrl  │  │ pixel_stim│       │ │
│  │  └────────────┘  └──────────┘        │ │
│  └───────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## 关键模块

### test_tdc_uart (顶层)
- 差分 200MHz 系统时钟输入，CPU_RESET 低有效，上电延时释放复位。
- UART 引脚：UART_RXD / UART_TXD。
- 像素接口：PIXEL_CSA[5:0]，PIXEL_RST（高有效），SIGNAL_IN_DOWN 固定接地。
- 可接入外部 SIGNAL_UP / SIGNAL_DOWN；scan_test_en 默认为 0（使用外部信号）。
- 输出 TDC_READY_LED 指示就绪。

### tdc_uart_integrated
- 参数：CLK_FREQ=200MHz，BAUD_RATE=115200。
- 子模块：时钟管理、复位同步、channel_up/down、tdc_calib_ctrl、tdc_scan_ctrl、tdc_signal_mux、pixel_stimulus_ctrl、tdc_cdc_sync、uart_comm_ctrl_tdc、uart_tx/uart_rx。
- UART 在 200MHz 域运行，TDC 测量与校准在 260MHz 域。
- Pixel 激励默认配置：低电平 8cyc，高电平 93cyc，PULSE_COUNT=100，间隔 40000cyc@200MHz，复位等待 100cyc。

### uart_comm_ctrl_tdc
- 串口命令与数据编解码，管理测量 FIFO、扫描/校准/像素命令。
- 数据发送严格保持 UP→DOWN 配对，busy 同步后再弹出 FIFO。

#### 命令格式（32 位，小端发送 LSB→MSB）
- [31]：1=校准，0=扫描
- [30]：扫描模式（0=单步，1=全扫描）
- [29:28]：通道选择（00=无，01=DOWN，10=UP，11=BOTH）
- [27:20]：相位参数（0-255）
- [19]：像素 RST 脉冲
- [18:13]：像素 CSA[5:0] 脉冲
- [12:0]：保留

#### 数据格式（32 位，小端发送）
- [31:30]：类型（00=UP，01=DOWN，10=INFO，11=CMD 回显）
- [29:24]：ID / 相位索引（6-bit）
- [23:11]：精细时间（13-bit）
- [10]：通道标志（1=UP，0=DOWN）
- [9:0]：粗计数（10-bit）

### UART 物理层
- uart_tx / uart_rx，115200 8N1，32 位数据拆成 4 字节小端流。

### tdc_scan_ctrl 与 tdc_signal_mux
- 相位扫描、测试脉冲注入，支持 UP/DOWN/双通道；scan_test_en 高时使用内部测试脉冲。

### pixel_stimulus_ctrl
- 在 200MHz 域生成像素 CSA/RST 脉冲，支持指令触发与脉冲计数配置。

---

## 上位机脚本（UART）

提供两个上位机工具：命令行扫描脚本和图形化像素控制界面。

### 1. tdc_uart_scan.py（命令行）

位于 scripts/tdc_uart_scan.py，提供串口连接、扫描、校准、像素控制与结果可视化。

#### 依赖
```bash
pip install pyserial numpy matplotlib
```

#### 快速使用
连接板卡串口（115200 8N1），运行脚本：
```bash
python scripts/tdc_uart_scan.py
```

常用操作：
- 选项 1/2：全扫描（可指定结束相位，默认 224）
- 选项 3：单步测试指定相位
- 选项 4/5：仅 UP 或仅 DOWN 扫描
- 选项 6：连续单步扫描区间
- 选项 7：启动 TDC 校准

#### 数据解析
脚本按 32 位数据格式解码，分类 UP/DOWN，提供配对延时计算、Fine 统计、可选绘图与文件保存（带时间戳）。

---

### 2. tdc_uart_scan_GUI.py（图形界面）

位于 scripts/tdc_uart_scan_GUI.py，提供可视化像素芯片控制、自动化数据采集与 3D 分析。

#### 依赖
```bash
pip install pyserial numpy matplotlib
```

#### 功能特性
- **像素芯片控制**：
  - RST 复位脉冲控制
  - CSA[5:0] 独立激励位配置
  - 实时指令预览（32位十六进制）
  - 单次发送或批量自动化测试

- **自动化测试模式**：
  - **Fixed 模式**：固定参数重复采集，生成 2D 直方图分析
  - **6-Step Scan 模式**：依次激励 CSA0~CSA5，生成 3D 瀑布图对比不同激励源的响应

- **实时数据显示**：
  - UP/DOWN 配对计算（支持双向配对，处理粗计数 10 位溢出）
  - Coarse Diff、Fine Diff、Delta T (ps) 显示
  - 配对数据自动计算：`Delta_T = (Coarse_DOWN - Coarse_UP) × 3846.15ps - (Fine_DOWN - Fine_UP)`
  - CSV 导出功能

- **统计分析**：
  - 均值、标准差、方差计算
  - 高斯拟合曲线
  - 3D 柱状图展示多通道对比

#### 快速使用
连接板卡串口，运行 GUI：
```bash
python scripts/tdc_uart_scan_GUI.py
```

操作步骤：
1. 选择端口和波特率（默认 115200）
2. 点击"打开串口"连接设备
3. 配置像素激励参数（RST、CSA[5:0]）
4. 选择测试模式：
   - **单次发送**：测试当前配置
   - **Fixed 采集**：固定参数重复测试
   - **6-Step 扫描**：自动遍历 CSA0~5，生成 3D 对比图
5. 查看实时数据表格和统计分析窗口

---

### 3. tdc_trend_analysis.py（延时单元分析）

位于 scripts/tdc_trend_analysis.py，用于分析像素芯片延时单元的单位延时（Unit Delay）随 SEL 配置的变化趋势。

#### 原理说明

像素芯片的 6 个 CSA 激励点具有不同的延时关系：
```
CSA0: Delta_T =  5τ  →  τ = Delta_T / 5
CSA1: Delta_T =  3τ  →  τ = Delta_T / 3
CSA2: Delta_T =   τ  →  τ = Delta_T / 1
CSA3: Delta_T =  -τ  →  τ = Delta_T / (-1)
CSA4: Delta_T = -3τ  →  τ = Delta_T / (-3)
CSA5: Delta_T = -5τ  →  τ = Delta_T / (-5)
```

其中 τ 为延时单元的单位延时时间（ps）。通过对每个像素点采集的大量数据（如 10000 组），可以反推计算出 τ 值，并分析其在不同 SEL 配置下的稳定性和灵敏度。

#### 数据组织

脚本要求数据按如下结构存放：
```
data/
├── SEL001/
│   └── 实验时间戳/
│       ├── CSA0.csv  (推荐：分像素文件)
│       ├── CSA1.csv
│       ├── ...
│       └── data.csv  (兼容：包含 CSA_Label 列的合并文件)
├── SEL010/
├── SEL011/
├── ...
└── SEL111/
```

每个 CSV 文件需包含 `Delta_ps` 列（UP/DOWN 时间差，单位 ps）。

#### 功能特性

- **批量处理**：自动遍历 SEL=001~111（十进制 1~7）的所有实验数据
- **智能读取**：
  - 优先读取分像素文件 `CSAx.csv`
  - 若不存在，则从 `data.csv` 中根据 `CSA_Label` 列筛选
  - 自动选择每个 SEL 下的最新实验目录
- **统计计算**：
  - 对每个像素的所有采样计算单位延时 τ
  - 统计均值（Mean_Tau）和标准差（Std_Tau）
- **可视化输出**：
  - 生成 2×3 子图（6 个像素各一张）
  - Errorbar 图：Y 轴为 τ 均值，误差棒为标准差
  - 线性拟合：显示 τ 随 SEL 变化的斜率（Sensitivity, ps/LSB）
  - 保存为 `Unit_Delay_Analysis_YYYYMMDD_HHMMSS.png`

#### 快速使用

确保数据按上述结构存放后运行：
```bash
python scripts/tdc_trend_analysis.py
```

输出示例：
```
处理 SEL=001 (实验: 20260108_143022)
  CSA0: 样本数=10000, Mean_Tau=14652.30 ps
  CSA1: 样本数=10000, Mean_Tau=14655.12 ps
  ...
[完成] 单位延时分析图已保存至: data/Unit_Delay_Analysis_20260108_150305.png
```

#### 应用场景

- **工艺表征**：评估延时单元在不同电压/温度下的稳定性
- **校准优化**：确定最佳 SEL 配置以获得线性响应
- **性能分析**：量化不同像素间的延时匹配度（Std_Tau 越小越好）
- **灵敏度测试**：通过线性拟合斜率评估 SEL 调节的有效性

---

## 构建与下载

### 环境
- Vivado 2020.1 及以上
- 板卡：Xilinx Kintex-7 xc7k325t-ffg900-2

### 综合与实现
```tcl
open_project TDC_UART.xpr
reset_run synth_1
launch_runs synth_1 -jobs 8
wait_on_run synth_1

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
```

### 下载比特流
```tcl
open_hw_manager
connect_hw_server
open_hw_target
set_property PROGRAM.FILE {TDC_UART.runs/impl_1/test_tdc_uart.bit} [current_hw_device]
program_hw_device
```

---

## 文件结构（摘要）
```
TDC_UART/
├── TDC_UART.xpr                     # Vivado 工程
├── README.md                       # 本文档（UART 版）
├── scripts/
│   ├── tdc_uart_scan.py            # 串口命令行脚本（扫描/校准）
│   ├── tdc_uart_scan_GUI.py        # 图形界面（像素控制/自动化测试）
│   └── tdc_trend_analysis.py       # 延时单元趋势分析工具
├── TDC_UART.srcs/
│   ├── sources_1/
│   │   ├── new/
│   │   │   ├── test_tdc_uart.v
│   │   │   ├── tdc_uart_integrated.v
│   │   │   ├── uart_comm_ctrl_tdc.v
│   │   │   ├── uart_tx.v / uart_rx.v
│   │   │   ├── channel.v, delay_line.v, priority_encoder.v
│   │   │   ├── tdc_clock_manager.v, tdc_reset_sync.v, tdc_cdc_sync.v
│   │   │   ├── tdc_scan_ctrl.v, tdc_signal_mux.v
│   │   │   ├── pixel_stimulus_ctrl.v, dynamic_phase_pulse_gen.v
│   │   │   └── tdc_pkg.vh 等测量核心文件
│   │   └── ip/                      # ILA 等调试 IP
│   └── constrs_1/                   # 约束文件
├── tdc_results/                    # 采集/扫描结果示例
├── TDC_UART.runs/                  # Vivado 生成文件
└── TDC_UART.hw/                    # 硬件会话/ILA 数据
```

---

## 许可证

MIT License

## 作者

pan224

## 更新日志

- **2025-12-10**: 完成模块化重构，添加完整文档和测试数据
- **2025-12-09**: 修复时序违规，优化 CDC 路径
- **2025-12-08**: 实现扫描测试功能
