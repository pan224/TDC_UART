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

        ttk.Label(frame, text="连续扫描起始").grid(row=6, column=0, sticky="w", padx=4, pady=2)
        self.cont_start_var = tk.StringVar(value="0")
        ttk.Entry(frame, textvariable=self.cont_start_var, width=10).grid(row=6, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(frame, text="连续扫描结束").grid(row=7, column=0, sticky="w", padx=4, pady=2)
        self.cont_end_var = tk.StringVar(value="224")
        ttk.Entry(frame, textvariable=self.cont_end_var, width=10).grid(row=7, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(frame, text="通道（固定）").grid(row=8, column=0, sticky="w", padx=4, pady=2)
        ttk.Label(frame, text="BOTH").grid(row=8, column=1, sticky="w", padx=4, pady=2)

        ttk.Button(
            frame,
            text="执行连续单步扫描",
            command=lambda: self._run_task(self._task_continuous_scan),
        ).grid(row=9, column=0, columnspan=3, sticky="ew", padx=4, pady=6)

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
