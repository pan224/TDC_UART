#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDC UART 扫描测试程序
基于 UART 串口通信（替代以太网版本）
支持多种测试模式：单步测试、全扫描

命令协议 (32位):
  [31]     : 1=校准, 0=扫描测试
  [30]     : 扫描模式 (0=单步, 1=全扫描)
  [29:28]  : 通道选择 (00=无, 01=DOWN, 10=UP, 11=UP+DOWN)
  [27:20]  : 相位参数 (0-255)
  [19]     : 像素芯片RST控制（产生复位脉冲）
  [18:13]  : 像素芯片CSA[5:0]控制（产生激励脉冲）
  [12:0]   : 保留

数据格式 (32位):
  [31:30]  : 类型 (00=UP, 01=DOWN, 10=INFO, 11=CMD)
  [29:22]  : ID (相位索引)
  [21:9]   : 精细时间 (13-bit)
  [8]      : 通道标志 (1=UP, 0=DOWN)
  [7:0]    : 粗计数低8位

UART配置:
  波特率: 115200
  数据位: 8
  停止位: 1
  无校验
  32位数据分4字节传输 (LSB First)
"""

import struct
import time
import os
from datetime import datetime

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[ERROR] pyserial 未安装，请执行: pip install pyserial")

try:
    import numpy as np
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    PLOT_AVAILABLE = True
except ImportError:
    PLOT_AVAILABLE = False
    print("[WARN] numpy/matplotlib 未安装，数据可视化功能不可用")


class TDCUartScanner:
    """TDC UART 扫描控制器"""
    
    # 命令类型 ([31]位)
    CMD_SCAN = 0      # 0 = 扫描测试
    CMD_CALIB = 1     # 1 = 校准
    
    # 扫描模式 ([30]位)
    SCAN_SINGLE = 0   # 单步模式
    SCAN_FULL = 1     # 全扫描模式
    
    # 通道选择 ([29:28]位)
    CH_NONE = 0b00    # 无通道
    CH_DOWN = 0b01    # DOWN 通道
    CH_UP = 0b10      # UP 通道 
    CH_BOTH = 0b11    # UP+DOWN 通道
    
    # 数据类型（接收数据的 [31:30] 位）
    TYPE_UP = 0b00
    TYPE_DOWN = 0b01
    TYPE_INFO = 0b10
    TYPE_CMD = 0b11
    
    def __init__(self, port=None, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.connected = False
        
    @staticmethod
    def list_ports():
        """列出所有可用的串口"""
        if not SERIAL_AVAILABLE:
            print("[ERROR] pyserial 未安装")
            return []
        
        ports = serial.tools.list_ports.comports()
        print("\n可用串口列表:")
        print("-" * 50)
        for i, port in enumerate(ports):
            print(f"  {i+1}. {port.device} - {port.description}")
        print("-" * 50)
        return [p.device for p in ports]
    
    def connect(self, timeout=2.0):
        """连接到FPGA串口"""
        if not SERIAL_AVAILABLE:
            print("[ERROR] pyserial 未安装")
            return False
        
        if self.port is None:
            # 自动选择串口
            ports = self.list_ports()
            if not ports:
                print("[ERROR] 未找到可用串口")
                return False
            
            try:
                choice = input(f"请选择串口 (1-{len(ports)}) [1]: ").strip()
                if not choice:
                    choice = "1"
                idx = int(choice) - 1
                if 0 <= idx < len(ports):
                    self.port = ports[idx]
                else:
                    print("[ERROR] 无效选择")
                    return False
            except ValueError:
                print("[ERROR] 无效输入")
                return False
        
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            self.connected = True
            print(f"[INFO] 已连接到 {self.port} @ {self.baudrate} baud")
            
            # 清空接收缓冲区
            print("[INFO] 清空接收缓冲区...")
            self._clear_rx_buffer()
            
            return True
        except serial.SerialException as e:
            print(f"[ERROR] 连接失败: {e}")
            return False
    
    def _clear_rx_buffer(self):
        """清空接收缓冲区"""
        if self.serial and self.serial.is_open:
            discarded = self.serial.in_waiting
            if discarded > 0:
                self.serial.read(discarded)
                print(f"[INFO] 已丢弃 {discarded} 字节旧数据")
    
    def disconnect(self):
        """断开连接"""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.connected = False
            print("[INFO] 连接已断开")
    
    def send_command(self, cmd_type, scan_mode=0, channel=0b11, phase=0, pixel_control=0):
        """
        发送命令到FPGA
        
        Args:
            cmd_type: 命令类型 (0=扫描, 1=校准)
            scan_mode: 扫描模式 (0=单步, 1=全扫描)
            channel: 通道选择 (0b00=无, 0b01=DOWN, 0b10=UP, 0b11=BOTH)
            phase: 相位参数 (0-255)
            pixel_control: 像素芯片控制 (8位: [7]=RST, [6:1]=CSA[5:0], [0]=保留)
        
        Returns:
            bool: 是否发送成功
        """
        if not self.connected:
            print("[ERROR] 未连接到设备")
            return False
        
        # 构建命令:
        # [31]     = cmd_type (0=扫描, 1=校准)
        # [30]     = scan_mode (0=单步, 1=全扫描)
        # [29:28]  = channel (通道选择)
        # [27:20]  = phase (相位参数)
        # [19:12]  = pixel_control (像素芯片控制)
        # [11:0]   = 保留
        cmd_data = ((cmd_type & 0x1) << 31) | \
                   ((scan_mode & 0x1) << 30) | \
                   ((channel & 0x3) << 28) | \
                   ((phase & 0xFF) << 20) | \
                   ((pixel_control & 0xFF) << 12)
        
        # 详细显示命令结构
        cmd_type_str = '校准' if cmd_type else '扫描'
        scan_mode_str = '全扫描' if scan_mode else '单步'
        channel_names = ['无', 'DOWN', 'UP', 'BOTH']
        
        print(f"[TX] 命令详情:")
        print(f"     完整命令: 0x{cmd_data:08X}")
        print(f"     [31]    Type: {cmd_type} ({cmd_type_str})")
        print(f"     [30]    Mode: {scan_mode} ({scan_mode_str})")
        print(f"     [29:28] Channel: 0b{channel:02b} ({channel_names[channel]})")
        print(f"     [27:20] Phase: {phase}")
        if pixel_control != 0:
            pixel_rst = (pixel_control >> 7) & 0x1
            pixel_csa = (pixel_control >> 1) & 0x3F
            print(f"     [19:12] Pixel Control: 0x{pixel_control:02X}")
            print(f"             RST: {pixel_rst}, CSA[5:0]: 0b{pixel_csa:06b}")
        
        try:
            # 32位数据转为4字节 (LSB First - 小端序)
            # UART模块按 [7:0], [15:8], [23:16], [31:24] 顺序发送
            data = struct.pack('<I', cmd_data)  # 小端序
            self.serial.write(data)
            self.serial.flush()
            print(f"[TX] 发送成功 (4字节: {data.hex()})")
            
            # 等待发送完成
            time.sleep(0.05)
            return True
        except Exception as e:
            print(f"[ERROR] 发送失败: {e}")
            return False
    
    def receive_data(self, expected_count, timeout=5.0):
        """
        接收指定数量的数据
        
        Args:
            expected_count: 期望接收的数据包数量
            timeout: 超时时间(秒)
        
        Returns:
            list: 接收到的数据列表 [{type, id, fine, coarse, flag, raw}, ...]
        """
        if not self.connected:
            print("[ERROR] 未连接到设备")
            return []
        
        data_list = []
        start_time = time.time()
        buffer = b''
        
        print(f"[INFO] 等待接收 {expected_count} 个数据包...")
        
        # 设置接收超时
        original_timeout = self.serial.timeout
        self.serial.timeout = 0.5  # 短超时用于非阻塞读取
        
        try:
            while len(data_list) < expected_count:
                # 检查总超时
                if time.time() - start_time > timeout:
                    print(f"[WARN] 接收超时，仅收到 {len(data_list)}/{expected_count} 个数据包")
                    break
                
                # 读取可用数据
                if self.serial.in_waiting > 0:
                    new_data = self.serial.read(self.serial.in_waiting)
                    buffer += new_data
                else:
                    # 尝试读取一些数据
                    new_data = self.serial.read(4)
                    if new_data:
                        buffer += new_data
                    continue
                
                # 处理完整的32位数据包 (4字节)
                while len(buffer) >= 4:
                    raw_bytes = buffer[:4]
                    buffer = buffer[4:]
                    
                    # 小端序解析 (LSB First)
                    value = struct.unpack('<I', raw_bytes)[0]
                    
                    # 解析数据包
                    # [31:30] = 类型 (00=UP, 01=DOWN, 10=INFO, 11=CMD)
                    # [29:22] = ID (相位索引)
                    # [21:9]  = 精细时间 (13-bit)
                    # [8]     = 通道标志 (1=UP通道, 0=DOWN通道)
                    # [7:0]   = 粗计数低8位
                    data_type = (value >> 30) & 0x3
                    data_id = (value >> 22) & 0xFF
                    fine_time = (value >> 9) & 0x1FFF
                    channel_flag = (value >> 8) & 0x1
                    coarse_time = value & 0xFF
                    
                    # 过滤命令类型的回显数据
                    if data_type == 0b11:  # CMD 类型
                        print(f"[RX] 忽略命令回显: 0x{value:08X}")
                        continue
                    
                    data_list.append({
                        'type': data_type,
                        'id': data_id,
                        'fine': fine_time,
                        'coarse': coarse_time,
                        'flag': channel_flag,
                        'raw': value
                    })
                    
                    # 实时显示前几个数据包用于调试
                    if len(data_list) <= 10:
                        type_str = ['UP', 'DOWN', 'INFO', 'CMD'][data_type]
                        print(f"[RX] 数据包#{len(data_list)}: Type={type_str}, ID={data_id}, "
                              f"Fine={fine_time}, Flag={channel_flag}, Coarse={coarse_time}, "
                              f"Raw=0x{value:08X}")
                    elif len(data_list) % 50 == 0 or len(data_list) == expected_count:
                        print(f"[RX] 进度: {len(data_list)}/{expected_count}")
        
        finally:
            self.serial.timeout = original_timeout
        
        print(f"[INFO] 接收完成，共 {len(data_list)} 个数据包")
        return data_list
    
    def start_scan(self, scan_mode=1, phase=224, channel=0b11):
        """
        启动扫描测试
        
        Args:
            scan_mode: 扫描模式
                      0 = 单步测试（指定相位）
                      1 = 全扫描（0到phase的所有相位）
            phase: 相位参数 (0-255, 推荐0-224)
            channel: 通道选择
                    0b00 = 无
                    0b01 = DOWN only
                    0b10 = UP only
                    0b11 = BOTH (默认)
        
        Returns:
            bool: 是否成功启动
        """
        mode_str = '全扫描' if scan_mode else '单步'
        ch_names = ['无', 'DOWN', 'UP', 'BOTH']
        print(f"[CMD] 启动扫描测试 (模式={mode_str}, 相位={phase}, 通道={ch_names[channel]})")
        return self.send_command(
            cmd_type=self.CMD_SCAN,
            scan_mode=scan_mode,
            channel=channel,
            phase=phase
        )
    
    def start_calibration(self):
        """启动手动校准"""
        print("[CMD] 启动手动校准")
        return self.send_command(
            cmd_type=self.CMD_CALIB,
            scan_mode=0,
            channel=0,
            phase=0
        )
    
    def send_pixel_stimulus(self, csa_mask=0, rst=False):
        """
        发送像素芯片激励信号
        
        Args:
            csa_mask: CSA激励掩码 (6位: bit5-bit0 对应 CSA_5-CSA_0)
            rst: 是否触发复位
        
        Returns:
            bool: 是否发送成功
        """
        # 构建像素控制字节
        # [7] = RST, [6:1] = CSA[5:0], [0] = 保留(0)
        pixel_control = ((1 if rst else 0) << 7) | ((csa_mask & 0x3F) << 1)
        
        csa_list = [i for i in range(6) if (csa_mask >> i) & 0x1]
        csa_str = ', '.join([f'CSA_{i}' for i in csa_list]) if csa_list else '无'
        rst_str = 'RST' if rst else ''
        
        if rst and csa_list:
            print(f"[CMD] 发送像素芯片激励: {csa_str} + {rst_str}")
        elif rst:
            print(f"[CMD] 发送像素芯片激励: {rst_str}")
        elif csa_list:
            print(f"[CMD] 发送像素芯片激励: {csa_str}")
        else:
            print("[WARN] 没有选择任何激励信号")
            return False
        
        return self.send_command(
            cmd_type=self.CMD_SCAN,
            scan_mode=0,
            channel=0,
            phase=0,
            pixel_control=pixel_control
        )


class TDCDataProcessor:
    """TDC 数据处理器"""
    
    def __init__(self, data_list):
        """
        Args:
            data_list: 接收到的数据列表
        """
        self.data_list = data_list
        
        # 时间常数 (260MHz系统)
        self.CLK_PERIOD = 3846  # ps (1/260MHz)
        self.TDC_BIN = 1        # fine值已经是ps单位
        self.PHASE_STEP = 17.17 # ps/step (VCO=1040MHz)
        
        # 分离UP和DOWN通道
        self.up_data = [d for d in data_list if d['type'] == 0b00]
        self.down_data = [d for d in data_list if d['type'] == 0b01]
        
    def process(self):
        """处理和分析数据"""
        print("\n" + "="*70)
        print("TDC 数据分析")
        print("="*70)
        
        print(f"总数据包: {len(self.data_list)}")
        print(f"UP 通道: {len(self.up_data)} 个")
        print(f"DOWN 通道: {len(self.down_data)} 个")
        
        if len(self.up_data) == 0 and len(self.down_data) == 0:
            print("[WARN] 没有有效数据")
            return
        
        # 分析UP通道
        if len(self.up_data) > 0:
            self._analyze_channel(self.up_data, "UP")
        
        # 分析DOWN通道
        if len(self.down_data) > 0:
            self._analyze_channel(self.down_data, "DOWN")
        
        # 如果是扫描模式,分析延迟曲线
        if len(self.up_data) >= 225:
            self._analyze_scan_curve()
        
        # 如果有足够的数据，进行TDC性能分析
        if len(self.up_data) >= 10:
            self.analyze_tdc_performance()
        
        print("="*70 + "\n")
    
    def _analyze_channel(self, channel_data, channel_name):
        """分析单个通道的数据"""
        print(f"\n{channel_name} 通道分析:")
        print("-" * 50)
        
        if not PLOT_AVAILABLE:
            fine_vals = [d['fine'] for d in channel_data]
            coarse_vals = [d['coarse'] for d in channel_data]
            
            print(f"  样本数: {len(channel_data)}")
            print(f"  Fine 范围: {min(fine_vals)} - {max(fine_vals)}")
            print(f"  Coarse 范围: {min(coarse_vals)} - {max(coarse_vals)}")
            return
        
        fine = np.array([d['fine'] for d in channel_data])
        coarse = np.array([d['coarse'] for d in channel_data])
        ids = np.array([d['id'] for d in channel_data])
        
        fine_time = fine * self.TDC_BIN
        coarse_time = coarse * self.CLK_PERIOD
        total_time = coarse_time + fine_time
        
        print(f"  样本数: {len(channel_data)}")
        print(f"  ID 范围: {ids.min()} - {ids.max()}")
        print(f"  Fine 范围: {fine.min()} - {fine.max()}")
        print(f"  Coarse 范围: {coarse.min()} - {coarse.max()}")
        print(f"  Fine 时间: {fine_time.min():.1f} - {fine_time.max():.1f} ps")
        print(f"  Total 时间: {total_time.min():.1f} - {total_time.max():.1f} ps")
        
        if len(channel_data) > 1:
            print(f"  Fine 标准差: {fine.std():.2f}")
            print(f"  Time 标准差: {total_time.std():.2f} ps")
    
    def _analyze_scan_curve(self):
        """分析扫描曲线"""
        if not PLOT_AVAILABLE:
            return
        
        print(f"\n扫描模式分析 ({len(self.up_data)}个相位):")
        print("-" * 50)
        print(f"提示: 225步(17.17ps/step)可覆盖完整3864ps周期")
        
        fine = np.array([d['fine'] for d in self.up_data])
        ids = np.array([d['id'] for d in self.up_data])
        
        actual_fine_time = fine
        phase_indices = ids
        
        # 检测环绕点
        diffs = np.diff(actual_fine_time)
        jump_threshold = self.CLK_PERIOD / 2
        wrap_points = np.where(np.abs(diffs) > jump_threshold)[0]
        
        print(f"  相位范围: {phase_indices.min()} - {phase_indices.max()}")
        print(f"  Fine time 范围: {actual_fine_time.min():.1f} - {actual_fine_time.max():.1f} ps")
        print(f"  Fine time 变化幅度: {actual_fine_time.max() - actual_fine_time.min():.1f} ps")
        print(f"  理论关系（无延迟）: Fine = {self.CLK_PERIOD:.0f} - Phase × {self.PHASE_STEP:.2f}")
        
        if len(wrap_points) > 0:
            print(f"  \n检测到 {len(wrap_points)} 个环绕点（固定布线延迟导致）")
            for i, wp in enumerate(wrap_points):
                wrap_phase = phase_indices[wp]
                estimated_delay = self.CLK_PERIOD - wrap_phase * self.PHASE_STEP
                print(f"    环绕点{i+1}: Phase {phase_indices[wp]} → {phase_indices[wp+1]}")
                print(f"              估计布线延迟 ≈ {estimated_delay:.1f} ps")
        
        if len(phase_indices) > 2:
            coeffs = np.polyfit(phase_indices, actual_fine_time, 1)
            fit_line = np.polyval(coeffs, phase_indices)
            residuals = actual_fine_time - fit_line
            
            print(f"  实际斜率: {coeffs[0]:.3f} ps/phase (理论: {-self.PHASE_STEP:.2f})")
            print(f"  斜率误差: {abs(coeffs[0] + self.PHASE_STEP):.3f} ps/phase")
            print(f"  RMS 误差: {np.sqrt(np.mean(residuals**2)):.2f} ps")
            print(f"  最大偏差: {np.max(np.abs(residuals)):.2f} ps")
    
    def analyze_tdc_performance(self):
        """TDC性能分析"""
        if not PLOT_AVAILABLE:
            print("[WARN] numpy不可用，无法进行性能分析")
            return None
        
        if len(self.up_data) < 10:
            print("[WARN] 数据量不足，无法进行性能分析")
            return None
        
        print("\n" + "="*70)
        print("TDC 性能分析")
        print("="*70)
        
        fine_values = np.array([d['fine'] for d in self.up_data])
        phase_ids = np.array([d['id'] for d in self.up_data])
        
        performance = {}
        
        # 1. 测量范围分析
        print("\n[1] 测量范围分析:")
        print("-" * 50)
        measured_range = fine_values.max() - fine_values.min()
        print(f"  最小值: {fine_values.min():.2f} ps")
        print(f"  最大值: {fine_values.max():.2f} ps")
        print(f"  测量范围: {measured_range:.2f} ps")
        print(f"  理论范围: {self.CLK_PERIOD:.2f} ps (时钟周期)")
        print(f"  范围覆盖率: {(measured_range/self.CLK_PERIOD)*100:.1f}%")
        
        performance['range'] = {
            'min': float(fine_values.min()),
            'max': float(fine_values.max()),
            'span': float(measured_range),
            'coverage': float((measured_range/self.CLK_PERIOD)*100)
        }
        
        # 2. 分辨率和精度分析
        print("\n[2] 分辨率和精度分析:")
        print("-" * 50)
        
        sorted_indices = np.argsort(phase_ids)
        sorted_phases = phase_ids[sorted_indices]
        sorted_times = fine_values[sorted_indices]
        
        time_diffs = np.diff(sorted_times)
        jump_mask = np.abs(time_diffs) < self.CLK_PERIOD/2
        valid_diffs = time_diffs[jump_mask]
        
        if len(valid_diffs) > 0:
            avg_resolution = np.abs(valid_diffs).mean()
            resolution_std = np.abs(valid_diffs).std()
            decreasing_ratio = np.sum(valid_diffs < 0) / len(valid_diffs)
            
            print(f"  平均步进: {avg_resolution:.3f} ps")
            print(f"  步进标准差: {resolution_std:.3f} ps")
            print(f"  理论步进: {self.PHASE_STEP:.3f} ps")
            print(f"  步进误差: {abs(avg_resolution - self.PHASE_STEP):.3f} ps")
            print(f"  递减比例: {decreasing_ratio*100:.1f}%")
            
            performance['resolution'] = {
                'avg_step': float(avg_resolution),
                'std_step': float(resolution_std),
                'theoretical_step': float(self.PHASE_STEP),
                'decreasing_ratio': float(decreasing_ratio)
            }
        
        # 3. LSB分析
        print("\n[3] LSB 分析:")
        print("-" * 50)
        
        unique_values = np.unique(fine_values)
        if len(unique_values) > 1:
            value_diffs = np.diff(np.sort(unique_values))
            lsb_estimate = value_diffs[value_diffs > 0].min()
            print(f"  检测到的唯一值数量: {len(unique_values)}")
            print(f"  估计LSB: {lsb_estimate:.3f} ps")
            
            performance['lsb'] = {
                'unique_values': int(len(unique_values)),
                'estimated_lsb': float(lsb_estimate)
            }
        
        # 4. DNL分析
        print("\n[4] DNL (差分非线性) 分析:")
        print("-" * 50)
        
        if len(valid_diffs) > 0:
            ideal_step = avg_resolution
            dnl = (valid_diffs - ideal_step) / ideal_step
            
            print(f"  DNL 最大值: {dnl.max():.3f} LSB")
            print(f"  DNL 最小值: {dnl.min():.3f} LSB")
            print(f"  DNL RMS: {np.sqrt(np.mean(dnl**2)):.3f} LSB")
            
            performance['dnl'] = {
                'max': float(dnl.max()),
                'min': float(dnl.min()),
                'rms': float(np.sqrt(np.mean(dnl**2)))
            }
        
        # 5. INL分析
        print("\n[5] INL (积分非线性) 分析:")
        print("-" * 50)
        
        if len(sorted_times) > 2:
            coeffs = np.polyfit(sorted_phases, sorted_times, 1)
            ideal_line = np.polyval(coeffs, sorted_phases)
            inl = sorted_times - ideal_line
            
            if len(valid_diffs) > 0:
                inl_lsb = inl / avg_resolution
                
                print(f"  拟合斜率: {coeffs[0]:.3f} ps/phase (理论: {-self.PHASE_STEP:.2f})")
                print(f"  INL 最大值: {inl_lsb.max():.3f} LSB ({inl.max():.2f} ps)")
                print(f"  INL 最小值: {inl_lsb.min():.3f} LSB ({inl.min():.2f} ps)")
                print(f"  INL RMS: {np.sqrt(np.mean(inl_lsb**2)):.3f} LSB")
                
                performance['inl'] = {
                    'max_lsb': float(inl_lsb.max()),
                    'min_lsb': float(inl_lsb.min()),
                    'rms_lsb': float(np.sqrt(np.mean(inl_lsb**2)))
                }
        
        # 6. 单调性检查
        print("\n[6] 单调性分析:")
        print("-" * 50)
        
        valid_transitions = time_diffs[jump_mask]
        monotonic_decreases = np.sum(valid_transitions < 0)
        total_valid = len(valid_transitions)
        
        print(f"  有效转换数: {total_valid}")
        print(f"  递减转换: {monotonic_decreases} ({(monotonic_decreases/total_valid)*100:.1f}%)")
        
        performance['monotonicity'] = {
            'decreases': int(monotonic_decreases),
            'total': int(total_valid)
        }
        
        print("\n" + "="*70 + "\n")
        
        return performance
    
    def save_to_file(self, filename=None, output_dir='tdc_results'):
        """保存数据到文件"""
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"[INFO] 创建输出目录: {output_dir}")
        
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"tdc_uart_scan_{timestamp}.txt"
        
        filepath = os.path.join(output_dir, filename)
        
        try:
            with open(filepath, 'w') as f:
                f.write("# TDC UART 扫描数据\n")
                f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("# Index, Type, ID, Fine, Flag, Coarse, Raw_Hex\n")
                
                for i, d in enumerate(self.data_list):
                    type_str = "UP" if d['type'] == 0b00 else ("DOWN" if d['type'] == 0b01 else "INFO")
                    flag = d.get('flag', 0)
                    f.write(f"{i},{type_str},{d['id']},{d['fine']},{flag},{d['coarse']},0x{d['raw']:08X}\n")
            
            print(f"[INFO] 数据已保存到: {filepath}")
            return filepath
        except Exception as e:
            print(f"[ERROR] 保存失败: {e}")
            return None
    
    def plot(self, save_file=None):
        """绘制数据图表"""
        if not PLOT_AVAILABLE:
            print("[WARN] matplotlib 不可用，无法绘图")
            return
        
        if len(self.data_list) == 0:
            print("[WARN] 没有数据可绘制")
            return
        
        show_performance = len(self.up_data) >= 10
        
        if show_performance:
            fig, axes = plt.subplots(4, 2, figsize=(14, 20))
        else:
            fig, axes = plt.subplots(3, 2, figsize=(14, 15))
        
        fig.suptitle('TDC UART 扫描数据分析', fontsize=16, fontweight='bold')
        
        # 子图1: UP通道 Fine Time
        if len(self.up_data) > 0:
            up_ids = [d['id'] for d in self.up_data]
            up_fine = np.array([d['fine'] for d in self.up_data])
            
            axes[0, 0].plot(up_ids, up_fine, 'b.-', markersize=3, linewidth=1)
            axes[0, 0].set_xlabel('相位索引 (Phase ID)')
            axes[0, 0].set_ylabel('Fine Time (ps)')
            axes[0, 0].set_title('UP 通道 - Fine Time')
            axes[0, 0].grid(True, alpha=0.3)
        
        # 子图2: DOWN通道 Fine Time
        if len(self.down_data) > 0:
            down_ids = [d['id'] for d in self.down_data]
            down_fine = np.array([d['fine'] for d in self.down_data])
            
            axes[0, 1].plot(down_ids, down_fine, 'r.-', markersize=3, linewidth=1)
            axes[0, 1].set_xlabel('相位索引 (Phase ID)')
            axes[0, 1].set_ylabel('Fine Time (ps)')
            axes[0, 1].set_title('DOWN 通道 - Fine Time')
            axes[0, 1].grid(True, alpha=0.3)
        
        # 子图3: UP通道 Coarse Time
        if len(self.up_data) > 0:
            up_ids = [d['id'] for d in self.up_data]
            up_coarse = np.array([d['coarse'] for d in self.up_data])
            
            axes[1, 0].plot(up_ids, up_coarse, 'b.-', markersize=3, linewidth=1)
            axes[1, 0].set_xlabel('相位索引 (Phase ID)')
            axes[1, 0].set_ylabel('Coarse Count (低8位)')
            axes[1, 0].set_title('UP 通道 - Coarse Count')
            axes[1, 0].grid(True, alpha=0.3)
        
        # 子图4: DOWN通道 Coarse Time
        if len(self.down_data) > 0:
            down_ids = [d['id'] for d in self.down_data]
            down_coarse = np.array([d['coarse'] for d in self.down_data])
            
            axes[1, 1].plot(down_ids, down_coarse, 'r.-', markersize=3, linewidth=1)
            axes[1, 1].set_xlabel('相位索引 (Phase ID)')
            axes[1, 1].set_ylabel('Coarse Count (低8位)')
            axes[1, 1].set_title('DOWN 通道 - Coarse Count')
            axes[1, 1].grid(True, alpha=0.3)
        
        # 子图5: Fine Time 分布
        if len(self.up_data) > 0:
            up_fine = np.array([d['fine'] for d in self.up_data])
            axes[2, 0].hist(up_fine, bins=50, alpha=0.7, color='blue', edgecolor='black', label='UP')
        
        if len(self.down_data) > 0:
            down_fine = np.array([d['fine'] for d in self.down_data])
            axes[2, 0].hist(down_fine, bins=50, alpha=0.7, color='red', edgecolor='black', label='DOWN')
        
        axes[2, 0].set_xlabel('Fine Count')
        axes[2, 0].set_ylabel('频数')
        axes[2, 0].set_title('Fine Count 分布')
        axes[2, 0].legend()
        axes[2, 0].grid(True, alpha=0.3)
        
        # 子图6: 扫描曲线对比
        if len(self.up_data) > 0:
            up_ids = np.array([d['id'] for d in self.up_data])
            up_fine = np.array([d['fine'] for d in self.up_data])
            axes[2, 1].plot(up_ids, up_fine, 'b.-', markersize=2, linewidth=1, label='UP', alpha=0.7)
        
        if len(self.down_data) > 0:
            down_ids = np.array([d['id'] for d in self.down_data])
            down_fine = np.array([d['fine'] for d in self.down_data])
            axes[2, 1].plot(down_ids, down_fine, 'r.-', markersize=2, linewidth=1, label='DOWN', alpha=0.7)
        
        axes[2, 1].set_xlabel('相位索引 (Phase ID)')
        axes[2, 1].set_ylabel('Fine Time (ps)')
        axes[2, 1].set_title('Fine Time 扫描曲线对比')
        axes[2, 1].legend()
        axes[2, 1].grid(True, alpha=0.3)
        
        # DNL和INL图（如果有足够数据）
        if show_performance and len(self.up_data) >= 10:
            up_fine = np.array([d['fine'] for d in self.up_data])
            up_ids = np.array([d['id'] for d in self.up_data])
            
            sorted_indices = np.argsort(up_ids)
            sorted_phases = up_ids[sorted_indices]
            sorted_times = up_fine[sorted_indices]
            
            # DNL图
            if len(sorted_times) > 1:
                time_diffs = np.diff(sorted_times)
                valid_mask = np.abs(time_diffs) < self.CLK_PERIOD/2
                valid_diffs = time_diffs[valid_mask]
                valid_phases = sorted_phases[:-1][valid_mask]
                
                if len(valid_diffs) > 0:
                    ideal_step = np.abs(valid_diffs).mean()
                    dnl = (valid_diffs - ideal_step) / ideal_step
                    
                    axes[3, 0].plot(valid_phases, dnl, 'g.-', markersize=2, linewidth=1)
                    axes[3, 0].axhline(y=0, color='r', linestyle='--', linewidth=1, alpha=0.5)
                    axes[3, 0].set_xlabel('相位索引 (Phase ID)')
                    axes[3, 0].set_ylabel('DNL (LSB)')
                    axes[3, 0].set_title(f'DNL 分析 (RMS={np.sqrt(np.mean(dnl**2)):.3f} LSB)')
                    axes[3, 0].grid(True, alpha=0.3)
            
            # INL图
            if len(sorted_times) > 2 and len(valid_diffs) > 0:
                coeffs = np.polyfit(sorted_phases, sorted_times, 1)
                ideal_line = np.polyval(coeffs, sorted_phases)
                inl = sorted_times - ideal_line
                inl_lsb = inl / ideal_step
                
                axes[3, 1].plot(sorted_phases, inl_lsb, 'm.-', markersize=2, linewidth=1)
                axes[3, 1].axhline(y=0, color='r', linestyle='--', linewidth=1, alpha=0.5)
                axes[3, 1].set_xlabel('相位索引 (Phase ID)')
                axes[3, 1].set_ylabel('INL (LSB)')
                axes[3, 1].set_title(f'INL 分析 (RMS={np.sqrt(np.mean(inl_lsb**2)):.3f} LSB)')
                axes[3, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_file:
            plt.savefig(save_file, dpi=300, bbox_inches='tight')
            print(f"[INFO] 图表已保存到: {save_file}")
        else:
            plt.show()


def show_menu():
    """显示主菜单"""
    print("\n" + "="*70)
    print("TDC UART 扫描测试程序 - 交互式菜单")
    print("="*70)
    print("\n请选择操作:")
    print("  1. 全扫描 (0-224, 双通道) [推荐]")
    print("  2. 全扫描 (指定结束相位)")
    print("  3. 单步测试 (指定相位)")
    print("  4. 单通道测试 (UP only)")
    print("  5. 单通道测试 (DOWN only)")
    print("  6. 连续单步扫描 (0-224)")
    print("  7. 校准 TDC")
    print("  8. 像素芯片激励控制")
    print("  9. 更换串口")
    print("  0. 退出程序")
    print("="*70)


def get_user_input(prompt, default=None, value_type=int, valid_range=None):
    """获取用户输入并验证"""
    while True:
        try:
            if default is not None:
                user_input = input(f"{prompt} [默认={default}]: ").strip()
                if not user_input:
                    return default
            else:
                user_input = input(f"{prompt}: ").strip()
            
            value = value_type(user_input)
            
            if valid_range:
                min_val, max_val = valid_range
                if not (min_val <= value <= max_val):
                    print(f"[错误] 输入超出范围 ({min_val}-{max_val})")
                    continue
            
            return value
        except ValueError:
            print(f"[错误] 无效输入")
        except KeyboardInterrupt:
            print("\n[INFO] 用户取消输入")
            return None


def execute_scan(scanner, scan_mode, phase, channel):
    """执行扫描测试"""
    mode_names = {0: '单步测试', 1: '全扫描'}
    ch_names = ['无', 'DOWN', 'UP', 'BOTH']
    
    # 计算期望数据量
    if scan_mode == 0:
        expected_data_count = 2 if channel == 0b11 else 1
    else:
        samples = phase + 1
        expected_data_count = samples * 2 if channel == 0b11 else samples
    
    print(f"\n" + "="*70)
    print("测试配置:")
    print(f"  模式: {mode_names[scan_mode]}")
    if scan_mode == 0:
        print(f"  测试相位: {phase}")
    else:
        print(f"  扫描范围: 0 到 {phase}")
    print(f"  通道: {ch_names[channel]}")
    print(f"  期望数据: {expected_data_count} 个")
    print("="*70)
    
    confirm = input("\n是否开始测试? (y/n) [y]: ").strip().lower()
    if confirm and confirm not in ['y', 'yes']:
        print("[INFO] 测试已取消")
        return False
    
    try:
        print(f"\n[1/3] 启动测试...")
        if not scanner.start_scan(scan_mode=scan_mode, phase=phase, channel=channel):
            print("[ERROR] 启动测试失败")
            return False
        
        print(f"\n[2/3] 接收数据...")
        # UART速度较慢，需要更长超时
        timeout = max(10.0, expected_data_count * 0.02)  # 每个数据包约20ms
        data = scanner.receive_data(expected_count=expected_data_count, timeout=timeout)
        
        if len(data) == 0:
            print("[ERROR] 没有接收到数据")
            return False
        
        print(f"\n[3/3] 处理数据...")
        processor = TDCDataProcessor(data)
        processor.process()
        
        # 保存数据
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        mode_suffix = 'single' if scan_mode == 0 else 'scan'
        ch_suffix = ch_names[channel].lower()
        data_filename = f"tdc_uart_{mode_suffix}_{ch_suffix}_{timestamp}.txt"
        processor.save_to_file(data_filename)
        
        # 绘图
        if PLOT_AVAILABLE and len(data) > 10:
            plot_filename = data_filename.replace('.txt', '.png')
            plot_file = os.path.join('tdc_results', plot_filename)
            processor.plot(save_file=plot_file)
        
        print("\n[INFO] 测试完成!")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def execute_pixel_stimulus(scanner):
    """执行像素芯片激励控制"""
    print("\n" + "="*70)
    print("像素芯片激励控制")
    print("="*70)
    print("\n选择激励模式:")
    print("  1. 单路激励 (CSA_0 ~ CSA_5)")
    print("  2. 多路激励 (自定义组合)")
    print("  3. 复位信号 (RST)")
    print("  4. 复位 + 激励组合")
    print("  0. 返回主菜单")
    
    mode = get_user_input("请选择模式", default=1, value_type=int, valid_range=(0, 4))
    if mode is None or mode == 0:
        return False
    
    csa_mask = 0
    rst = False
    
    if mode == 1:
        # 单路激励
        csa_num = get_user_input("请选择CSA通道 (0-5)", default=0, value_type=int, valid_range=(0, 5))
        if csa_num is None:
            return False
        csa_mask = 1 << csa_num
    
    elif mode == 2:
        # 多路激励
        print("\n请输入要激励的CSA通道 (多个通道用空格分隔, 例如: 0 2 4)")
        channels_input = input("CSA通道: ").strip()
        if not channels_input:
            print("[ERROR] 无效输入")
            return False
        
        try:
            channels = [int(ch) for ch in channels_input.split()]
            for ch in channels:
                if 0 <= ch <= 5:
                    csa_mask |= (1 << ch)
                else:
                    print(f"[WARN] 通道 {ch} 超出范围，已忽略")
        except ValueError:
            print("[ERROR] 无效输入")
            return False
    
    elif mode == 3:
        # 仅复位
        rst = True
    
    elif mode == 4:
        # 复位 + 激励
        rst = True
        print("\n请输入要激励的CSA通道 (多个通道用空格分隔, 例如: 0 2 4)")
        channels_input = input("CSA通道: ").strip()
        if channels_input:
            try:
                channels = [int(ch) for ch in channels_input.split()]
                for ch in channels:
                    if 0 <= ch <= 5:
                        csa_mask |= (1 << ch)
                    else:
                        print(f"[WARN] 通道 {ch} 超出范围，已忽略")
            except ValueError:
                print("[ERROR] 无效输入")
                return False
    
    # 显示配置
    print("\n激励配置:")
    if rst:
        print("  RST: 使能")
    if csa_mask:
        active_channels = [i for i in range(6) if (csa_mask >> i) & 0x1]
        print(f"  CSA: {', '.join([f'CSA_{i}' for i in active_channels])}")
    
    # 询问脉冲数量
    pulse_count = get_user_input("请输入脉冲数量", default=100, value_type=int, valid_range=(1, 100000))
    if pulse_count is None:
        return False
    
    print(f"  脉冲数量: {pulse_count}")
    
    # 计算期望接收的数据量
    # 每个脉冲会产生UP和DOWN两路信号，所以数据量是脉冲数的2倍
    expected_data_count = pulse_count * 2
    print(f"  期望数据: {expected_data_count} 个 ({pulse_count} 脉冲 × 2 通道)")
    
    confirm = input("\n确认发送? (y/n) [y]: ").strip().lower()
    if confirm and confirm not in ['y', 'yes']:
        print("[INFO] 已取消")
        return False
    
    try:
        print("\n[1/3] 发送激励信号...")
        if not scanner.send_pixel_stimulus(csa_mask=csa_mask, rst=rst):
            print("[ERROR] 发送失败")
            return False
        
        print("[INFO] 激励信号已发送")
        
        print(f"\n[2/3] 接收测量数据...")
        # 根据脉冲数量和波特率估算超时时间
        # 每个数据包4字节，115200 baud ≈ 11520 字节/秒
        # 预留额外时间用于处理
        timeout = max(10.0, expected_data_count * 4 / 11520 * 2)
        print(f"[INFO] 接收超时设置: {timeout:.1f} 秒")
        
        data = scanner.receive_data(expected_count=expected_data_count, timeout=timeout)
        
        if len(data) == 0:
            print("[ERROR] 没有接收到数据")
            return False
        
        print(f"\n[3/3] 处理数据 (收到 {len(data)}/{expected_data_count} 个)")
        processor = TDCDataProcessor(data)
        processor.process()
        
        # 分析像素芯片激励的延时特性
        analyze_pixel_delay(data, pulse_count)
        
        # 保存数据
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csa_str = ''.join([str(i) for i in range(6) if (csa_mask >> i) & 0x1])
        rst_str = '_rst' if rst else ''
        data_filename = f"pixel_stimulus_csa{csa_str}{rst_str}_{pulse_count}pulses_{timestamp}.txt"
        processor.save_to_file(data_filename)
        
        # 绘图
        if PLOT_AVAILABLE and len(data) > 10:
            plot_filename = data_filename.replace('.txt', '.png')
            plot_file = os.path.join('tdc_results', plot_filename)
            processor.plot(save_file=plot_file)
        
        print("\n[INFO] 像素激励测试完成!")
        return True
        
    except Exception as e:
        print(f"[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def execute_continuous_single_scan(scanner, start_phase, end_phase, channel):
    """执行连续单步扫描"""
    ch_names = ['无', 'DOWN', 'UP', 'BOTH']
    
    samples = end_phase - start_phase + 1
    expected_total = samples * 2 if channel == 0b11 else samples
    
    print(f"\n" + "="*70)
    print("连续单步扫描配置:")
    print(f"  扫描范围: {start_phase} 到 {end_phase}")
    print(f"  通道: {ch_names[channel]}")
    print(f"  总命令数: {samples} 条")
    print(f"  期望数据: {expected_total} 个")
    print("="*70)
    
    confirm = input("\n是否开始测试? (y/n) [y]: ").strip().lower()
    if confirm and confirm not in ['y', 'yes']:
        print("[INFO] 测试已取消")
        return False
    
    try:
        all_data = []
        print(f"\n[INFO] 开始连续单步扫描...")
        
        for phase in range(start_phase, end_phase + 1):
            if phase % 10 == 0 or phase == start_phase:
                print(f"\n[进度] 相位 {phase}/{end_phase}")
            
            if not scanner.start_scan(scan_mode=0, phase=phase, channel=channel):
                print(f"[ERROR] 相位 {phase} 命令发送失败")
                continue
            
            expected_count = 2 if channel == 0b11 else 1
            data = scanner.receive_data(expected_count=expected_count, timeout=5.0)
            
            if len(data) == 0:
                print(f"[WARN] 相位 {phase} 未收到数据")
                continue
            
            all_data.extend(data)
            time.sleep(0.05)
        
        print(f"\n[INFO] 扫描完成! 共收到 {len(all_data)}/{expected_total} 个数据")
        
        if len(all_data) == 0:
            print("[ERROR] 没有接收到任何数据")
            return False
        
        processor = TDCDataProcessor(all_data)
        processor.process()
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        ch_suffix = ch_names[channel].lower()
        data_filename = f"tdc_uart_continuous_{ch_suffix}_{timestamp}.txt"
        processor.save_to_file(data_filename)
        
        if PLOT_AVAILABLE and len(all_data) > 10:
            plot_filename = data_filename.replace('.txt', '.png')
            plot_file = os.path.join('tdc_results', plot_filename)
            processor.plot(save_file=plot_file)
        
        print("\n[INFO] 测试完成!")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def analyze_pixel_delay(data_list, pulse_count):
    """
    分析像素芯片激励产生的UP/DOWN延时特性
    
    Args:
        data_list: 接收到的数据列表
        pulse_count: 激励脉冲数量
    """
    if not PLOT_AVAILABLE:
        print("\n[WARN] numpy不可用，跳过延时分析")
        return
    
    print("\n" + "="*70)
    print("像素芯片激励 - UP/DOWN 延时分析")
    print("="*70)
    
    # 分离UP和DOWN通道数据
    up_data = [d for d in data_list if d['type'] == 0b00 or d.get('flag') == 1]
    down_data = [d for d in data_list if d['type'] == 0b01 or d.get('flag') == 0]
    
    print(f"\n数据统计:")
    print(f"  总数据包: {len(data_list)}")
    print(f"  UP 通道: {len(up_data)} 个")
    print(f"  DOWN 通道: {len(down_data)} 个")
    print(f"  期望数据: {pulse_count * 2} 个 ({pulse_count} × 2)")
    
    if len(up_data) == 0 or len(down_data) == 0:
        print("[WARN] 缺少UP或DOWN通道数据，无法分析延时")
        return
    
    # 提取时间信息
    up_fine = np.array([d['fine'] for d in up_data])
    up_coarse = np.array([d['coarse'] for d in up_data])
    down_fine = np.array([d['fine'] for d in down_data])
    down_coarse = np.array([d['coarse'] for d in down_data])
    
    # 时间常数
    CLK_PERIOD = 3846  # ps (260MHz)
    
    # 计算总时间 (粗计数 + 精细时间)
    up_total_time = up_coarse * CLK_PERIOD + up_fine
    down_total_time = down_coarse * CLK_PERIOD + down_fine
    
    print(f"\nUP 通道时间统计:")
    print(f"  Fine 范围: {up_fine.min()} - {up_fine.max()} ps")
    print(f"  Fine 平均: {up_fine.mean():.2f} ps")
    print(f"  Fine 标准差: {up_fine.std():.2f} ps")
    print(f"  Coarse 范围: {up_coarse.min()} - {up_coarse.max()}")
    
    print(f"\nDOWN 通道时间统计:")
    print(f"  Fine 范围: {down_fine.min()} - {down_fine.max()} ps")
    print(f"  Fine 平均: {down_fine.mean():.2f} ps")
    print(f"  Fine 标准差: {down_fine.std():.2f} ps")
    print(f"  Coarse 范围: {down_coarse.min()} - {down_coarse.max()}")
    
    # 计算相对延时（取相同索引的UP和DOWN对比）
    min_len = min(len(up_data), len(down_data))
    if min_len > 0:
        up_fine_arr = up_fine[:min_len]
        up_coarse_arr = up_coarse[:min_len]
        down_fine_arr = down_fine[:min_len]
        down_coarse_arr = down_coarse[:min_len]
        
        # 使用TDC延时计算公式：(coarse_a - coarse_b) * T - (fine_a - fine_b)
        # UP作为a，DOWN作为b
        time_delay = (up_coarse_arr - down_coarse_arr) * CLK_PERIOD - (up_fine_arr - down_fine_arr)
        
        print(f"\nUP-DOWN 延时计算 (配对分析，{min_len}对):")
        print(f"  公式: (Coarse_UP - Coarse_DOWN) × {CLK_PERIOD} ps - (Fine_UP - Fine_DOWN)")
        print(f"  平均延时: {time_delay.mean():.2f} ps")
        print(f"  标准差: {time_delay.std():.2f} ps")
        print(f"  最小延时: {time_delay.min():.2f} ps")
        print(f"  最大延时: {time_delay.max():.2f} ps")
        print(f"  延时范围: {time_delay.max() - time_delay.min():.2f} ps")
        
        # 显示前10对数据的详细计算
        if min_len >= 10:
            print(f"\n前10对数据详细计算:")
            print(f"  {'ID':<6} {'Coarse_UP':<10} {'Coarse_DN':<10} {'Fine_UP':<10} {'Fine_DN':<10} {'Delay(ps)':<12}")
            print(f"  {'-'*66}")
            for i in range(min(10, min_len)):
                delay_val = time_delay[i]
                print(f"  {i:<6} {up_coarse_arr[i]:<10} {down_coarse_arr[i]:<10} "
                      f"{up_fine_arr[i]:<10} {down_fine_arr[i]:<10} {delay_val:<12.2f}")
    
    # Fine值稳定性分析
    print(f"\nFine值稳定性分析:")
    print(f"  UP Fine 唯一值数: {len(np.unique(up_fine))}")
    print(f"  DOWN Fine 唯一值数: {len(np.unique(down_fine))}")
    
    if len(up_fine) > 1:
        up_fine_changes = np.sum(np.diff(up_fine) != 0)
        print(f"  UP Fine 变化次数: {up_fine_changes}/{len(up_fine)-1} ({up_fine_changes/(len(up_fine)-1)*100:.1f}%)")
    
    if len(down_fine) > 1:
        down_fine_changes = np.sum(np.diff(down_fine) != 0)
        print(f"  DOWN Fine 变化次数: {down_fine_changes}/{len(down_fine)-1} ({down_fine_changes/(len(down_fine)-1)*100:.1f}%)")
    
    # 如果数据量适中，显示分布直方图信息
    if 10 <= len(up_fine) <= 10000:
        up_hist, up_bins = np.histogram(up_fine, bins=50)
        most_common_bin = np.argmax(up_hist)
        print(f"  UP Fine 最常见值范围: {up_bins[most_common_bin]:.1f} - {up_bins[most_common_bin+1]:.1f} ps ({up_hist[most_common_bin]} 次)")
    
    if 10 <= len(down_fine) <= 10000:
        down_hist, down_bins = np.histogram(down_fine, bins=50)
        most_common_bin = np.argmax(down_hist)
        print(f"  DOWN Fine 最常见值范围: {down_bins[most_common_bin]:.1f} - {down_bins[most_common_bin+1]:.1f} ps ({down_hist[most_common_bin]} 次)")
    
    print("\n" + "="*70)


def main():
    """主程序"""
    if not SERIAL_AVAILABLE:
        print("[ERROR] pyserial 未安装，请执行: pip install pyserial")
        return 1
    
    print("="*70)
    print("TDC UART 扫描测试程序")
    print("="*70)
    
    # 创建扫描器
    scanner = TDCUartScanner(baudrate=115200)
    
    # 连接到串口
    if not scanner.connect():
        print("[ERROR] 无法连接到串口")
        return 1
    
    try:
        while True:
            show_menu()
            
            choice = get_user_input("请输入选项", default=1, value_type=int, valid_range=(0, 9))
            if choice is None:
                continue
            
            if choice == 0:
                print("\n[INFO] 退出程序")
                break
            
            elif choice == 1:
                execute_scan(scanner, scan_mode=1, phase=224, channel=0b11)
            
            elif choice == 2:
                phase = get_user_input("请输入结束相位 (0-255)", default=224, 
                                      value_type=int, valid_range=(0, 255))
                if phase is not None:
                    execute_scan(scanner, scan_mode=1, phase=phase, channel=0b11)
            
            elif choice == 3:
                phase = get_user_input("请输入测试相位 (0-255)", default=0, 
                                      value_type=int, valid_range=(0, 255))
                if phase is not None:
                    execute_scan(scanner, scan_mode=0, phase=phase, channel=0b11)
            
            elif choice == 4:
                print("\n选择测试模式:")
                print("  1. 单步测试")
                print("  2. 全扫描")
                mode_choice = get_user_input("请选择", default=2, value_type=int, valid_range=(1, 2))
                if mode_choice == 1:
                    phase = get_user_input("请输入测试相位", default=0, 
                                          value_type=int, valid_range=(0, 255))
                    if phase is not None:
                        execute_scan(scanner, scan_mode=0, phase=phase, channel=0b10)
                else:
                    phase = get_user_input("请输入结束相位", default=224, 
                                          value_type=int, valid_range=(0, 255))
                    if phase is not None:
                        execute_scan(scanner, scan_mode=1, phase=phase, channel=0b10)
            
            elif choice == 5:
                print("\n选择测试模式:")
                print("  1. 单步测试")
                print("  2. 全扫描")
                mode_choice = get_user_input("请选择", default=2, value_type=int, valid_range=(1, 2))
                if mode_choice == 1:
                    phase = get_user_input("请输入测试相位", default=0, 
                                          value_type=int, valid_range=(0, 255))
                    if phase is not None:
                        execute_scan(scanner, scan_mode=0, phase=phase, channel=0b01)
                else:
                    phase = get_user_input("请输入结束相位", default=224, 
                                          value_type=int, valid_range=(0, 255))
                    if phase is not None:
                        execute_scan(scanner, scan_mode=1, phase=phase, channel=0b01)
            
            elif choice == 6:
                print("\n选择通道:")
                print("  1. UP 通道")
                print("  2. DOWN 通道")
                print("  3. 双通道 (BOTH)")
                ch_choice = get_user_input("请选择", default=3, value_type=int, valid_range=(1, 3))
                if ch_choice is None:
                    continue
                
                channel_map = {1: 0b10, 2: 0b01, 3: 0b11}
                channel = channel_map[ch_choice]
                
                start_phase = get_user_input("请输入起始相位", default=0, 
                                            value_type=int, valid_range=(0, 255))
                if start_phase is None:
                    continue
                
                end_phase = get_user_input("请输入结束相位", default=224, 
                                          value_type=int, valid_range=(start_phase, 255))
                if end_phase is not None:
                    execute_continuous_single_scan(scanner, start_phase, end_phase, channel)
            
            elif choice == 7:
                print("\n[INFO] 启动 TDC 校准...")
                confirm = input("确认启动校准? (y/n) [y]: ").strip().lower()
                if not confirm or confirm in ['y', 'yes']:
                    if scanner.start_calibration():
                        print("[INFO] 校准命令已发送")
                    else:
                        print("[ERROR] 校准命令发送失败")
            
            elif choice == 8:
                execute_pixel_stimulus(scanner)
            
            elif choice == 9:
                scanner.disconnect()
                scanner.port = None
                if not scanner.connect():
                    print("[ERROR] 无法连接到新串口")
                    return 1
            
            print("\n" + "-"*70)
            continue_test = input("按 Enter 继续，输入 q 退出: ").strip().lower()
            if continue_test == 'q':
                print("\n[INFO] 退出程序")
                break
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断")
        return 130
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        scanner.disconnect()


if __name__ == "__main__":
    import sys
    sys.exit(main())
