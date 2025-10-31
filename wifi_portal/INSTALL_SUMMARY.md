# WiFi Portal - Raspberry Pi OS 原生安裝總結

## 📦 已建立的檔案

### 核心檔案

| 檔案 | 用途 | 說明 |
|------|------|------|
| `install.sh` | 一鍵安裝腳本 | 自動安裝系統依賴、建立虛擬環境、部署至 `/opt/wifi-portal` |
| `setup.py` | Python 套件設定 | 定義套件資訊和依賴項目 |
| `MANIFEST.in` | 套件資源清單 | 指定要包含的非 Python 檔案 |

### 服務管理

| 檔案 | 用途 | 說明 |
|------|------|------|
| `wifi-portal.service` | systemd 服務定義 | 定義系統服務的啟動方式和環境變數 |
| `portal-service.sh` | 服務管理腳本 | 提供簡化的服務控制介面 (start/stop/restart/logs) |

### AP 模式設定

| 檔案 | 用途 | 說明 |
|------|------|------|
| `setup-ap-mode.sh` | AP 模式配置腳本 | 自動設定 hostapd、dnsmasq、iptables 實現 captive portal |

### 開發與維護工具

| 檔案 | 用途 | 說明 |
|------|------|------|
| `run-dev.sh` | 開發伺服器啟動腳本 | 快速測試用，自動建立虛擬環境並啟動服務 |
| `reinstall.sh` | 快速重新安裝腳本 | 更新程式碼，自動備份並重啟服務 |
| `check-install.sh` | 安裝驗證腳本 | 檢查安裝是否正確，診斷常見問題 |

### 文檔

| 檔案 | 用途 | 說明 |
|------|------|------|
| `DEPLOYMENT.md` | 完整部署指南 | 詳細的安裝、配置、故障排除文檔 |
| `README.md` | 專案說明 | 更新後包含原生安裝和開發模式說明 |
| `INSTALL_SUMMARY.md` | 本文檔 | 快速參考指南 |

## 🚀 快速安裝指令

### 在 Raspberry Pi 上執行

```bash
cd /home/orson/Workspace/Toys/hwmonitor-mqtt/wifi_portal

# 1. 安裝系統服務
sudo ./install.sh

# 2. 配置 AP 模式（可選）
sudo /opt/wifi-portal/setup-ap-mode.sh

# 3. 啟動服務
sudo /opt/wifi-portal/portal-service.sh enable
sudo /opt/wifi-portal/portal-service.sh start

# 4. 查看狀態
sudo /opt/wifi-portal/portal-service.sh status
```

## 🚨 快速修復

如果遇到 `ModuleNotFoundError: No module named 'wifi_portal'` 錯誤：

```bash
# 最快的解決方法
cd /path/to/source/wifi_portal
sudo ./reinstall.sh
```

## 🔧 常用指令

### 服務管理

```bash
# 啟動服務
sudo /opt/wifi-portal/portal-service.sh start

# 停止服務
sudo /opt/wifi-portal/portal-service.sh stop

# 重啟服務
sudo /opt/wifi-portal/portal-service.sh restart

# 查看即時日誌
sudo /opt/wifi-portal/portal-service.sh logs

# 開機自動啟動
sudo /opt/wifi-portal/portal-service.sh enable

# 取消開機自動啟動
sudo /opt/wifi-portal/portal-service.sh disable
```

### 開發測試

```bash
# 快速啟動開發伺服器（不需安裝）
cd /home/orson/Workspace/Toys/hwmonitor-mqtt/wifi_portal
sudo ./run-dev.sh
```

### 更新程式碼

```bash
# 快速更新（推薦）
cd /path/to/source/wifi_portal
sudo ./reinstall.sh

# 驗證更新
sudo /opt/wifi-portal/check-install.sh
```

### AP 模式配置

