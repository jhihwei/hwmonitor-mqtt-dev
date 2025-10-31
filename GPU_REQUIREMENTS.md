# GPU 監控系統需求

TUI Viewer 的 GPU 監控功能支援多種 GPU 類型，但某些功能需要額外的系統工具。

## Python 套件需求

### 必要套件
- **psutil >= 7.0.0** - 已包含在 `pyproject.toml` 中
  - 用於基本的溫度感測器讀取
  - 安裝：`uv pip install psutil`

## GPU 類型支援與系統工具需求

### NVIDIA GPU
**使用率與溫度檢測**：
- 需要 `nvidia-smi` 工具（包含在 NVIDIA 驅動中）
- 安裝方式：
  ```bash
  # Ubuntu/Debian
  sudo apt install nvidia-utils

  # 或安裝完整 NVIDIA 驅動
  sudo ubuntu-drivers autoinstall
  ```

### Intel GPU
**使用率檢測** (三種方法，按優先順序嘗試)：
1. `intel_gpu_top` 工具（推薦）
   ```bash
   # Ubuntu/Debian
   sudo apt install intel-gpu-tools
   ```
2. sysfs `/sys/class/drm/card0/engine/rcs0/busy_percent` (kernel 5.11+)
   - 無需額外安裝，需要較新的 kernel

**溫度檢測** (三種方法，按優先順序嘗試)：
1. psutil sensors (`i915`, `coretemp`, `pch_cannonlake`)
   - 無需額外安裝
2. sysfs hwmon `/sys/class/drm/card0/hwmon/hwmon*/temp*_input`
   - 無需額外安裝

### AMD GPU
**使用率檢測**：
- sysfs `/sys/class/drm/card0/device/gpu_busy_percent`
- 無需額外安裝，kernel 4.17+

**溫度檢測**：
- psutil sensors (`amdgpu`, `radeon`)
- 無需額外安裝

### Raspberry Pi GPU
**溫度檢測**：
- 需要 `vcgencmd` 工具（Raspberry Pi OS 預裝）
- 其他發行版可能需要安裝：
  ```bash
  sudo apt install libraspberrypi-bin
  ```

## 降級支援

**重要**：所有 GPU 監控功能都是可選的，失敗時會自動降級：
- GPU 使用率：失敗時返回 `0.0%`
- GPU 溫度：失敗時返回 `N/A`
- 顯示：無 GPU 時自動切換到僅顯示 CPU/RAM 的布局

## 安裝建議

### 最小安裝（僅 Python 套件）
```bash
uv sync
```

### 完整 GPU 支援（推薦）
```bash
# 安裝 Python 套件
uv sync

# Intel GPU 工具（可選）
sudo apt install intel-gpu-tools

# NVIDIA GPU 工具（可選，僅 NVIDIA 顯卡需要）
sudo apt install nvidia-utils
```

## 驗證 GPU 監控

### 檢查可用的 GPU
```bash
# 檢查 NVIDIA GPU
nvidia-smi

# 檢查 Intel GPU
intel_gpu_top -l

# 檢查 AMD GPU
cat /sys/class/drm/card0/device/gpu_busy_percent

# 檢查可用的溫度感測器
python3 -c "import psutil; print(psutil.sensors_temperatures())"
```

### 測試 TUI Viewer
```bash
uv run python tui_viewer.py
```

查看 footer 區域：
- **有 GPU**：顯示 `C xx.x% xx°C G xx.x% xx°C R xx.x%`
- **無 GPU**：顯示 `CPU xx.x% RAM xx.x% xx°C`

## 疑難排解

### GPU 使用率顯示 0.0%
- 檢查是否安裝相應的工具（如 `intel_gpu_top`, `nvidia-smi`）
- 檢查 sysfs 路徑是否存在
- 確認 kernel 版本符合需求

### GPU 溫度顯示 N/A
- 執行 `psutil.sensors_temperatures()` 檢查可用感測器
- 檢查 `/sys/class/drm/card0/hwmon/` 目錄是否存在
- 確認 GPU 驅動已正確載入

### 權限問題
某些系統工具可能需要 root 權限：
```bash
# 將使用者加入 video 群組
sudo usermod -a -G video $USER

# 重新登入後生效
```
