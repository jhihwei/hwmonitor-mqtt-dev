# WiFi Portal - Raspberry Pi OS 部署指南

本指南說明如何在 Raspberry Pi OS 上以原生方式（非 Docker）部署 WiFi 設定入口。

## 🚨 快速修復指南

如果您遇到 `ModuleNotFoundError: No module named 'wifi_portal'` 錯誤：

```bash
# 最快的解決方法
cd /path/to/source/wifi_portal
sudo ./reinstall.sh
```

詳細的故障排除請參考[常見問題](#常見問題)章節。

## 系統需求

- Raspberry Pi 3/4/5 或 Zero W
- Raspberry Pi OS (Bullseye 或更新版本)
- 支援 WiFi 的無線網卡（內建或 USB）
- Root 權限

## 快速安裝

### 一鍵安裝

```bash
cd /path/to/hwmonitor-mqtt/wifi_portal
sudo ./install.sh
```

安裝腳本會自動：
- 安裝系統依賴套件（Python, NetworkManager, wpa_supplicant）
- 建立虛擬環境並安裝 Python 套件
- 複製檔案到 `/opt/wifi-portal`
- 安裝 systemd 服務

### 配置 AP 模式（可選）

如果您想讓 Raspberry Pi 建立 WiFi 熱點：

```bash
sudo /opt/wifi-portal/setup-ap-mode.sh
```

配置選項（透過環境變數）：
```bash
# 自訂 SSID 和密碼
sudo AP_SSID="MyPi-Setup" AP_PASSWORD="mypassword" /opt/wifi-portal/setup-ap-mode.sh

# 自訂網卡介面
sudo WIFI_INTERFACE="wlan1" /opt/wifi-portal/setup-ap-mode.sh
```

## 服務管理

### 使用 portal-service.sh

```bash
# 啟動服務
sudo /opt/wifi-portal/portal-service.sh start

# 停止服務
sudo /opt/wifi-portal/portal-service.sh stop

# 重啟服務
sudo /opt/wifi-portal/portal-service.sh restart

# 查看狀態
sudo /opt/wifi-portal/portal-service.sh status

# 查看日誌
sudo /opt/wifi-portal/portal-service.sh logs

# 設定開機自動啟動
sudo /opt/wifi-portal/portal-service.sh enable

# 取消開機自動啟動
sudo /opt/wifi-portal/portal-service.sh disable
```

### 使用 systemctl

```bash
# 啟動服務
sudo systemctl start wifi-portal

# 停止服務
sudo systemctl stop wifi-portal

# 重啟服務
sudo systemctl restart wifi-portal

# 查看狀態
sudo systemctl status wifi-portal

# 開機自動啟動
sudo systemctl enable wifi-portal

# 查看日誌
sudo journalctl -u wifi-portal -f
```

## 使用方式

### 標準模式（連接現有 WiFi）

1. 確保 Raspberry Pi 已連接到網路
2. 啟動 WiFi Portal 服務
3. 在瀏覽器開啟：`http://<raspberry-pi-ip>:8080`
4. 透過 Web UI 管理 WiFi 設定

### AP 模式（建立熱點）

1. 執行 `setup-ap-mode.sh` 配置 AP 模式
2. 重啟 Raspberry Pi 或重啟相關服務：
   ```bash
   sudo systemctl restart dhcpcd
   sudo systemctl restart hostapd
   sudo systemctl restart dnsmasq
   ```
3. 使用手機或電腦連接到 Raspberry Pi 的熱點
   - 預設 SSID: `RasPi-Setup`
   - 預設密碼: `raspberry`
4. 開啟瀏覽器，會自動導向 `http://192.168.4.1:8080`
5. 透過 Web UI 設定 WiFi 並連接到您的網路

## 檔案結構

安裝後的檔案位置：

```
/opt/wifi-portal/
├── venv/                    # Python 虛擬環境
├── wifi_portal/             # 主要程式碼
│   ├── webui/               # FastAPI 應用
│   │   ├── app.py
│   │   ├── static/
│   │   └── templates/
│   └── wifi_manager.py      # WiFi 管理模組
├── wifi-portal.service      # systemd 服務檔
├── setup-ap-mode.sh         # AP 模式設定腳本
├── portal-service.sh        # 服務管理腳本
└── install.sh               # 安裝腳本

/etc/systemd/system/
└── wifi-portal.service      # systemd 服務（符號連結）
```

## 環境變數設定

編輯 `/etc/systemd/system/wifi-portal.service`：

```ini
[Service]
Environment="WIFI_INTERFACE=wlan0"
Environment="WPA_SUPPLICANT_CONF=/etc/wpa_supplicant/wpa_supplicant.conf"
Environment="PORTAL_PORT=8080"
```

修改後重新載入：
```bash
sudo systemctl daemon-reload
sudo systemctl restart wifi-portal
```

## 故障排除

### 查看服務狀態

```bash
sudo systemctl status wifi-portal
```

### 查看詳細日誌

```bash
# 即時日誌
sudo journalctl -u wifi-portal -f

# 最近 100 行
sudo journalctl -u wifi-portal -n 100

# 特定時間範圍
sudo journalctl -u wifi-portal --since "1 hour ago"
```

### 常見問題

#### 1. 服務無法啟動

**檢查步驟：**

```bash
# 查看詳細錯誤日誌
sudo journalctl -u wifi-portal -n 50 --no-pager

# 檢查 Python 環境
/opt/wifi-portal/venv/bin/python --version

# 手動測試啟動
cd /opt/wifi-portal
sudo PYTHONPATH=/opt/wifi-portal venv/bin/python -m uvicorn wifi_portal.webui.app:app --host 0.0.0.0 --port 8080
```

##### 常見錯誤 A：ModuleNotFoundError

這表示 Python 套件結構不正確。

```bash
# 解決方法 1: 使用重新安裝腳本（推薦）
cd /path/to/source/wifi_portal
sudo ./reinstall.sh

# 解決方法 2: 檢查目錄結構
ls -la /opt/wifi-portal/wifi_portal/
# 應該看到：__init__.py, wifi_manager.py, webui/

# 如果目錄結構不對，手動修正：
sudo mkdir -p /opt/wifi-portal/wifi_portal
sudo cp /path/to/source/wifi_portal/wifi_manager.py /opt/wifi-portal/wifi_portal/
sudo cp /path/to/source/wifi_portal/__init__.py /opt/wifi-portal/wifi_portal/
sudo cp -r /path/to/source/wifi_portal/webui /opt/wifi-portal/wifi_portal/
sudo systemctl restart wifi-portal
```

##### 常見錯誤 B：Port already in use

```bash
# 檢查 8080 埠是否被佔用
sudo lsof -i :8080

# 終止佔用的程序或修改埠號
sudo nano /etc/systemd/system/wifi-portal.service
# 修改 ExecStart 行中的 --port 8080
sudo systemctl daemon-reload
sudo systemctl restart wifi-portal
```

#### 2. WiFi 掃描失敗

```bash
# 確認 NetworkManager 運行中
sudo systemctl status NetworkManager

# 測試 nmcli 指令
nmcli dev wifi list
```

#### 3. AP 模式無法連接

```bash
# 檢查 hostapd 狀態
sudo systemctl status hostapd

# 檢查 dnsmasq 狀態
sudo systemctl status dnsmasq

# 檢查 iptables 規則
sudo iptables -t nat -L -v
```

#### 4. 權限問題

```bash
# 確認服務以 root 執行
ps aux | grep uvicorn

# 檢查設定檔權限
ls -l /etc/wpa_supplicant/wpa_supplicant.conf
```

## 更新與維護

### 快速更新（推薦）

使用重新安裝腳本，自動備份並更新：

```bash
cd /path/to/source/wifi_portal
sudo ./reinstall.sh
```

此腳本會：

- 自動停止服務
- 建立備份（含時間戳記）
- 更新所有檔案
- 更新 Python 依賴
- 重新啟動服務

### 手動更新程式碼

```bash
# 停止服務
sudo systemctl stop wifi-portal

# 備份現有安裝
sudo cp -r /opt/wifi-portal /opt/wifi-portal.backup.$(date +%Y%m%d)

# 更新 Python 套件檔案
cd /path/to/source/wifi_portal
sudo mkdir -p /opt/wifi-portal/wifi_portal
sudo cp wifi_manager.py /opt/wifi-portal/wifi_portal/
sudo cp __init__.py /opt/wifi-portal/wifi_portal/
sudo cp -r webui /opt/wifi-portal/wifi_portal/

# 更新腳本和設定
sudo cp *.sh /opt/wifi-portal/
sudo cp *.service /opt/wifi-portal/
sudo cp *.md /opt/wifi-portal/

# 更新 systemd 服務
sudo cp /opt/wifi-portal/wifi-portal.service /etc/systemd/system/
sudo systemctl daemon-reload

# 更新依賴（如果有新增套件）
sudo /opt/wifi-portal/venv/bin/pip install --upgrade uvicorn fastapi jinja2 python-multipart

# 重啟服務
sudo systemctl start wifi-portal
```

### 備份設定

```bash
# 備份 wpa_supplicant 設定
sudo cp /etc/wpa_supplicant/wpa_supplicant.conf \
        /etc/wpa_supplicant/wpa_supplicant.conf.backup

# 備份 AP 模式設定
sudo cp /etc/hostapd/hostapd.conf /etc/hostapd/hostapd.conf.backup
sudo cp /etc/dnsmasq.conf /etc/dnsmasq.conf.backup
```

## 卸載

```bash
# 停止並停用服務
sudo systemctl stop wifi-portal
sudo systemctl disable wifi-portal

# 移除服務檔
sudo rm /etc/systemd/system/wifi-portal.service
sudo systemctl daemon-reload

# 移除程式檔案
sudo rm -rf /opt/wifi-portal

# 恢復 AP 模式設定（如果有設定）
sudo cp /etc/hostapd/hostapd.conf.bak /etc/hostapd/hostapd.conf
sudo cp /etc/dnsmasq.conf.bak /etc/dnsmasq.conf
sudo cp /etc/dhcpcd.conf.bak /etc/dhcpcd.conf
```

## 安全建議

1. **變更預設密碼**：修改 AP 模式的預設密碼
2. **限制網路存取**：僅在設定時啟用 AP 模式
3. **定期更新**：保持系統和套件為最新版本
4. **防火牆設定**：考慮使用 ufw 限制 8080 埠的存取

```bash
# 僅允許本地網路存取
sudo ufw allow from 192.168.4.0/24 to any port 8080
```

## 進階設定

### 使用 HTTPS

建議使用 Nginx 作為反向代理：

```bash
sudo apt-get install nginx certbot

# 設定 Nginx 反向代理
sudo nano /etc/nginx/sites-available/wifi-portal
```

範例 Nginx 設定：
```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 自訂 Portal 介面

編輯模板：
```bash
sudo nano /opt/wifi-portal/wifi_portal/webui/templates/index.html
```

修改樣式：
```bash
sudo nano /opt/wifi-portal/wifi_portal/webui/static/styles.css
```

重啟服務以套用變更：
```bash
sudo systemctl restart wifi-portal
```

## 授權與支援

本專案為開源軟體，使用前請詳閱授權條款。

如有問題或建議，請至 GitHub Issues 回報。
