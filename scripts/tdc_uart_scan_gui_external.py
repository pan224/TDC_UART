import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import struct
import queue
import time
import csv
import os  # 新增: 用于文件路径操作
from datetime import datetime

# 引入数据分析库
try:
    import numpy as np
    import matplotlib
    from matplotlib import cm # 引入颜色映射
    matplotlib.use("TkAgg") # 指定后端
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk # 引入工具栏
    from matplotlib.figure import Figure
    from mpl_toolkits.mplot3d import Axes3D # 引入3D绘图工具
    HAS_ANALYSIS_LIBS = True
except ImportError:
    HAS_ANALYSIS_LIBS = False
    print("Warning: numpy or matplotlib not found. Analysis features disabled.")

class TDC_GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TDC 像素芯片控制 & 数据采集")
        self.root.geometry("1400x950") 
        
        # 串口变量
        self.ser = None
        self.is_connected = False
        self.rx_thread = None
        self.stop_thread = False
        self.data_queue = queue.Queue()
        
        # 数据处理变量
        self.pending_ups = {}    # 等待配对的 UP 包 {id: pkt}
        self.csv_data_buffer = []
        
        # 档位记录变量 (Metadata)
        self.current_active_sel_str = "000" # 当前生效的 Sel 值 (默认为 000)
        
        # 统计变量
        self.total_packets = 0
        self.up_count = 0
        self.down_count = 0

        # === 自动化测试相关变量 ===
        self.test_mode = "IDLE"          # 状态: IDLE, FIXED, SCAN
        self.last_test_mode = "IDLE"     # 记录最后一次测试的模式，用于快捷保存
        self.test_current_round = 0
        self.test_round_pairs = 0
        self.test_delta_values = []      # 用于单次Auto Test
        self.test_latched_cmd = None
        self.test_latched_sel_str = "000" # 自动化测试时的锁定 Sel 值
        
        # 6-Step 扫描专用变量
        self.scan_step = 0               # 当前扫描步骤 (0-5)
        self.scan_results = [[] for _ in range(6)] # 存储6组数据
        
        # UI绑定变量
        self.var_target_rounds = tk.IntVar(value=6)    
        self.var_pulses_per_round = tk.IntVar(value=100)
        self.test_target_rounds = 100
        self.test_target_pairs_per_round = 100

        # 常量定义 (使用 ps 为单位)
        self.CLK_FREQ = 260e6
        self.CLK_PERIOD_PS = 1e12 / self.CLK_FREQ 
        self.FINE_BITS = 13
        self.FINE_LSB_PS = self.CLK_PERIOD_PS / (2**self.FINE_BITS)

        # 构建界面
        self.create_widgets()
        
        # 启动定时器更新UI
        self.root.after(50, self.update_ui_from_queue)

    def create_widgets(self):
        # === 顶部：串口设置 ===
        top_frame = ttk.LabelFrame(self.root, text="通信设置", padding=5)
        top_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(top_frame, text="端口:").pack(side="left", padx=5)
        self.port_combo = ttk.Combobox(top_frame, width=15)
        self.port_combo.pack(side="left", padx=5)
        self.refresh_ports()
        ttk.Button(top_frame, text="刷新", command=self.refresh_ports).pack(side="left", padx=2)

        ttk.Label(top_frame, text="波特率:").pack(side="left", padx=5)
        self.baud_combo = ttk.Combobox(top_frame, values=["115200", "2000000", "3000000"], width=10)
        self.baud_combo.current(0) 
        self.baud_combo.pack(side="left", padx=5)

        self.btn_connect = ttk.Button(top_frame, text="打开串口", command=self.toggle_connection)
        self.btn_connect.pack(side="left", padx=10)
        
        self.status_lbl = ttk.Label(top_frame, text="● 未连接", foreground="red")
        self.status_lbl.pack(side="left", padx=10)

        # === 主体区域：左右分栏 ===
        paned_window = ttk.PanedWindow(self.root, orient="horizontal")
        paned_window.pack(fill="both", expand=True, padx=5, pady=5)

        # --- 左侧：控制面板 (带滚动条) ---
        left_container = ttk.Frame(paned_window, width=340)
        paned_window.add(left_container, weight=1)
        
        left_canvas = tk.Canvas(left_container)
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=left_canvas.yview)
        left_frame = ttk.Frame(left_canvas)
        
        left_frame.bind(
            "<Configure>",
            lambda e: left_canvas.configure(
                scrollregion=left_canvas.bbox("all")
            )
        )
        
        canvas_window = left_canvas.create_window((0, 0), window=left_frame, anchor="nw")
        
        def configure_canvas(event):
            left_canvas.itemconfig(canvas_window, width=event.width)
        left_canvas.bind("<Configure>", configure_canvas)

        left_canvas.configure(yscrollcommand=scrollbar.set)
        left_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            left_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            
        left_container.bind('<Enter>', lambda e: left_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        left_container.bind('<Leave>', lambda e: left_canvas.unbind_all("<MouseWheel>"))

        # --- 控件 ---
        
        # 1. 系统控制
        calib_frame = ttk.LabelFrame(left_frame, text="系统命令", padding=10)
        calib_frame.pack(fill="x", pady=5)
        ttk.Button(calib_frame, text="触发重新校准 (Recalibrate)", command=self.send_recalibrate, style="Accent.TButton").pack(fill="x")

        # 2. 像素芯片激励设置
        pixel_frame = ttk.LabelFrame(left_frame, text="像素芯片激励 (Pixel Excitation)", padding=10)
        pixel_frame.pack(fill="x", pady=10)

        self.var_rst = tk.BooleanVar(value=False)
        self.vars_csa = [tk.BooleanVar(value=False) for _ in range(6)]

        ttk.Checkbutton(pixel_frame, text="RST (复位)", variable=self.var_rst, command=self.update_cmd_preview).pack(anchor="w", pady=5)
        ttk.Separator(pixel_frame, orient="horizontal").pack(fill="x", pady=5)
        ttk.Label(pixel_frame, text="CSA 激励位 (CSA5-0):").pack(anchor="w")

        csa_grid = ttk.Frame(pixel_frame)
        csa_grid.pack(fill="x", pady=5)
        for i in range(6):
            btn = ttk.Checkbutton(csa_grid, text=f"CSA {i}", variable=self.vars_csa[i], command=self.update_cmd_preview)
            btn.grid(row=i//2, column=i%2, sticky="w", padx=10, pady=2)

        # === SEL 档位选择 (Metadata) ===
        sel_frame = ttk.LabelFrame(left_frame, text="挡位记录 (Sel Record)", padding=10)
        sel_frame.pack(fill="x", pady=10)
        
        self.var_sel2 = tk.StringVar(value="0")
        self.var_sel1 = tk.StringVar(value="0")
        self.var_sel0 = tk.StringVar(value="0")
        
        f_sel = ttk.Frame(sel_frame)
        f_sel.pack(fill="x")
        
        ttk.Label(f_sel, text="Sel 2").grid(row=0, column=0, padx=5)
        ttk.Label(f_sel, text="Sel 1").grid(row=0, column=1, padx=5)
        ttk.Label(f_sel, text="Sel 0").grid(row=0, column=2, padx=5)
        
        width_cb = 3
        cb2 = ttk.Combobox(f_sel, textvariable=self.var_sel2, values=["0", "1"], width=width_cb, state="readonly")
        cb2.grid(row=1, column=0, padx=5)
        cb1 = ttk.Combobox(f_sel, textvariable=self.var_sel1, values=["0", "1"], width=width_cb, state="readonly")
        cb1.grid(row=1, column=1, padx=5)
        cb0 = ttk.Combobox(f_sel, textvariable=self.var_sel0, values=["0", "1"], width=width_cb, state="readonly")
        cb0.grid(row=1, column=2, padx=5)
        
        ttk.Label(sel_frame, text="(仅用于记录，不发送给FPGA)", font=("Arial", 8), foreground="gray").pack(pady=(5,0))

        # 3. 实时指令预览
        preview_frame = ttk.LabelFrame(left_frame, text="单次发送指令预览", padding=10)
        preview_frame.pack(fill="x", pady=10)
        self.lbl_cmd_hex = ttk.Label(preview_frame, text="0x00300000", font=("Consolas", 14, "bold"), foreground="blue")
        self.lbl_cmd_hex.pack(anchor="center", pady=5)
        self.btn_send_pixel = ttk.Button(left_frame, text="发送单次配置 (Send Once)", command=self.send_pixel_cmd)
        self.btn_send_pixel.pack(fill="x", pady=5, ipady=5)

        # 4. 自动化测试面板
        auto_frame = ttk.LabelFrame(left_frame, text="自动化数据采集 (Auto Test)", padding=10)
        auto_frame.pack(fill="x", pady=20)
        
        auto_frame.columnconfigure(1, weight=1)
        
        ttk.Label(auto_frame, text="指令发送次数 (Rounds):").grid(row=0, column=0, sticky="w", pady=2)
        rounds_spin = ttk.Spinbox(auto_frame, from_=1, to=10000, textvariable=self.var_target_rounds, width=8)
        rounds_spin.grid(row=0, column=1, sticky="e", pady=2)
        
        ttk.Label(auto_frame, text="单次脉冲数 (Pulses/Cmd):").grid(row=1, column=0, sticky="w", pady=2)
        pulses_spin = ttk.Spinbox(auto_frame, from_=1, to=10000, textvariable=self.var_pulses_per_round, width=8)
        pulses_spin.grid(row=1, column=1, sticky="e", pady=2)
        
        # 实时总数显示
        self.lbl_total_expected = ttk.Label(auto_frame, text="预计总数据量: 600", foreground="blue", font=("Arial", 9, "bold"))
        self.lbl_total_expected.grid(row=2, column=0, columnspan=2, pady=5)
        
        self.var_target_rounds.trace_add("write", self.update_expected_total)
        self.var_pulses_per_round.trace_add("write", self.update_expected_total)

        # 按钮
        self.btn_auto_test = ttk.Button(auto_frame, text="开始采集与分析 (Fixed)", command=self.start_auto_test_fixed)
        self.btn_auto_test.grid(row=3, column=0, columnspan=2, sticky="ew", pady=5)

        self.btn_scan_test = ttk.Button(auto_frame, text="开始 6-Step CSA 扫描 (3D)", command=self.start_scan_test)
        self.btn_scan_test.grid(row=4, column=0, columnspan=2, sticky="ew", pady=5)
        
        self.btn_stop_test = ttk.Button(auto_frame, text="停止当前测试 (Stop)", command=self.stop_auto_test, state="disabled")
        self.btn_stop_test.grid(row=5, column=0, columnspan=2, sticky="ew", pady=5)
        
        self.lbl_auto_status = ttk.Label(auto_frame, text="状态: 空闲", foreground="gray", wraplength=280)
        self.lbl_auto_status.grid(row=6, column=0, columnspan=2, pady=5)

        if not HAS_ANALYSIS_LIBS:
            self.btn_auto_test.config(state="disabled", text="缺少 numpy/matplotlib")
            self.btn_scan_test.config(state="disabled")

        # --- 右侧：数据显示 ---
        right_frame = ttk.Frame(paned_window)
        paned_window.add(right_frame, weight=4)

        # 统计栏
        stats_frame = ttk.Frame(right_frame)
        stats_frame.pack(fill="x", pady=5)
        self.lbl_stats = ttk.Label(stats_frame, text="Total: 0 | UP: 0 | DOWN: 0", font=("Consolas", 10, "bold"))
        self.lbl_stats.pack(side="left")
        
        # 按钮布局
        ttk.Button(stats_frame, text="清空显示", command=self.clear_data).pack(side="right", padx=5)
        ttk.Button(stats_frame, text="保存CSV", command=self.save_data).pack(side="right", padx=5)
        ttk.Button(stats_frame, text="快捷保存 (表格+图像)", command=self.quick_save).pack(side="right", padx=5)

        # 表格 (新增 CSA 列以方便检查)
        cols = ("Time", "Type", "ID", "Sel", "CSA", "Coarse", "Fine", "Delta T (ps)", "Raw Hex")
        self.tree = ttk.Treeview(right_frame, columns=cols, show="headings", height=20)
        
        self.tree.column("Time", width=80)
        self.tree.column("Type", width=40)
        self.tree.column("ID", width=40)
        self.tree.column("Sel", width=40, anchor="center") 
        self.tree.column("CSA", width=60, anchor="center") # New CSA Column
        self.tree.column("Coarse", width=60)
        self.tree.column("Fine", width=60)
        self.tree.column("Delta T (ps)", width=90, anchor="e")
        self.tree.column("Raw Hex", width=80)

        for col in cols:
            self.tree.heading(col, text=col)

        scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.update_cmd_preview()

    def update_expected_total(self, *args):
        try:
            r = self.var_target_rounds.get()
            p = self.var_pulses_per_round.get()
            total = r * p
            self.lbl_total_expected.config(text=f"Fixed总量: {total} | Scan总量: {total*6}")
        except:
            self.lbl_total_expected.config(text="预计总数据量: -")

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        self.port_combo['values'] = [p.device for p in ports]
        if ports:
            self.port_combo.current(0)

    def toggle_connection(self):
        if not self.is_connected:
            try:
                port = self.port_combo.get()
                baud = int(self.baud_combo.get())
                self.ser = serial.Serial(port, baud, timeout=1)
                self.is_connected = True
                self.stop_thread = False
                self.rx_thread = threading.Thread(target=self.read_serial_thread, daemon=True)
                self.rx_thread.start()
                self.btn_connect.config(text="关闭串口")
                self.status_lbl.config(text=f"● 已连接 {port}", foreground="green")
            except Exception as e:
                messagebox.showerror("错误", str(e))
        else:
            self.stop_thread = True
            if self.ser: self.ser.close()
            self.is_connected = False
            self.btn_connect.config(text="打开串口")
            self.status_lbl.config(text="● 未连接", foreground="red")

    def read_serial_thread(self):
        buffer = b""
        while not self.stop_thread and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting:
                    buffer += self.ser.read(self.ser.in_waiting)
                    while len(buffer) >= 4:
                        packet = buffer[:4]
                        buffer = buffer[4:]
                        raw_int = struct.unpack('<I', packet)[0]
                        self.data_queue.put(raw_int)
                else:
                    time.sleep(0.005)
            except:
                break

    def parse_packet(self, raw_int):
        data_type = (raw_int >> 30) & 0x03
        measure_id = (raw_int >> 24) & 0x3F      
        fine_time = (raw_int >> 11) & 0x1FFF    
        flag_ch = (raw_int >> 10) & 0x01        
        coarse_time = raw_int & 0x3FF           
        
        type_str = ["UP", "DOWN", "INFO", "CMD"][data_type]
        ch_str = "UP" if flag_ch == 1 else "DOWN"
        
        return {
            "time_str": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "type_code": data_type,
            "type": type_str,
            "ch": ch_str,
            "id": measure_id,
            "coarse": coarse_time,
            "fine": fine_time,
            "raw_hex": f"0x{raw_int:08X}"
        }

    # === 通用测试初始化检查 ===
    def _init_test_params(self):
        if not self.is_connected:
            messagebox.showwarning("警告", "请先连接串口")
            return False
        try:
            self.test_target_rounds = self.var_target_rounds.get()
            self.test_target_pairs_per_round = self.var_pulses_per_round.get()
            if self.test_target_rounds <= 0 or self.test_target_pairs_per_round <= 0:
                raise ValueError
        except:
            messagebox.showerror("错误", "请输入有效的正整数")
            return False
        
        self.btn_auto_test.config(state="disabled")
        self.btn_scan_test.config(state="disabled")
        self.btn_stop_test.config(state="normal") 
        self.lbl_auto_status.config(text="测试运行中...列表刷新已暂停", foreground="blue")
        
        s2 = self.var_sel2.get()
        s1 = self.var_sel1.get()
        s0 = self.var_sel0.get()
        self.test_latched_sel_str = f"{s2}{s1}{s0}"
        
        # 每次新测试开始时清空数据缓存，避免混淆不同测试的数据
        self.csv_data_buffer = []
        self.tree.delete(*self.tree.get_children())
        self.total_packets = 0
        self.up_count = 0
        self.down_count = 0
        
        return True

    def stop_auto_test(self):
        if self.test_mode == "IDLE": return
        self.test_mode = "IDLE"
        self.lbl_auto_status.config(text="测试已手动停止", foreground="red")
        self.btn_auto_test.config(state="normal")
        self.btn_scan_test.config(state="normal")
        self.btn_stop_test.config(state="disabled")

    # === 1. 固定参数测试逻辑 (Fixed) ===
    def start_auto_test_fixed(self):
        if not self._init_test_params(): return

        self.test_mode = "FIXED"
        self.last_test_mode = "FIXED"
        self.test_current_round = 0 
        self.test_round_pairs = 0
        self.test_delta_values = [] 
        
        self.test_latched_cmd = self.get_current_cmd_int()
        self.send_pixel_cmd(silent=True, cmd_val=self.test_latched_cmd)

    # === 2. 扫描测试逻辑 (Scan 6-Steps) ===
    def start_scan_test(self):
        if not self._init_test_params(): return

        self.test_mode = "SCAN"
        self.last_test_mode = "SCAN"
        self.test_current_round = 0 
        self.test_round_pairs = 0
        self.scan_step = 0 
        self.scan_results = [[] for _ in range(6)] 
        
        self.run_scan_step()

    def run_scan_step(self):
        if self.test_mode != "SCAN": return

        csa_val = 1 << self.scan_step
        rst_bit = 1 if self.var_rst.get() else 0
        scan_ch = 0x3 
        
        cmd = (0 << 31) | (0 << 30) | (scan_ch << 28) | (0 << 20) | \
              (rst_bit << 19) | (csa_val << 13)
        
        self.test_latched_cmd = cmd
        status_msg = f"正在执行步骤 {self.scan_step}/5 (CSA_{self.scan_step})..."
        self.lbl_auto_status.config(text=status_msg)
        self.send_pixel_cmd(silent=True, cmd_val=self.test_latched_cmd)

    # === 测试完成逻辑 ===
    def finish_test(self):
        mode = self.test_mode
        self.test_mode = "IDLE"
        self.btn_auto_test.config(state="normal")
        self.btn_scan_test.config(state="normal")
        self.btn_stop_test.config(state="disabled") 
        self.lbl_auto_status.config(text="测试完成", foreground="green")
        
        if mode == "FIXED":
            self.show_analysis_window_fixed()
        elif mode == "SCAN":
            self.show_analysis_window_scan()

    # === 快捷保存功能 (核心修改) ===
    def quick_save(self):
        if not self.csv_data_buffer:
            messagebox.showinfo("提示", "没有数据可保存")
            return

        # 1. 确定保存参数
        sel_str = self.test_latched_sel_str 
        if not sel_str or self.last_test_mode == "IDLE":
             sel_str = f"{self.var_sel2.get()}{self.var_sel1.get()}{self.var_sel0.get()}"

        mode = self.last_test_mode if self.last_test_mode != "IDLE" else "MANUAL"
        rounds = self.var_target_rounds.get()
        pulses = self.var_pulses_per_round.get()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 2. 创建目录 ./data/SELxxx/{Mode}_{R}x{P}_{Time}/
        base_dir = os.path.join(os.getcwd(), "data", f"SEL{sel_str}")
        folder_name = f"{mode}_{rounds}R_{pulses}P_{timestamp}"
        save_dir = os.path.join(base_dir, folder_name)
        
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"创建文件夹失败: {e}")
            return

        # 3. 数据分拣与保存
        # 根据 pkt["csa_label"] 对数据进行分组
        grouped_data = {}
        for row in self.csv_data_buffer:
            label = row.get("csa_label", "Unknown")
            if label not in grouped_data:
                grouped_data[label] = []
            grouped_data[label].append(row)
            
        try:
            # 分别保存每个 CSA 的数据到不同的文件 (如 CSA0.csv, CSA1.csv)
            for label, rows in grouped_data.items():
                filename = f"{label}.csv" # 例如 "CSA0.csv"
                csv_path = os.path.join(save_dir, filename)
                
                with open(csv_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Time", "Ch", "ID", "Sel", "Coarse", "Fine", "CoarseDiff", "FineDiff", "Delta_ps", "RawHex", "CSA_Label"])
                    for i in rows:
                        writer.writerow([
                            i["time_str"], i["ch"], i["id"], i.get("sel", "000"), i["coarse"], i["fine"], 
                            i.get("c_diff", ""), i.get("f_diff", ""), i.get("delta",""), i["raw_hex"], i.get("csa_label", "")
                        ])
                        
            # 可选：如果需要一个汇总的 data.csv，可以解开下面注释
            # csv_path_all = os.path.join(save_dir, "data_all.csv")
            # ... write all rows ...
                        
        except Exception as e:
            messagebox.showerror("错误", f"保存CSV失败: {e}")
            return

        # 4. 保存统计图像
        img_path = os.path.join(save_dir, "analysis_plot.png")
        txt_path = os.path.join(save_dir, "summary.txt")
        self.save_plot_and_stats(img_path, txt_path, mode)
        
        messagebox.showinfo("成功", f"数据已按像素(CSA)分开保存至:\n{save_dir}")

    def save_plot_and_stats(self, img_path, txt_path, mode):
        if not HAS_ANALYSIS_LIBS: return
        
        fig = Figure(figsize=(10, 8), dpi=100)
        stats_content = f"Test Mode: {mode}\nTimestamp: {datetime.now()}\n\n"
        
        if mode == "FIXED" and self.test_delta_values:
            ax = fig.add_subplot(111)
            data = np.array(self.test_delta_values)
            mean_val = np.mean(data)
            var_val = np.var(data)
            std_val = np.std(data)
            min_val = np.min(data)
            max_val = np.max(data)
            
            stats_content += f"Samples:  {len(data)}\nMean: {mean_val:.4f} ps\nVariance: {var_val:.4f}\nStd Dev: {std_val:.4f} ps\nRange: {min_val:.2f} ~ {max_val:.2f} ps\n"
            
            n, bins, patches = ax.hist(data, bins=100, color='#3498db', alpha=0.7, edgecolor='gray')
            if std_val > 0:
                x_fit = np.linspace(min_val, max_val, 200)
                y_pdf = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_fit - mean_val) / std_val)**2)
                bin_width = bins[1] - bins[0]
                y_fit = y_pdf * len(data) * bin_width
                ax.plot(x_fit, y_fit, color='#e74c3c', linestyle='--', linewidth=2)
            
            ax.axvline(mean_val, color='green', linestyle='-', linewidth=1.5, label=f'Mean: {mean_val:.2f} ps')
            ax.set_title(f"Delta T Distribution (Fixed)")
            ax.set_xlabel("Delta T (ps)")
            ax.set_ylabel("Count")
            ax.legend()
            
        elif mode == "SCAN":
            ax = fig.add_subplot(111, projection='3d')
            colors = ['r', 'g', 'b', 'y', 'c', 'm']
            
            all_data = []
            for d in self.scan_results: all_data.extend(d)
            
            if all_data:
                global_min = np.min(all_data)
                global_max = np.max(all_data)
                bin_width = 20
                bins = np.arange(global_min, global_max + bin_width * 2, bin_width)
                
                stats_content += "Step | CSA  | Samples | Mean (ps) | Variance | Std Dev (ps)\n" + "-" * 65 + "\n"
                
                for i in range(6):
                    data = np.array(self.scan_results[i])
                    if len(data) == 0: continue
                    mean_val = np.mean(data)
                    var_val = np.var(data)
                    std_val = np.std(data)
                    stats_content += f" {i}   | CSA_{i} | {len(data):<7} | {mean_val:>9.2f} | {var_val:>8.2f} | {std_val:>10.2f}\n"
                    
                    hist, _ = np.histogram(data, bins=bins)
                    xs = (bins[:-1] + bins[1:]) / 2
                    ys = np.full(len(hist), i)
                    zs = np.zeros(len(hist))
                    dx = bin_width * 0.8
                    dy = 0.3
                    dz = hist
                    mask = dz > 0
                    ax.bar3d(xs[mask], ys[mask], zs[mask], dx, dy, dz[mask], color=colors[i], alpha=0.5, zsort='average')
                    
                    if std_val > 0:
                        x_fit = np.linspace(global_min, global_max, 200)
                        y_fit = np.full_like(x_fit, i + dy/2)
                        y_pdf = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_fit - mean_val) / std_val)**2)
                        z_fit = y_pdf * len(data) * bin_width
                        ax.plot(x_fit, y_fit, z_fit, color='black', linewidth=1.5, alpha=0.9)
                
                ax.set_xlabel('Delta T (ps)')
                ax.set_ylabel('CSA Index')
                ax.set_zlabel('Count')
                ax.set_yticks(range(6))
                ax.view_init(elev=30, azim=-50)
        
        fig.savefig(img_path)
        with open(txt_path, "w") as f:
            f.write(stats_content)

    def show_analysis_window_fixed(self):
        if not HAS_ANALYSIS_LIBS or not self.test_delta_values:
            messagebox.showinfo("信息", "没有数据")
            return
        
        win = tk.Toplevel(self.root)
        win.title("Fixed Data Analysis")
        win.geometry("800x650")
        
        data = np.array(self.test_delta_values)
        mean_val = np.mean(data)
        var_val = np.var(data)  
        std_val = np.std(data)
        min_val = np.min(data)
        max_val = np.max(data)
        
        info_frame = ttk.LabelFrame(win, text="统计结果 (Statistics)", padding=10)
        info_frame.pack(fill="x", padx=10, pady=5)

        info_str = (
            f"档位 (Sel Setting):     {self.test_latched_sel_str}\n"
            f"样本总数 (Total Samples): {len(data)}\n"
            f"平均值 (Mean):          {mean_val:.2f} ps\n"
            f"方差 (Variance):        {var_val:.2f}\n"
            f"标准差 (Std Dev):       {std_val:.2f} ps\n"
            f"范围 (Range):           {min_val:.2f} ps ~ {max_val:.2f} ps"
        )
        ttk.Label(info_frame, text=info_str, font=("Consolas", 11)).pack(anchor="w")
        
        fig = Figure(figsize=(7, 5), dpi=100)
        ax = fig.add_subplot(111)
        
        n, bins, patches = ax.hist(data, bins=100, color='#3498db', alpha=0.7, edgecolor='gray', label='Histogram')
        
        if std_val > 0:
            x_fit = np.linspace(min_val, max_val, 200)
            y_pdf = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_fit - mean_val) / std_val)**2)
            bin_width = bins[1] - bins[0]
            y_fit = y_pdf * len(data) * bin_width
            ax.plot(x_fit, y_fit, color='#e74c3c', linestyle='--', linewidth=2, label='Gaussian Fit')

        ax.axvline(mean_val, color='green', linestyle='-', linewidth=1.5, label=f'Mean: {mean_val:.2f} ps')
        ax.set_title(f"Delta T Distribution (Sel={self.test_latched_sel_str})")
        ax.set_xlabel("Delta T (ps)")
        ax.set_ylabel("Count")
        ax.legend()
        ax.grid(True, linestyle=':', alpha=0.6)
        
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        
        toolbar = NavigationToolbar2Tk(canvas, win)
        toolbar.update()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def show_analysis_window_scan(self):
        if not HAS_ANALYSIS_LIBS: return
        
        win = tk.Toplevel(self.root)
        win.title("6-Step CSA Scan Analysis (3D Discrete + Stats)")
        win.geometry("1200x900")
        
        stats_frame = ttk.LabelFrame(win, text="Statistics Table (Mean & Variance)", padding=10)
        stats_frame.pack(fill="x", padx=10, pady=5)
        
        cols = ("Step", "CSA", "Samples", "Mean (ps)", "Variance", "Std Dev (ps)", "Min (ps)", "Max (ps)")
        stats_tree = ttk.Treeview(stats_frame, columns=cols, show="headings", height=8)
        
        for col in cols:
            stats_tree.heading(col, text=col)
            stats_tree.column(col, width=100, anchor="center")
            
        stats_tree.pack(fill="both", expand=True)

        fig = Figure(figsize=(10, 8), dpi=100)
        ax = fig.add_subplot(111, projection='3d')
        
        colors = ['r', 'g', 'b', 'y', 'c', 'm']
        
        all_data = []
        for d in self.scan_results:
            all_data.extend(d)
            
        if not all_data:
            messagebox.showinfo("信息", "没有有效数据")
            return

        global_min = np.min(all_data)
        global_max = np.max(all_data)
        span = global_max - global_min
        if span == 0: span = 1
        
        bin_width = 20
        bins = np.arange(global_min, global_max + bin_width * 2, bin_width)
        
        for i in range(6):
            data = np.array(self.scan_results[i])
            if len(data) == 0:
                stats_tree.insert("", "end", values=(i, f"CSA_{i}", 0, "N/A", "N/A", "N/A", "N/A", "N/A"))
                continue
            
            mean_val = np.mean(data)
            var_val = np.var(data)
            std_val = np.std(data)
            min_val = np.min(data)
            max_val = np.max(data)
            
            stats_tree.insert("", "end", values=(
                i, f"CSA_{i}", len(data), 
                f"{mean_val:.2f}", f"{var_val:.2f}", f"{std_val:.2f}", 
                f"{min_val:.2f}", f"{max_val:.2f}"
            ))

            hist, _ = np.histogram(data, bins=bins)
            xs = (bins[:-1] + bins[1:]) / 2
            ys = np.full(len(hist), i)
            zs = np.zeros(len(hist))
            dx = bin_width * 0.8
            dy = 0.3
            dz = hist
            mask = dz > 0
            ax.bar3d(xs[mask], ys[mask], zs[mask], dx, dy, dz[mask], color=colors[i], alpha=0.5, zsort='average')

            if std_val > 0:
                x_fit = np.linspace(global_min, global_max, 200)
                y_fit = np.full_like(x_fit, i + dy/2) 
                y_pdf = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_fit - mean_val) / std_val)**2)
                z_fit = y_pdf * len(data) * bin_width
                ax.plot(x_fit, y_fit, z_fit, color='black', linewidth=1.5, alpha=0.9)

        ax.set_xlabel('Delta T (ps)')
        ax.set_ylabel('CSA Index')
        ax.set_zlabel('Count')
        ax.set_title(f'6-Step CSA Scan Distribution (Sel={self.test_latched_sel_str})')
        ax.set_yticks(range(6))
        ax.view_init(elev=30, azim=-50)
        
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        toolbar = NavigationToolbar2Tk(canvas, win)
        toolbar.update()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def update_ui_from_queue(self):
        processed = 0
        limit = 500 if self.test_mode != "IDLE" else 100
        
        while not self.data_queue.empty() and processed < limit:
            raw_int = self.data_queue.get()
            pkt = self.parse_packet(raw_int)
            
            self.total_packets += 1
            if pkt["ch"] == "UP":
                self.up_count += 1
            else:
                self.down_count += 1
            
            dt_ps_val = None
            
            # 记录当前数据的 CSA 来源标签，用于后续分拣保存
            if self.test_mode == "SCAN":
                pkt["csa_label"] = f"CSA{self.scan_step}"
            else:
                # 在 Fixed 模式下，尝试根据 UI 勾选情况判断 CSA
                active_csas = [i for i, var in enumerate(self.vars_csa) if var.get()]
                if len(active_csas) == 1:
                    pkt["csa_label"] = f"CSA{active_csas[0]}"
                elif len(active_csas) > 1:
                    pkt["csa_label"] = "CSA_Multi"
                else:
                    pkt["csa_label"] = "CSA_None"

            # 标记 SEL
            if self.test_mode != "IDLE":
                pkt["sel"] = self.test_latched_sel_str
            else:
                pkt["sel"] = self.current_active_sel_str 
            
            if pkt["type"] == "UP":
                self.pending_ups[pkt["id"]] = pkt
                
            elif pkt["type"] == "DOWN":
                if pkt["id"] in self.pending_ups:
                    up_pkt = self.pending_ups.pop(pkt["id"])
                    
                    c_diff_raw = (pkt["coarse"] - up_pkt["coarse"] + 1024) % 1024
                    if c_diff_raw > 512:
                        c_diff = c_diff_raw - 1024
                    else:
                        c_diff = c_diff_raw
                    
                    f_diff = pkt["fine"] - up_pkt["fine"]
                    
                    pkt["c_diff"] = str(c_diff)
                    pkt["f_diff"] = str(f_diff)
                    pkt["sel"] = up_pkt.get("sel", "000") 
                    # 确保 UP 包的 csa_label 传递给 DOWN 包（如果需要），或者直接使用 pkt 的
                    if "csa_label" not in pkt:
                        pkt["csa_label"] = up_pkt.get("csa_label", "Unknown")

                    t_coarse = c_diff * self.CLK_PERIOD_PS
                    t_fine = f_diff  
                    dt_ps_val = t_coarse - t_fine
                    pkt["delta"] = f"{dt_ps_val:.2f}"

            if self.test_mode != "IDLE":
                if dt_ps_val is not None:
                    if self.test_mode == "FIXED":
                        self.test_delta_values.append(dt_ps_val)
                    elif self.test_mode == "SCAN":
                        self.scan_results[self.scan_step].append(dt_ps_val)
                    
                    self.test_round_pairs += 1
                    
                    if self.test_round_pairs >= self.test_target_pairs_per_round:
                        self.test_current_round += 1
                        self.test_round_pairs = 0
                        
                        if self.test_mode == "FIXED":
                            self.lbl_auto_status.config(text=f"Fixed进度: {self.test_current_round}/{self.test_target_rounds} 轮")
                        else:
                            self.lbl_auto_status.config(text=f"Scan进度: Step {self.scan_step}/5 - {self.test_current_round}/{self.test_target_rounds} 轮")

                        if self.test_current_round < self.test_target_rounds:
                            self.root.after(10, lambda: self.send_pixel_cmd(silent=True, cmd_val=self.test_latched_cmd))
                        else:
                            if self.test_mode == "FIXED":
                                self.finish_test()
                            elif self.test_mode == "SCAN":
                                self.scan_step += 1
                                if self.scan_step < 6:
                                    self.test_current_round = 0
                                    self.root.after(50, self.run_scan_step)
                                else:
                                    self.finish_test()
            else:
                delta_str = pkt.get("delta", "")
                c_diff_str = pkt.get("c_diff", "")
                f_diff_str = pkt.get("f_diff", "")
                sel_str = pkt.get("sel", "000")
                csa_str = pkt.get("csa_label", "")
                self.tree.insert("", 0, values=(
                    pkt["time_str"], pkt["type"], pkt["id"], sel_str, csa_str,
                    pkt["coarse"], pkt["fine"], delta_str, pkt["raw_hex"]
                ))
                if len(self.tree.get_children()) > 1000:
                    self.tree.delete(self.tree.get_children()[-1])

            self.csv_data_buffer.append(pkt)
            processed += 1
            
        if processed > 0:
            self.lbl_stats.config(text=f"Total: {self.total_packets} | UP: {self.up_count} | DOWN: {self.down_count}")
        
        self.root.after(50, self.update_ui_from_queue)

    def get_current_cmd_int(self):
        rst_bit = 1 if self.var_rst.get() else 0
        csa_val = 0
        for i in range(6):
            if self.vars_csa[i].get():
                csa_val |= (1 << i)
        
        scan_ch = 0x3 
        cmd = (0 << 31) | (0 << 30) | (scan_ch << 28) | (0 << 20) | \
              (rst_bit << 19) | (csa_val << 13)
        return cmd

    def update_cmd_preview(self):
        cmd = self.get_current_cmd_int()
        self.lbl_cmd_hex.config(text=f"0x{cmd:08X}")

    def send_pixel_cmd(self, silent=False, cmd_val=None):
        if not self.is_connected:
            if not silent: messagebox.showwarning("警告", "请先连接串口")
            return
        
        if not self.test_mode or self.test_mode == "IDLE":
            s2 = self.var_sel2.get()
            s1 = self.var_sel1.get()
            s0 = self.var_sel0.get()
            self.current_active_sel_str = f"{s2}{s1}{s0}"
        
        if cmd_val is not None:
            cmd = cmd_val
        else:
            cmd = self.get_current_cmd_int()
            
        packet = struct.pack('<I', cmd)
        self.ser.write(packet)
        if not silent:
            print(f"Sent Pixel Cmd: 0x{cmd:08X}, Sel Record: {self.current_active_sel_str}")

    def send_recalibrate(self):
        if not self.is_connected: return
        cmd = 1 << 31
        self.ser.write(struct.pack('<I', cmd))

    def clear_data(self):
        self.tree.delete(*self.tree.get_children())
        self.total_packets = 0
        self.up_count = 0
        self.down_count = 0
        self.pending_ups.clear()
        self.csv_data_buffer = []
        self.lbl_stats.config(text="Total: 0")

    def save_data(self):
        if not self.csv_data_buffer: return
        filename = filedialog.asksaveasfilename(defaultextension=".csv")
        if filename:
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Time", "Ch", "ID", "Sel", "Coarse", "Fine", "CoarseDiff", "FineDiff", "Delta_ps", "RawHex", "CSA_Label"])
                for i in self.csv_data_buffer:
                    writer.writerow([
                        i["time_str"], i["ch"], i["id"], i.get("sel", "000"), i["coarse"], i["fine"], 
                        i.get("c_diff", ""), i.get("f_diff", ""), i.get("delta",""), i["raw_hex"], i.get("csa_label", "")
                    ])

if __name__ == "__main__":
    root = tk.Tk()
    try:
        from ttkthemes import ThemedTk
    except: pass
    
    style = ttk.Style()
    style.configure("Accent.TButton", foreground="blue", font=("Helvetica", 10, "bold"))
    
    app = TDC_GUI(root)
    root.mainloop()