# TDC (Time-to-Digital Converter) UART 集成系统

## 项目概述

本项目是一个基于 **Xilinx Kintex-7 (xc7k325t-ffg900-2)** 的双通道高精度 TDC 设计。通信链路已由千兆以太网切换为 **UART 串口**，波特率为 **115200**。系统集成了 TDC 测量核心、像素芯片激励控制、相位扫描测试与上位机交互功能，可通过 UART 完成测量数据回传、精细相位扫描、在线校准和像素控制。

### 主要特性

*   **高分辨率**：约 xxx ps（待测）（基于 96-tap CARRY4 延迟线 + 四相位插值架构）。
*   **时钟架构**：260MHz 专用 TDC 采样时钟 + 200MHz 系统通信时钟。
*   **双通道测量**：**UP 取样** 与 **DOWN 取样** 独立并行采集。
*   **在线自校准**：内置环形振荡器，通过码密度测试生成 LUT 实现线性化校正。
*   **UART 通信**：115200-8N1 模式，采用高效的小端 32 位字传输协议。
*   **综合控制**：集成相位扫描引擎、像素 RST/CSA 脉冲发生器。

---

## 系统架构

```
┌─────────────────────────────────────────────┐
│               test_tdc_uart                 │
├─────────────────────────────────────────────┤
│        IBUFDS + 上电复位延时 (200MHz)         │
│  ┌───────────────────────────────────────┐  │
│  │           tdc_uart_integrated         │  │
│  │  ┌────────────┐  ┌──────────────────┐ │  │
│  │  │ clock_mgr  │  │ channel_up/down  │ │  │
│  │  └────────────┘  └──────────────────┘ │  │
│  │        │              │               │  │
│  │  ┌────────────┐  ┌───────────┐        │  │
│  │  │ uart_comm  │──│ uart_tx/rx│        │  │
│  │  └────────────┘  └───────────┘        │  │
│  │  ┌────────────┐  ┌───────────┐        │  │
│  │  │ scan_ctrl  │  │ pixel_stim│        │  │
│  │  └────────────┘  └───────────┘        │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

---

## 关键模块详解

### 1. `test_tdc_uart` (顶层模块)
- **时钟与复位**：接收差分 200MHz 系统时钟，CPU_RESET 低有效，包含上电延时逻辑以确保复位稳定。
- **外设接口**：
  - **UART**：映射到 `UART_RXD` / `UART_TXD` 引脚。
  - **Pixel IO**：提供 `PIXEL_CSA[5:0]` 和 `PIXEL_RST`（高有效）控制信号。
  - **信号输入**：`SIGNAL_IN_DOWN` 固定接地，`SIGNAL_IN_UP` 信号像素芯片内部默认自动接地。
- **调试支持**：可接入外部 `SIGNAL_UP` / `SIGNAL_DOWN`；`scan_test_en` 默认为 0（外部信号模式），为 1 时切换至内部脉冲发生器。`TDC_READY_LED` 指示系统就绪状态。

### 2. `tdc_uart_integrated` (集成核心)
- **参数配置**：`CLK_FREQ=200MHz`, `BAUD_RATE=115200`.
- **时钟域划分**：
  - **200MHz 域**：负责 UART 通信、指令解析、数据打包及像素控制。
  - **260MHz 域**：专用于 TDC 测量与校准核心，由 MMCM/PLL 独立生成，最大化减少噪声干扰。
- **子模块集成**：
  - `channel_up/down`: TDC 测量通道。
  - `tdc_calib_ctrl`: 在线校准控制。
  - `tdc_scan_ctrl`: 相位扫描控制。
  - `pixel_stimulus_ctrl`: 像素激励生成。
  - `uart_comm_ctrl_tdc`: 通信协议栈。

### 3. `uart_comm_ctrl_tdc` (通信控制器)
- **功能**：负责串口命令解码与测量数据回传，管理数据 FIFO，处理扫描/校准/像素指令。
- **配对逻辑**：数据发送严格保持 **UP → DOWN** 配对顺序，确保数据完整性。

#### 命令格式 (32-bit, Little Endian)

| Bit | 描述 | 选项/值 |
| :--- | :--- | :--- |
| **[31]** | 操作类型 | 1=校准, 0=扫描/控制 |
| **[30]** | 扫描模式 | 0=单步, 1=全扫描 |
| **[29:28]** | 通道掩码 | 00=无, 01=DOWN, 10=UP, 11=BOTH |
| **[27:20]** | **相位参数** | 0-255 (Dynamic Phase Shift) |
| **[19]** | Pixel RST | 1=触发复位脉冲 |
| **[18:13]** | **Pixel CSA** | CSA[5:0] 脉冲触发位掩码 |
| **[12:0]** | 保留 | 0 |

#### 数据格式 (32-bit, Little Endian)

| Bit | 描述 | 详细说明 |
| :--- | :--- | :--- |
| **[31:30]** | 数据类型 | 00=UP, 01=DOWN, 10=INFO, 11=CMD回显 |
| **[29:24]** | **ID/Phase** | 6-bit 索引，用于匹配 UP/DOWN 对 |
| **[23:11]** | **Fine Time** | 13-bit 精细直方图校准后时间 |
| **[10]** | 通道标志 | 1=UP, 0=DOWN |
| **[9:0]** | **Coarse** | 10-bit 粗计数器数值 |

### 4. `tdc_scan_ctrl` (相位扫描)
- 利用 FPGA Clocking Wizard 的 **Dynamic Phase Shift** 功能。
- **VCO 频率**：1040MHz。
- **分辨率**：单位相位步进为 $1 / 1040\text{MHz} / 56 \approx 17.17 \text{ps}$。
- **模式**：
  - **单步模式**：调整到指定相位，发射一次测试脉冲。
  - **全扫描模式**：自动从 0 扫描至 224，覆盖一个 260MHz 周期 ($17.17 \text{ps} \times 224 \approx 3846 \text{ps}$)。

---

## 上位机脚本 (Python Tools)

位于 `scripts/` 目录下，提供三种工具满足不同测试需求。

### 1. `tdc_uart_scan.py` (命令行工具)
基础调试与校准工具，提供轻量级的串口交互。
*   **功能**：执行全扫描、单步测试、启动校准。
*   **数据处理**：实时解码 32 位数据流，按照 UP/DOWN 分类并计算配对延迟。

### 2. `tdc_uart_scan_GUI.py` (图形化工作台)
功能强大的可视化控制台，专为像素芯片测试优化。

**主要特性：**
*   **交互式控制**：一键触发 RST/CSA 脉冲，支持 6 个 CSA 通道独立开关。
*   **自动化测试序列**：
    *   **Fixed Mode**：定点监测，生成实时 2D 分布直方图。
    *   **6-Step Scan**：自动遍历 CSA0-CSA5，生成 **3D 瀑布图** 对比通道响应。
*   **实时配对运算**：
    *   自动处理粗计数(Coarse)溢出翻转。
    *   计算公式：
        ```math
        \Delta T = (\text{Coarse}_{DN} - \text{Coarse}_{UP}) \times 3846.15 - (\text{Fine}_{DN} - \text{Fine}_{UP})
        ```
*   **数据导出**：支持 CSV 原始数据保存及统计图表导出。

**数据目录规范：**
脚本依赖特定的目录结构进行数据归档：
```
data/
├── SEL001/
│   └── YYYYMMDD_HHMMSS/
│       ├── analysis_plot.png
│       ├── CSA0.csv         # 分通道数据
│       ├── ...
│       └── summary.txt
└── ...
```

### 3. `tdc_trend_analysis.py` (趋势分析工具)
用于批量后处理数据，分析像素芯片延时单元的 **Unit Delay (τ)** 特性。

**核心算法：**
基于像素物理结构的延时关系模型：
```math
\begin{aligned}
\text{CSA}_0: \Delta T &= 5\tau \\
\text{CSA}_1: \Delta T &= 3\tau \\
\text{CSA}_2: \Delta T &= \tau \\
\dots \\
\text{CSA}_5: \Delta T &= -5\tau
\end{aligned}
```
脚本自动遍历 `SEL001` - `SEL111` 目录，计算 $\tau$ 值并绘制 **$\tau$ vs SEL** 的灵敏度曲线。

---

## 文件结构索引

```
TDC_UART/
├── TDC_UART.xpr                     # Vivado 工程文件
├── README.md                       # 本文档
├── scripts/                         # Python 上位机脚本
│   ├── tdc_uart_scan.py            #     - 命令行扫描/校准
│   ├── tdc_uart_scan_GUI.py        #     - GUI 像素控制与采集
│   └── tdc_trend_analysis.py       #     - 延时单元趋势分析
├── data/                            # 实验数据存档目录
├── TDC_UART.srcs/                   # FPGA 源代码
│   ├── sources_1/
│   │   ├── new/
│   │   │   ├── test_tdc_uart.v         # Top Module
│   │   │   ├── tdc_uart_integrated.v   # Core Wrapper
│   │   │   ├── uart_comm_ctrl_tdc.v    # Protocol Handler
│   │   │   ├── channel.v               # TDC Channel
│   │   │   ├── delay_line.v            # CARRY4 Line
│   │   │   ├── priority_encoder.v      # Decoder
│   │   │   ├── tdc_scan_ctrl.v         # Phase Shift Ctrl
│   │   │   └── ...
│   │   └── ip/                      # Vivado IPs (Clock Wizard, FIFO, ILA)
│   └── constrs_1/                   # 物理/时序约束
└── ...
```

---

## 作者

**pan224**
