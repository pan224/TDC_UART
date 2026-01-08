import os
import glob
import csv
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from datetime import datetime

def analyze_unit_delay():
    # === 1. 基础配置 ===
    # 脚本位置推导 data 目录 (假设脚本在 scripts/ 下)
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    base_data_dir = os.path.join(script_dir, "..", "data")
    base_data_dir = os.path.normpath(base_data_dir)

    # 像素对应的系数表 (Delta T = Coeff * tau)
    # tau = Delta T / Coeff
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

    # 存储绘图数据
    # 结构: plot_data[csa_index] = { 'sel': [], 'mean': [], 'std': [] }
    plot_data = {i: {'sel': [], 'mean': [], 'std': []} for i in range(6)}

    print(f"[-] 开始分析单位延时 (Unit Delay)...")
    print(f"[-] 数据目录: {base_data_dir}")
    print("-" * 60)

    # === 2. 遍历读取数据 ===
    for sel_val in sel_range:
        sel_bin_str = f"{sel_val:03b}" # 格式化为 001, 010...
        target_sel_dir = os.path.join(base_data_dir, f"SEL{sel_bin_str}")

        # 检查文件夹
        if not os.path.exists(target_sel_dir):
            continue
        
        sub_dirs = [d for d in glob.glob(os.path.join(target_sel_dir, "*")) if os.path.isdir(d)]
        if not sub_dirs:
            continue
            
        # 取最新实验
        latest_experiment_dir = max(sub_dirs, key=os.path.getmtime)
        
        print(f"处理 SEL={sel_bin_str} (实验: {os.path.basename(latest_experiment_dir)})")

        # 遍历每个 CSA 像素
        for csa_idx in range(6):
            # 优先寻找分拣后的 CSAx.csv
            csv_filename = f"CSA{csa_idx}.csv"
            csv_path = os.path.join(latest_experiment_dir, csv_filename)
            
            # 如果找不到分文件，尝试从 data.csv 中筛选 (兼容旧数据)
            rows_to_process = []
            if os.path.exists(csv_path):
                # 读取 CSAx.csv
                try:
                    with open(csv_path, 'r', newline='') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if "Delta_ps" in row and row["Delta_ps"]:
                                rows_to_process.append(float(row["Delta_ps"]))
                except Exception as e:
                    print(f"  [Error] 读取 {csv_filename} 失败: {e}")
            else:
                # 尝试读取 data.csv 并筛选
                main_csv = os.path.join(latest_experiment_dir, "data.csv")
                if os.path.exists(main_csv):
                    try:
                        with open(main_csv, 'r', newline='') as f:
                            reader = csv.DictReader(f)
                            target_label = f"CSA{csa_idx}"
                            for row in reader:
                                # 检查标签列
                                if row.get("CSA_Label") == target_label or row.get("csa_label") == target_label:
                                    if row["Delta_ps"]:
                                        rows_to_process.append(float(row["Delta_ps"]))
                    except:
                        pass

            # 如果该像素在该SEL下有数据，进行计算
            if rows_to_process:
                raw_deltas = np.array(rows_to_process)
                coeff = pixel_coeffs[csa_idx]
                
                # 核心计算：计算单位延时 tau
                # tau = Delta_T / coeff
                # 注意：如果 coeff 为负，且 delta 也为负，tau 为正。
                unit_delays = raw_deltas / coeff
                
                mean_tau = np.mean(unit_delays)
                std_tau = np.std(unit_delays)
                
                # 存入列表
                plot_data[csa_idx]['sel'].append(sel_val)
                plot_data[csa_idx]['mean'].append(mean_tau)
                plot_data[csa_idx]['std'].append(std_tau)
                
                print(f"  CSA{csa_idx}: 样本数={len(raw_deltas)}, Mean_Tau={mean_tau:.2f} ps")

    # === 3. 绘图 (2行3列) ===
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle('Unit Delay Analysis per Pixel vs. SEL Setting', fontsize=16, fontweight='bold')
    
    # 扁平化 ax 数组方便遍历
    axes_flat = axes.flatten()

    for csa_idx in range(6):
        ax = axes_flat[csa_idx]
        data = plot_data[csa_idx]
        
        x = np.array(data['sel'])
        y = np.array(data['mean'])
        yerr = np.array(data['std'])
        
        if len(x) > 0:
            # 绘制 Errorbar
            ax.errorbar(x, y, yerr=yerr, fmt='o', capsize=4, capthick=1.5, 
                        ecolor='red', color='blue', markersize=6, label='Unit Delay')
            
            # 线性拟合
            if len(x) > 1:
                z = np.polyfit(x, y, 1)
                p = np.poly1d(z)
                x_line = np.linspace(min(x)-0.5, max(x)+0.5, 100)
                ax.plot(x_line, p(x_line), "g--", alpha=0.6, label=f'Fit: {z[0]:.2f}x+{z[1]:.1f}')
                
                # 显示斜率 (Sensitivity)
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
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_file = os.path.join(base_data_dir, f"Unit_Delay_Analysis_{timestamp}.png")
    plt.savefig(save_file)
    print(f"\n[完成] 单位延时分析图已保存至: {save_file}")
    plt.show()

if __name__ == "__main__":
    analyze_unit_delay()