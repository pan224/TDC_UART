import os
import glob
import csv
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from datetime import datetime

def analyze_unit_delay():
    # === 1. 基础配置 ===
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    base_data_dir = os.path.join(script_dir, "..", "data")
    base_data_dir = os.path.normpath(base_data_dir)

    # 像素对应的系数表 (Delta T = Coeff * tau)
    pixel_coeffs = {
        0: 5,
        1: 3,
        2: 1,
        3: -1,
        4: -3,
        5: -5
    }

    # SEL 范围 (1-7)
    sel_range = range(1, 8)

    # === 默认/备用数据配置 ===
    # 格式: { SEL值: { CSA索引: Delta_T_ps } }
    # 当文件读取失败时，将使用此处的默认值
    manual_defaults = {
        4: { # SEL=4 (即 SEL100) 的示波器测量数据
            0: 47720,
            1: 26244,
            2: 8852,
            3: -10577,
            4: -27960,
            5: -45367
        }
    }

    # 存储绘图数据
    plot_data = {i: {'sel': [], 'mean': [], 'std': []} for i in range(6)}

    print(f"[-] 开始分析单位延时 (Unit Delay)...")
    print(f"[-] 数据目录: {base_data_dir}")
    print("-" * 60)

    # === 2. 遍历处理数据 ===
    for sel_val in sel_range:
        sel_bin_str = f"{sel_val:03b}" # 格式化为 001, 010...
        target_sel_dir = os.path.join(base_data_dir, f"SEL{sel_bin_str}")
        
        # 尝试获取最新的实验目录
        latest_experiment_dir = None
        if os.path.exists(target_sel_dir):
            sub_dirs = [d for d in glob.glob(os.path.join(target_sel_dir, "*")) if os.path.isdir(d)]
            if sub_dirs:
                latest_experiment_dir = max(sub_dirs, key=os.path.getmtime)
        
        # 打印状态
        if latest_experiment_dir:
            print(f"处理 SEL={sel_bin_str} (实验: {os.path.basename(latest_experiment_dir)})")
        else:
            print(f"处理 SEL={sel_bin_str} (未找到实验文件，尝试查找默认数据...)")

        # 遍历每个 CSA 像素
        for csa_idx in range(6):
            rows_to_process = []
            
            # --- 步骤 A: 尝试从文件中读取数据 ---
            if latest_experiment_dir:
                # 1. 优先读取分拣后的 CSAx.csv
                csv_filename = f"CSA{csa_idx}.csv"
                csv_path = os.path.join(latest_experiment_dir, csv_filename)
                
                if os.path.exists(csv_path):
                    try:
                        with open(csv_path, 'r', newline='') as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                if "Delta_ps" in row and row["Delta_ps"]:
                                    rows_to_process.append(float(row["Delta_ps"]))
                    except Exception as e:
                        print(f"  [Warn] 读取 {csv_filename} 失败: {e}")
                
                # 2. 如果分文件没数据，尝试从 data.csv 筛选
                if not rows_to_process:
                    main_csv = os.path.join(latest_experiment_dir, "data.csv")
                    if os.path.exists(main_csv):
                        try:
                            with open(main_csv, 'r', newline='') as f:
                                reader = csv.DictReader(f)
                                target_label = f"CSA{csa_idx}"
                                for row in reader:
                                    if row.get("CSA_Label") == target_label or row.get("csa_label") == target_label:
                                        if row["Delta_ps"]:
                                            rows_to_process.append(float(row["Delta_ps"]))
                        except:
                            pass

            # --- 步骤 B: 数据处理与决策 ---
            coeff = pixel_coeffs[csa_idx]
            
            if rows_to_process:
                # Case 1: 成功读取到文件数据
                raw_deltas = np.array(rows_to_process)
                unit_delays = raw_deltas / coeff
                
                mean_tau = np.mean(unit_delays)
                std_tau = np.std(unit_delays)
                
                plot_data[csa_idx]['sel'].append(sel_val)
                plot_data[csa_idx]['mean'].append(mean_tau)
                plot_data[csa_idx]['std'].append(std_tau)
                
                print(f"  CSA{csa_idx}: [File] 样本数={len(raw_deltas)}, Mean={mean_tau:.2f} ps")
            
            else:
                # Case 2: 未检测到数据，检查是否有默认数据 (Fallback)
                if sel_val in manual_defaults and csa_idx in manual_defaults[sel_val]:
                    manual_delta = manual_defaults[sel_val][csa_idx]
                    
                    # 计算 Tau (假设 Delta = Coeff * Tau)
                    mean_tau = manual_delta / coeff
                    std_tau = 0.0 # 默认数据无方差信息
                    
                    plot_data[csa_idx]['sel'].append(sel_val)
                    plot_data[csa_idx]['mean'].append(mean_tau)
                    plot_data[csa_idx]['std'].append(std_tau)
                    
                    print(f"  CSA{csa_idx}: [Default] 使用默认值 Delta={manual_delta} ps, Calc_Tau={mean_tau:.2f} ps")
                else:
                    # Case 3: 既无文件也无默认值
                    pass

    # === 3. 绘图 (2行3列) ===
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle('Unit Delay Analysis per Pixel vs. SEL Setting', fontsize=16, fontweight='bold')
    
    axes_flat = axes.flatten()

    for csa_idx in range(6):
        ax = axes_flat[csa_idx]
        data = plot_data[csa_idx]
        
        x = np.array(data['sel'])
        y = np.array(data['mean'])
        yerr = np.array(data['std'])
        
        if len(x) > 0:
            # 绘制数据点
            ax.errorbar(x, y, yerr=yerr, fmt='o', capsize=4, capthick=1.5, 
                        ecolor='red', color='blue', markersize=6, label='Unit Delay')
            
            # 线性拟合
            if len(x) > 1:
                z = np.polyfit(x, y, 1)
                p = np.poly1d(z)
                x_line = np.linspace(min(x)-0.5, max(x)+0.5, 100)
                ax.plot(x_line, p(x_line), "g--", alpha=0.6, label=f'Fit: {z[0]:.2f}x+{z[1]:.1f}')
                
                ax.text(0.05, 0.95, f"Sensitivity:\n{z[0]:.2f} ps/LSB", 
                        transform=ax.transAxes, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.3))

            ax.set_title(f'Pixel CSA{csa_idx} (Coeff={pixel_coeffs[csa_idx]})', fontsize=12, fontweight='bold')
            ax.set_xlabel('SEL Value')
            ax.set_ylabel('Unit Delay (ps)')
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.legend(loc='lower right', fontsize='small')
            ax.grid(True, linestyle='--', alpha=0.5)
        else:
            ax.text(0.5, 0.5, "No Data", ha='center', va='center')
            ax.set_title(f'Pixel CSA{csa_idx}')

    plt.tight_layout()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_file = os.path.join(base_data_dir, f"Unit_Delay_Analysis_{timestamp}.png")
    plt.savefig(save_file)
    print(f"\n[完成] 单位延时分析图已保存至: {save_file}")
    plt.show()

if __name__ == "__main__":
    analyze_unit_delay()