```bash
# 使用預設設定（SSID: RasPi-Setup, 密碼: raspberry）
sudo /opt/wifi-portal/setup-ap-mode.sh

# 自訂 SSID 和密碼
sudo AP_SSID="MyPi-WiFi" AP_PASSWORD="mypassword123" /opt/wifi-portal/setup-ap-mode.sh

# 重啟 AP 相關服務
sudo systemctl restart dhcpcd
sudo systemctl restart hostapd
sudo systemctl restart dnsmasq
```

## 📋 安裝後的目錄結構

```
/opt/wifi-portal/
├── venv/                           # Python 虛擬環境
│   ├── bin/
│   │   ├── python
│   │   └── uvicorn
│   └── lib/
├── wifi_portal/                    # 主要程式碼
│   ├── __init__.py
│   ├── wifi_manager.py             # WiFi 管理模組
│   └── webui/                      # Web 介面
│       ├── __init__.py
│       ├── app.py                  # FastAPI 應用
│       ├── static/                 # 靜態資源
│       │   └── styles.css
│       └── templates/              # HTML 模板
│           ├── base.html
│           └── index.html
├── setup.py                        # 套件設定
├── MANIFEST.in                     # 資源清單
├── wifi-portal.service             # systemd 服務檔
├── setup-ap-mode.sh                # AP 配置腳本
├── portal-service.sh               # 服務管理腳本
└── DEPLOYMENT.md                   # 部署文檔

/etc/systemd/system/
└── wifi-portal.service             # systemd 服務（符號連結）
```

## 🔍 問題排查

### 服務無法啟動

```bash
# 查看詳細錯誤
sudo journalctl -u wifi-portal -n 50 --no-pager

# 手動測試啟動
cd /opt/wifi-portal
sudo venv/bin/python -m uvicorn wifi_portal.webui.app:app --host 0.0.0.0 --port 8080
```

### WiFi 掃描失敗

```bash
# 確認 NetworkManager 運行
sudo systemctl status NetworkManager

# 測試 nmcli
nmcli dev wifi list
```

### AP 模式問題

```bash
# 檢查 hostapd
sudo systemctl status hostapd
sudo journalctl -u hostapd -n 20

# 檢查 dnsmasq
sudo systemctl status dnsmasq
sudo journalctl -u dnsmasq -n 20

# 檢查網路介面
ip addr show wlan0
```

## 🌐 存取方式

### 標準模式
```
http://<raspberry-pi-ip>:8080
```

### AP 模式
```
http://192.168.4.1:8080
```

## 📝 環境變數

可在 `/etc/systemd/system/wifi-portal.service` 中修改：

```ini
Environment="WIFI_INTERFACE=wlan0"                    # WiFi 網卡名稱
Environment="WPA_SUPPLICANT_CONF=/etc/wpa_supplicant/wpa_supplicant.conf"  # 設定檔路徑
```

修改後記得重新載入：
```bash
sudo systemctl daemon-reload
sudo systemctl restart wifi-portal
```

## 🔐 安全建議

1. **變更 AP 預設密碼**：修改 `setup-ap-mode.sh` 中的 `AP_PASSWORD`
2. **限制網路存取**：使用防火牆限制 8080 埠的存取
3. **僅在需要時啟用 AP 模式**：平時可停用 hostapd 和 dnsmasq
4. **定期更新系統**：保持 Raspberry Pi OS 和套件為最新版本

## 📚 更多資訊

- 完整部署指南：[DEPLOYMENT.md](DEPLOYMENT.md)
- 專案說明：[README.md](README.md)
- WiFi 管理 API：查看 `wifi_portal/wifi_manager.py`
- Web UI 程式碼：查看 `wifi_portal/webui/app.py`

## ✅ 安裝驗證清單

- [ ] 執行 `install.sh` 無錯誤
- [ ] systemd 服務已註冊：`systemctl status wifi-portal`
- [ ] 服務可以啟動：`sudo /opt/wifi-portal/portal-service.sh start`
- [ ] 可以存取 Web UI：`http://<ip>:8080`
- [ ] WiFi 掃描功能正常
- [ ] 可以新增 WiFi 設定
- [ ] AP 模式正常運作（如果已配置）

---

建立日期：2025-10-21
版本：1.0.0
