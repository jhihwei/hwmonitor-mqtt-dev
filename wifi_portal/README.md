# Raspberry Pi Wi-Fi 設定入口

此資料夾提供一個 FastAPI Web UI，可搭配 Raspberry Pi OS 的 AP 模式，讓使用者在連線至樹莓派建立的熱點後設定 Wi-Fi。

## 快速開始

### 方式 1: 原生系統安裝（推薦用於生產環境）

在 Raspberry Pi 上一鍵安裝為系統服務：

```bash
sudo ./install.sh
sudo /opt/wifi-portal/portal-service.sh enable
sudo /opt/wifi-portal/portal-service.sh start
```

詳細說明請參考 [DEPLOYMENT.md](DEPLOYMENT.md)

### 方式 2: 開發模式（快速測試）

```bash
# 使用開發啟動腳本（自動建立虛擬環境）
sudo ./run-dev.sh

# 或使用 uv（需要先安裝 uv）
uv sync
uv run uvicorn wifi_portal.webui.app:app --host 0.0.0.0 --port 8080
```

連上樹莓派的 AP 後，開啟 `http://192.168.4.1:8080`（請依實際 AP 網段調整）。

## 3. Docker Compose 啟動

```bash
cd wifi_portal
docker compose up --build
```

Compose 版本會：

- 使用 host network
- 掛載 `/etc/wpa_supplicant` 與 `/run/wpa_supplicant`
- 以 `privileged: true` 方式執行，以便存取網路設備

請以 root 或具備網路管理權限的使用者執行，並確認系統已安裝 `network-manager`、`wpa_supplicant`。

### 環境變數

- `WIFI_INTERFACE`（預設 `wlan0`）
- `WPA_SUPPLICANT_CONF`（預設 `/etc/wpa_supplicant/wpa_supplicant.conf`）

## 4. 功能說明

- **目前連線狀態**：使用 `nmcli device show` 顯示連線名稱、IP、閘道。
- **已儲存網路**：分析 `wpa_supplicant.conf`，列出已設定的 SSID。
- **附近 Wi-Fi**：執行 `nmcli dev wifi list` 掃描，顯示訊號強度與安全性。
- **新增 Wi-Fi**：表單提交後備份原始設定檔，寫入新的 network 區塊，再呼叫 `wpa_cli reconfigure`。

> ⚠️ 調整 Wi-Fi 設定涉及網路驅動與系統檔案，操作前請備份並確保擁有適當權限。

## 5. 檔案結構

```
wifi_portal/
├── Dockerfile            # 容器化設定
├── README.md             # 本說明文件
├── docker-compose.yml    # 啟動 Wi-Fi 設定入口的 compose
├── webui/                # FastAPI App 與模板
│   ├── __init__.py
│   ├── app.py
│   ├── static/
│   │   └── styles.css
│   └── templates/
│       ├── base.html
│       └── index.html
└── wifi_manager.py       # 與 wpa_supplicant / nmcli 互動的工具類別
```
