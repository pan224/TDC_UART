#!/usr/bin/env python3
"""
TDC UART 图形界面（对齐 tdc_uart_scan_internal.py）

功能范围仅对应 scripts/tdc_uart_scan_internal.py（双通道模式）：
- 全扫描 / 自定义全扫描 / 单步扫描
- 连续单步扫描
- 手动校准
- 数据处理、保存和可选绘图
"""

import os
import threading
import traceback
import queue
import math
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from tdc_uart_scan_internal import (
    SERIAL_AVAILABLE,
    PLOT_AVAILABLE,
    TDCUartScanner,
    TDCDataProcessor,
)


class TDCGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TDC UART 图形界面")
        self.root.geometry("1180x820")

        self.scanner = TDCUartScanner(baudrate=115200)
        self.is_busy = False

        self.log_queue = queue.Queue()
        self._build_ui()
        self._refresh_ports()
        self._poll_log_queue()

    def _build_ui(self):
        top = ttk.LabelFrame(self.root, text="串口设置", padding=8)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="端口").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=20, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        ttk.Button(top, text="刷新", command=self._refresh_ports).grid(row=0, column=2, padx=4, pady=4)

        ttk.Label(top, text="波特率").grid(row=0, column=3, padx=4, pady=4, sticky="w")
        self.baud_var = tk.StringVar(value="115200")
        self.baud_combo = ttk.Combobox(top, textvariable=self.baud_var, values=["115200", "2000000", "3000000"], width=10)
        self.baud_combo.grid(row=0, column=4, padx=4, pady=4, sticky="w")

        self.connect_btn = ttk.Button(top, text="连接", command=self._toggle_connect)
        self.connect_btn.grid(row=0, column=5, padx=8, pady=4)

        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(top, textvariable=self.status_var).grid(row=0, column=6, padx=8, pady=4, sticky="w")

        self.busy_var = tk.StringVar(value="空闲")
        ttk.Label(top, textvariable=self.busy_var).grid(row=0, column=7, padx=8, pady=4, sticky="w")

        mid = ttk.Frame(self.root)
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(mid)
        left.pack(side="left", fill="y")

        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self._build_scan_panel(left)

        log_frame = ttk.LabelFrame(right, text="日志", padding=8)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_frame, height=30, wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="left", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=8, pady=8)

        ttk.Button(bottom, text="清空日志", command=self._clear_log).pack(side="left", padx=4)
        ttk.Button(bottom, text="退出", command=self._quit).pack(side="right", padx=4)

    def _build_scan_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="扫描 / 校准", padding=8)
        frame.pack(fill="x", pady=(0, 10))

        ttk.Button(frame, text="重新校准", command=lambda: self._run_task(self._task_calibration)).grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=4
        )

        ttk.Separator(frame, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)

        ttk.Button(
            frame,
            text="全扫描 0..224（双通道）",
            command=lambda: self._run_task(self._task_scan, 1, 224, 0b11),
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=4, pady=4)

        ttk.Label(frame, text="结束相位").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        self.end_phase_var = tk.StringVar(value="224")
        ttk.Entry(frame, textvariable=self.end_phase_var, width=10).grid(row=3, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(
            frame,
            text="自定义全扫描（双通道）",
            command=lambda: self._run_task(self._task_scan_custom_full),
        ).grid(row=3, column=2, sticky="ew", padx=4, pady=2)

        ttk.Label(frame, text="单步相位").grid(row=4, column=0, sticky="w", padx=4, pady=2)
        self.single_phase_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=self.single_phase_var, width=10).grid(row=4, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(
            frame,
            text="单步测试（双通道）",
            command=lambda: self._run_task(self._task_scan_single_both),
        ).grid(row=4, column=2, sticky="ew", padx=4, pady=2)

        ttk.Separator(frame, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=6)

        ttk.Label(frame, text="统计相位").grid(row=6, column=0, sticky="w", padx=4, pady=2)
        self.stat_phase_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=self.stat_phase_var, width=10).grid(row=6, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(frame, text="样本对数 n").grid(row=7, column=0, sticky="w", padx=4, pady=2)
        self.stat_count_var = tk.StringVar(value="200")
        ttk.Entry(frame, textvariable=self.stat_count_var, width=10).grid(row=7, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(
            frame,
            text="单步统计（UP/DOWN交替）",
            command=lambda: self._run_task(self._task_single_step_stats),
        ).grid(row=7, column=2, sticky="ew", padx=4, pady=2)

        ttk.Separator(frame, orient="horizontal").grid(row=8, column=0, columnspan=3, sticky="ew", pady=6)

        ttk.Label(frame, text="全步进样本对数 n").grid(row=9, column=0, sticky="w", padx=4, pady=2)
        self.full_stat_count_var = tk.StringVar(value="30")
        ttk.Entry(frame, textvariable=self.full_stat_count_var, width=10).grid(row=9, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(
            frame,
            text="全步进统计 0..224（均值+标准差）",
            command=lambda: self._run_task(self._task_full_phase_stats),
        ).grid(row=9, column=2, sticky="ew", padx=4, pady=2)

        ttk.Separator(frame, orient="horizontal").grid(row=10, column=0, columnspan=3, sticky="ew", pady=6)

        ttk.Label(frame, text="连续扫描起始").grid(row=11, column=0, sticky="w", padx=4, pady=2)
        self.cont_start_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=self.cont_start_var, width=10).grid(row=11, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(frame, text="连续扫描结束").grid(row=12, column=0, sticky="w", padx=4, pady=2)
        self.cont_end_var = tk.StringVar(value="224")
        ttk.Entry(frame, textvariable=self.cont_end_var, width=10).grid(row=12, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(frame, text="通道（固定）").grid(row=13, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(frame, text="BOTH").grid(row=13, column=1, sticky="w", padx=4, pady=2)

        ttk.Button(
            frame,
            text="执行连续单步扫描",
            command=lambda: self._run_task(self._task_continuous_scan),
        ).grid(row=14, column=0, columnspan=3, sticky="ew", padx=4, pady=6)

        for col in range(3):
            frame.grid_columnconfigure(col, weight=1)

    def _refresh_ports(self):
        if not SERIAL_AVAILABLE:
            self._log("[错误] 未检测到 pyserial，请安装: pip install pyserial")
            return
        ports = TDCUartScanner.list_ports()
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        if self.scanner.connected:
            self.scanner.disconnect()
            self.status_var.set("未连接")
            self.connect_btn.configure(text="连接")
            self._log("[INFO] 已断开连接")
            return

        if self.is_busy:
            messagebox.showwarning("忙碌", "当前任务正在执行，请稍候。")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("端口", "请选择串口。")
            return

        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            messagebox.showerror("波特率", "波特率格式无效。")
            return

        self.scanner.port = port
        self.scanner.baudrate = baud
        ok = self.scanner.connect()
        if ok:
            self.status_var.set(f"已连接: {port} @ {baud}")
            self.connect_btn.configure(text="断开")
            self._log(f"[INFO] 已连接到 {port} @ {baud}")
        else:
            self.status_var.set("未连接")
            messagebox.showerror("连接失败", "串口连接失败。")

    def _run_task(self, func, *args):
        if self.is_busy:
            messagebox.showwarning("忙碌", "已有任务在运行。")
            return
        if not self.scanner.connected:
            messagebox.showerror("未连接", "请先连接串口。")
            return

        self.is_busy = True
        self.busy_var.set("运行中")

        thread = threading.Thread(target=self._task_wrapper, args=(func, args), daemon=True)
        thread.start()

    def _task_wrapper(self, func, args):
        try:
            func(*args)
        except Exception as exc:
            self._log(f"[ERROR] {exc}")
            self._log(traceback.format_exc())
        finally:
            self.root.after(0, self._on_task_done)

    def _on_task_done(self):
        self.is_busy = False
        self.busy_var.set("空闲")

    def _validate_phase(self, value: str, min_value=0, max_value=255):
        try:
            iv = int(value)
        except ValueError:
            raise ValueError(f"无效整数输入: {value}")
        if iv < min_value or iv > max_value:
            raise ValueError(f"相位超出范围 [{min_value}, {max_value}]: {iv}")
        return iv

    def _validate_positive_int(self, value: str, min_value=1, max_value=1000000):
        try:
            iv = int(value)
        except ValueError:
            raise ValueError(f"无效整数输入: {value}")
        if iv < min_value or iv > max_value:
            raise ValueError(f"数值超出范围 [{min_value}, {max_value}]: {iv}")
        return iv

    def _task_calibration(self):
        self._log("[任务] 发送校准命令")
        ok = self.scanner.start_calibration()
        self._log("[信息] 校准命令已发送" if ok else "[错误] 校准命令发送失败")

    def _task_scan_custom_full(self):
        phase = self._validate_phase(self.end_phase_var.get(), 0, 255)
        self._task_scan(1, phase, 0b11)

    def _task_scan_single_both(self):
        phase = self._validate_phase(self.single_phase_var.get(), 0, 255)
        self._task_scan(0, phase, 0b11)

    def _task_single_step_stats(self):
        phase = self._validate_phase(self.stat_phase_var.get(), 0, 255)
        pair_count = self._validate_positive_int(self.stat_count_var.get(), 1, 200000)

        up_fine_ps = []
        down_fine_ps = []
        max_retries = 3

        self._log("=" * 60)
        self._log(f"[任务] 单步统计测试 相位={phase}, 样本对数={pair_count}")
        self._log("[信息] 每次发送 BOTH 命令，分别统计 UP 与 DOWN 的分布")

        for i in range(pair_count):
            if i == 0 or (i + 1) % 20 == 0 or (i + 1) == pair_count:
                self._log(f"[信息] 采样进度 {i + 1}/{pair_count}")

            up_pkt = None
            down_pkt = None
            success = False

            for attempt in range(1, max_retries + 1):
                ok = self.scanner.start_scan(scan_mode=0, phase=phase, channel=TDCUartScanner.CH_BOTH)
                if not ok:
                    if attempt == max_retries:
                        self._log(f"[警告] 第{i + 1}对: 命令发送失败 (重试{max_retries}次)")
                    continue

                rx_data = self.scanner.receive_data(expected_count=2, timeout=4.0)
                if not rx_data:
                    if attempt == max_retries:
                        self._log(f"[警告] 第{i + 1}对: 未收到配对数据 (重试{max_retries}次)")
                    continue

                up_pkt = next((d for d in rx_data if d.get('type') == TDCUartScanner.TYPE_UP), None)
                down_pkt = next((d for d in rx_data if d.get('type') == TDCUartScanner.TYPE_DOWN), None)
                if up_pkt is not None and down_pkt is not None:
                    success = True
                    break

                if attempt == max_retries:
                    self._log(f"[警告] 第{i + 1}对: 数据不完整(缺UP或DOWN), 已重试{max_retries}次")

            if not success:
                continue

            up_fine_ps.append(float(up_pkt['fine']))
            down_fine_ps.append(float(down_pkt['fine']))

        valid_n = min(len(up_fine_ps), len(down_fine_ps))
        if valid_n == 0:
            self._log("[错误] 未得到任何有效样本，无法统计")
            return

        up_mean_ps = sum(up_fine_ps) / len(up_fine_ps)
        up_var_ps2 = sum((x - up_mean_ps) ** 2 for x in up_fine_ps) / len(up_fine_ps)
        up_std_ps = math.sqrt(up_var_ps2)
        up_min_ps = min(up_fine_ps)
        up_max_ps = max(up_fine_ps)

        down_mean_ps = sum(down_fine_ps) / len(down_fine_ps)
        down_var_ps2 = sum((x - down_mean_ps) ** 2 for x in down_fine_ps) / len(down_fine_ps)
        down_std_ps = math.sqrt(down_var_ps2)
        down_min_ps = min(down_fine_ps)
        down_max_ps = max(down_fine_ps)

        self._log("-" * 60)
        self._log(f"[结果] 有效样本对数: {valid_n}/{pair_count}")
        self._log(f"[结果][UP] 均值/方差/标准差: {up_mean_ps:.3f} ps / {up_var_ps2:.3f} ps^2 / {up_std_ps:.3f} ps")
        self._log(f"[结果][UP] 最小/最大: {up_min_ps:.3f} / {up_max_ps:.3f} ps")
        self._log(f"[结果][DOWN] 均值/方差/标准差: {down_mean_ps:.3f} ps / {down_var_ps2:.3f} ps^2 / {down_std_ps:.3f} ps")
        self._log(f"[结果][DOWN] 最小/最大: {down_min_ps:.3f} / {down_max_ps:.3f} ps")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("tdc_results", exist_ok=True)
        summary_file = os.path.join("tdc_results", f"single_step_stats_phase{phase}_{timestamp}.txt")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("# Single-step BOTH-command statistics (UP and DOWN separately)\n")
            f.write(f"phase={phase}\n")
            f.write(f"requested_pairs={pair_count}\n")
            f.write(f"valid_pairs={valid_n}\n")
            f.write("\n[UP]\n")
            f.write(f"mean_ps={up_mean_ps:.6f}\n")
            f.write(f"variance_ps2={up_var_ps2:.6f}\n")
            f.write(f"std_ps={up_std_ps:.6f}\n")
            f.write(f"min_ps={up_min_ps:.6f}\n")
            f.write(f"max_ps={up_max_ps:.6f}\n")
            f.write("\n[DOWN]\n")
            f.write(f"mean_ps={down_mean_ps:.6f}\n")
            f.write(f"variance_ps2={down_var_ps2:.6f}\n")
            f.write(f"std_ps={down_std_ps:.6f}\n")
            f.write(f"min_ps={down_min_ps:.6f}\n")
            f.write(f"max_ps={down_max_ps:.6f}\n")
            f.write("\n# up_fine_ps list\n")
            for v in up_fine_ps:
                f.write(f"{v:.6f}\n")
            f.write("\n# down_fine_ps list\n")
            for v in down_fine_ps:
                f.write(f"{v:.6f}\n")
        self._log(f"[信息] 统计结果已保存: {summary_file}")

        if PLOT_AVAILABLE and valid_n > 5:
            try:
                import numpy as np
                import matplotlib.pyplot as plt

                fig, (ax_up, ax_down) = plt.subplots(2, 1, figsize=(8, 8), sharex=False)
                bins = max(20, min(120, int(math.sqrt(valid_n) * 2)))
                ax_up.hist(np.array(up_fine_ps), bins=bins, alpha=0.75, color='royalblue', edgecolor='black')
                ax_up.axvline(up_mean_ps, color='red', linestyle='--', linewidth=1.5, label=f"Mean={up_mean_ps:.2f} ps")
                ax_up.set_title(f"UP Distribution (phase={phase})")
                ax_up.set_xlabel("UP Fine Time (ps)")
                ax_up.set_ylabel("Count")
                ax_up.grid(True, alpha=0.3)
                ax_up.legend()

                ax_down.hist(np.array(down_fine_ps), bins=bins, alpha=0.75, color='darkorange', edgecolor='black')
                ax_down.axvline(down_mean_ps, color='red', linestyle='--', linewidth=1.5, label=f"Mean={down_mean_ps:.2f} ps")
                ax_down.set_title(f"DOWN Distribution (phase={phase})")
                ax_down.set_xlabel("DOWN Fine Time (ps)")
                ax_down.set_ylabel("Count")
                ax_down.grid(True, alpha=0.3)
                ax_down.legend()
                fig.tight_layout()

                plot_file = os.path.join("tdc_results", f"single_step_stats_phase{phase}_{timestamp}.png")
                fig.savefig(plot_file, dpi=200)
                plt.close(fig)
                self._log(f"[信息] 分布图已保存: {plot_file}")
            except Exception as exc:
                self._log(f"[警告] 绘制分布图失败: {exc}")

    def _task_full_phase_stats(self):
        pair_count = self._validate_positive_int(self.full_stat_count_var.get(), 1, 20000)
        max_retries = 3

        phase_list = []
        up_mean_list = []
        up_std_list = []
        up_var_list = []
        down_mean_list = []
        down_std_list = []
        down_var_list = []
        valid_pairs_list = []

        self._log("=" * 60)
        self._log(f"[任务] 全步进统计 0..224，每步样本对数={pair_count}")
        self._log("[信息] 输出: 四子图(UP均值、DOWN均值、UP标准差、DOWN标准差)，横坐标均为步进值")

        for phase in range(225):
            if phase == 0 or phase % 10 == 0 or phase == 224:
                self._log(f"[信息] 全步进进度 相位 {phase}/224")

            up_vals = []
            down_vals = []

            for _ in range(pair_count):
                up_pkt = None
                down_pkt = None
                success = False

                for _attempt in range(max_retries):
                    ok = self.scanner.start_scan(scan_mode=0, phase=phase, channel=TDCUartScanner.CH_BOTH)
                    if not ok:
                        continue

                    rx_data = self.scanner.receive_data(expected_count=2, timeout=4.0)
                    if not rx_data:
                        continue

                    up_pkt = next((d for d in rx_data if d.get('type') == TDCUartScanner.TYPE_UP), None)
                    down_pkt = next((d for d in rx_data if d.get('type') == TDCUartScanner.TYPE_DOWN), None)
                    if up_pkt is not None and down_pkt is not None:
                        success = True
                        break

                if success:
                    up_vals.append(float(up_pkt['fine']))
                    down_vals.append(float(down_pkt['fine']))

            valid_n = min(len(up_vals), len(down_vals))
            if valid_n == 0:
                self._log(f"[警告] 相位 {phase}: 无有效样本，已跳过")
                continue

            up_mean = sum(up_vals) / len(up_vals)
            up_var = sum((x - up_mean) ** 2 for x in up_vals) / len(up_vals)
            up_std = math.sqrt(up_var)

            down_mean = sum(down_vals) / len(down_vals)
            down_var = sum((x - down_mean) ** 2 for x in down_vals) / len(down_vals)
            down_std = math.sqrt(down_var)

            phase_list.append(phase)
            up_mean_list.append(up_mean)
            up_std_list.append(up_std)
            up_var_list.append(up_var)
            down_mean_list.append(down_mean)
            down_std_list.append(down_std)
            down_var_list.append(down_var)
            valid_pairs_list.append(valid_n)

        if not phase_list:
            self._log("[错误] 全步进统计未得到有效数据")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("tdc_results", exist_ok=True)
        summary_file = os.path.join("tdc_results", f"full_phase_stats_0_224_{timestamp}.csv")
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("phase,valid_pairs,up_mean_ps,up_var_ps2,up_std_ps,down_mean_ps,down_var_ps2,down_std_ps\n")
            for i, phase in enumerate(phase_list):
                f.write(
                    f"{phase},{valid_pairs_list[i]},"
                    f"{up_mean_list[i]:.6f},{up_var_list[i]:.6f},{up_std_list[i]:.6f},"
                    f"{down_mean_list[i]:.6f},{down_var_list[i]:.6f},{down_std_list[i]:.6f}\n"
                )
        self._log(f"[信息] 全步进统计结果已保存: {summary_file}")

        self._log(f"[结果][UP] 均值范围: {min(up_mean_list):.3f} ~ {max(up_mean_list):.3f} ps")
        self._log(f"[结果][UP] 标准差均值: {sum(up_std_list)/len(up_std_list):.3f} ps")
        self._log(f"[结果][DOWN] 均值范围: {min(down_mean_list):.3f} ~ {max(down_mean_list):.3f} ps")
        self._log(f"[结果][DOWN] 标准差均值: {sum(down_std_list)/len(down_std_list):.3f} ps")

        if PLOT_AVAILABLE and len(phase_list) > 3:
            try:
                import numpy as np
                import matplotlib.pyplot as plt

                x = np.array(phase_list, dtype=float)
                up_mean_arr = np.array(up_mean_list, dtype=float)
                up_std_arr = np.array(up_std_list, dtype=float)
                down_mean_arr = np.array(down_mean_list, dtype=float)
                down_std_arr = np.array(down_std_list, dtype=float)

                # Detect very large std outliers so they do not dominate y-axis.
                def _detect_std_outliers(std_arr, phase_arr, channel_name):
                    if len(std_arr) < 6:
                        return np.zeros(len(std_arr), dtype=bool), []

                    median_val = float(np.median(std_arr))
                    mad = float(np.median(np.abs(std_arr - median_val)))

                    if mad < 1e-9:
                        threshold = median_val * 3.0 if median_val > 0 else float('inf')
                    else:
                        threshold = median_val + 6.0 * mad

                    outlier_mask = std_arr > threshold
                    outlier_rows = []
                    outlier_idx = np.where(outlier_mask)[0]
                    for idx in outlier_idx:
                        outlier_rows.append((channel_name, int(phase_arr[idx]), float(std_arr[idx])))
                    return outlier_mask, outlier_rows

                up_std_outlier_mask, up_outlier_rows = _detect_std_outliers(up_std_arr, x, "UP")
                down_std_outlier_mask, down_outlier_rows = _detect_std_outliers(down_std_arr, x, "DOWN")
                all_outlier_rows = sorted(up_outlier_rows + down_outlier_rows, key=lambda t: t[2], reverse=True)
                shown_outlier_rows = all_outlier_rows[:5]

                fig, axes = plt.subplots(2, 2, figsize=(12, 9), sharex=False)

                axes[0, 0].plot(x, up_mean_arr, '.-', color='royalblue', label='UP Mean')
                axes[0, 0].set_xlabel("Phase Step")
                axes[0, 0].set_ylabel("Mean Fine (ps)")
                axes[0, 0].set_title("UP Mean vs Phase Step")
                axes[0, 0].grid(True, alpha=0.3)
                axes[0, 0].legend()

                axes[0, 1].plot(x, down_mean_arr, '.-', color='darkorange', label='DOWN Mean')
                axes[0, 1].set_xlabel("Phase Step")
                axes[0, 1].set_ylabel("Mean Fine (ps)")
                axes[0, 1].set_title("DOWN Mean vs Phase Step")
                axes[0, 1].grid(True, alpha=0.3)
                axes[0, 1].legend()

                up_std_plot_mask = ~up_std_outlier_mask
                axes[1, 0].plot(x[up_std_plot_mask], up_std_arr[up_std_plot_mask], '.-', color='royalblue', label='UP Std')
                axes[1, 0].set_xlabel("Phase Step")
                axes[1, 0].set_ylabel("Std (ps)")
                axes[1, 0].set_title("UP Std vs Phase Step")
                axes[1, 0].grid(True, alpha=0.3)
                axes[1, 0].legend()

                down_std_plot_mask = ~down_std_outlier_mask
                axes[1, 1].plot(x[down_std_plot_mask], down_std_arr[down_std_plot_mask], '.-', color='darkorange', label='DOWN Std')
                axes[1, 1].set_xlabel("Phase Step")
                axes[1, 1].set_ylabel("Std (ps)")
                axes[1, 1].set_title("DOWN Std vs Phase Step")
                axes[1, 1].grid(True, alpha=0.3)
                axes[1, 1].legend()

                if all_outlier_rows:
                    table_lines = ["Filtered large-std points (excluded from std plots):", "Channel  Phase  Std(ps)"]
                    for ch, ph, std_val in shown_outlier_rows:
                        table_lines.append(f"{ch:>7}  {ph:>5}  {std_val:>7.3f}")
                    if len(all_outlier_rows) > len(shown_outlier_rows):
                        table_lines.append(f"... and {len(all_outlier_rows) - len(shown_outlier_rows)} more")

                    fig.subplots_adjust(bottom=0.20)
                    fig.text(
                        0.5,
                        0.04,
                        "\n".join(table_lines),
                        ha='center',
                        va='bottom',
                        fontsize=9,
                        family='monospace',
                        bbox=dict(boxstyle='round,pad=0.4', facecolor='#fffbe6', edgecolor='#999999', alpha=0.95),
                    )

                    self._log(f"[信息] 已从标准差子图中过滤 {len(all_outlier_rows)} 个大离群点，并在图中表格列出")

                fig.tight_layout()
                plot_file = os.path.join("tdc_results", f"full_phase_stats_0_224_{timestamp}.png")
                fig.savefig(plot_file, dpi=220)
                plt.close(fig)
                self._log(f"[信息] 全步进统计四分图已保存: {plot_file}")
            except Exception as exc:
                self._log(f"[警告] 绘制全步进统计图失败: {exc}")

    def _task_scan(self, scan_mode, phase, channel):
        mode_name = "全扫描" if scan_mode == 1 else "单步"
        ch_name = {0b00: "无", 0b01: "DOWN", 0b10: "UP", 0b11: "BOTH"}[channel]

        if scan_mode == 0:
            expected = 2 if channel == 0b11 else 1
        else:
            expected = (phase + 1) * (2 if channel == 0b11 else 1)

        self._log("=" * 60)
        self._log(f"[任务] 扫描 模式={mode_name} 相位={phase} 通道={ch_name}")
        self._log(f"[信息] 预计数据包数量: {expected}")

        ok = self.scanner.start_scan(scan_mode=scan_mode, phase=phase, channel=channel)
        if not ok:
            self._log("[错误] 启动扫描失败")
            return

        timeout = max(10.0, expected * 0.02)
        data = self.scanner.receive_data(expected_count=expected, timeout=timeout)
        if not data:
            self._log("[错误] 未接收到数据")
            return

        self._process_and_save(data, mode_name.lower(), ch_name.lower())

    def _task_continuous_scan(self):
        start_phase = self._validate_phase(self.cont_start_var.get(), 0, 255)
        end_phase = self._validate_phase(self.cont_end_var.get(), start_phase, 255)

        ch = "BOTH"
        channel = 0b11

        samples = end_phase - start_phase + 1
        expected_total = samples * (2 if channel == 0b11 else 1)

        self._log("=" * 60)
        self._log(f"[任务] 连续单步扫描 起始={start_phase} 结束={end_phase} 通道={ch}")
        self._log(f"[信息] 预计数据包数量: {expected_total}")

        all_data = []
        for phase in range(start_phase, end_phase + 1):
            if phase % 10 == 0 or phase == start_phase or phase == end_phase:
                self._log(f"[信息] 扫描进度 相位 {phase}/{end_phase}")

            ok = self.scanner.start_scan(scan_mode=0, phase=phase, channel=channel)
            if not ok:
                self._log(f"[警告] 相位 {phase} 命令发送失败")
                continue

            expected_count = 2 if channel == 0b11 else 1
            data = self.scanner.receive_data(expected_count=expected_count, timeout=5.0)
            all_data.extend(data)

        if not all_data:
            self._log("[错误] 连续模式下未接收到数据")
            return

        self._process_and_save(all_data, "continuous", ch.lower())

    def _process_and_save(self, data, mode_suffix, ch_suffix):
        processor = TDCDataProcessor(data)
        processor.process()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_filename = f"tdc_uart_{mode_suffix}_{ch_suffix}_{timestamp}.txt"
        data_path = processor.save_to_file(data_filename)
        self._log(f"[信息] 数据已保存: {data_path}")

        if PLOT_AVAILABLE and len(data) > 10:
            plot_filename = data_filename.replace(".txt", ".png")
            plot_file = os.path.join("tdc_results", plot_filename)
            processor.plot(save_file=plot_file)
            self._log(f"[信息] 图像已保存: {plot_file}")

    def _log(self, msg):
        self.log_queue.put(msg)

    def _poll_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
        self.root.after(80, self._poll_log_queue)

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _quit(self):
        if self.scanner.connected:
            self.scanner.disconnect()
        self.root.destroy()


def main():
    if not SERIAL_AVAILABLE:
        print("[错误] 未检测到 pyserial，请安装: pip install pyserial")
        return 1

    root = tk.Tk()
    app = TDCGuiApp(root)
    root.protocol("WM_DELETE_WINDOW", app._quit)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
