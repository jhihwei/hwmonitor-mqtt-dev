# Hardware Monitor via MQTT

[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![MQTT](https://img.shields.io/badge/MQTT-Protocol-orange.svg)](https://mqtt.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

輕量級系統監控解決方案，透過 MQTT 協定收集並發送硬體監控資料，提供即時 Web 介面查看系統狀態。

## ✨ 特色

- 🚀 **輕量高效** - Docker 容器化部署，資源佔用極低
- 📊 **即時監控** - 透過 MQTT 即時推送系統狀態
- 🌐 **Web 介面** - 現代化響應式監控介面
- 🔒 **安全設計** - 唯讀檔案系統、最小權限原則
- 🔧 **靈活部署** - 支援多種服務組合（agent、broker、web）
- 📡 **多主機支援** - 支援監控多台主機

## 🚀 快速開始

### 前置需求

- Docker & Docker Compose
- MQTT Broker（使用外部 broker 或本專案內建的 mosquitto）

### 1. 配置環境變數

```bash
# 複製範例檔案
cp .env.example .env

# 編輯 .env 檔案，設定 MQTT Broker 連線資訊
nano .env
```

`.env` 檔案內容：

```bash
BROKER_HOST=192.168.1.100  # MQTT Broker IP
BROKER_PORT=1883           # MQTT Port
MQTT_USER=your_username    # MQTT 使用者名稱
MQTT_PASS=your_password    # MQTT 密碼
WEB_PORT=8088              # Web 介面端口
```

### 2. 選擇部署模式

#### 模式 A：只啟動監控代理（連接到外部 MQTT Broker）

適用於：已有 MQTT Broker，只需要安裝監控代理到各主機

```bash
docker compose --profile agent up -d
```

#### 模式 B：啟動監控代理 + Web 介面

適用於：已有 MQTT Broker，需要監控代理和 Web 介面

```bash
docker compose --profile agent --profile web up -d
```

#### 模式 C：完整部署（Agent + Broker + Web）

適用於：從零開始，需要完整的監控系統

```bash
docker compose --profile full up -d
```

或簡化為：

```bash
docker compose --profile agent --profile broker --profile web up -d
```

### 💻 Windows 使用者

本專案的 Agent 也可以直接在 Windows 上執行（不透過 Docker）。

1.  **安裝 [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)**：
    *   下載並執行 LibreHardwareMonitor。
    *   **必須以管理員權限執行**。
    *   在 `Options` -> `General` 中，確保 `WMI Provider` 已啟用。
2.  **執行 Agent**：
    *   使用 `agent_sender_windows.py` 腳本。
    *   確保您的環境已安裝必要的 Python 套件 (`wmi`, `psutil`, `paho-mqtt`, `python-dotenv`)。
    *   設定好 `.env` 檔案後，執行：
        ```bash
        # 假設您使用 uv
        uv run .\agent_sender_windows.py
        ```


### 3. 訪問監控介面

```bash
# 預設端口 8088
open http://localhost:8088

# 或使用自訂端口（在 .env 中設定 WEB_PORT）
open http://localhost:YOUR_PORT
```

## 📡 架構說明

```
┌─────────────┐     MQTT      ┌──────────────┐
│  sys_agent  │──────────────>│ MQTT Broker  │
│  (Docker)   │   publish     │ (mqtt_broker)│
└─────────────┘               └──────┬───────┘
                                     │
                                     │ WebSocket
                                     │ subscribe
                                     ↓
┌─────────────┐    HTTP       ┌─────────────┐
│   Browser   │<──────────────│web_monitor  │
│             │   monitor.html│  (Nginx)    │
└─────────────┘               └─────────────┘
```

### 組件說明

| 組件 | 說明 | Profile |
|------|------|---------|
| **sys_agent** | 系統監控代理，收集硬體資訊並發送到 MQTT | `agent` |
| **mqtt_broker** | Mosquitto MQTT Broker（含 WebSocket 支援） | `broker` |
| **web_monitor** | Nginx 靜態 Web 監控介面 | `web` |

#### sys_agent（系統監控代理）

- 使用 Python + psutil 收集系統資訊
- 每秒發送一次監控資料到 MQTT
- Topic: `hwmon/<hostname>`
- 支援溫度、磁碟、網路監控

#### mqtt_broker（MQTT Broker）

- 基於 Eclipse Mosquitto 2.0.21
- 支援 MQTT TCP (1883) 和 WebSocket (8081)
- 使用 `mosquitto.conf` 和 `mosquitto_passwd` 配置

#### web_monitor（Web 監控介面）

- Nginx Alpine 靜態檔案伺服器
- 透過 MQTT WebSocket 訂閱監控資料
- 響應式設計，支援手機/平板/桌面

## 🛠️ 常用指令

```bash
# 查看服務狀態
docker compose ps

# 查看即時日誌
docker compose logs -f

# 只查看 Agent 日誌
docker compose logs -f sys_agent

# 停止服務
docker compose down

# 重建並啟動（以 agent 為例）
docker compose --profile agent up -d --build

# 重啟特定服務
docker compose restart sys_agent

# 列出所有 profiles 的服務
docker compose config --profiles
```

## 📊 監控資料格式

**MQTT Topic**: `hwmon/<hostname>`

**訊息格式（JSON）**：

```json
{
  "ts": 1697123456.789,
  "hostname": "server-01",
  "cpu": {
    "percent_total": 25.5,
    "percent_per_core": [20.1, 30.5, ...],
    "count_physical": 4,
    "count_logical": 8
  },
  "memory": {
    "ram": {
      "total": 17179869184,
      "used": 8589934592,
      "available": 8589934592,
      "percent": 50.0
    },
    "swap": {
      "total": 4294967296,
      "used": 0,
      "free": 4294967296,
      "percent": 0.0
    }
  },
  "disks": {
    "nvme0n1": {
      "read_bytes_per_s": 1048576,
      "write_bytes_per_s": 2097152,
      "read_iops": 100,
      "write_iops": 200
    }
  },
  "network": {
    "total": {
      "rate": {
        "rx_bytes_per_s": 1048576,
        "tx_bytes_per_s": 524288
      }
    },
    "per_nic": {
      "eth0": {
        "rate": {
          "rx_bytes_per_s": 1048576,
          "tx_bytes_per_s": 524288
        }
      }
    }
  },
  "temperatures": {
    "coretemp": [...],
    "k10temp": [...],
    "nvme": [...]
  }
}
```

## 🔧 進階配置

### 多主機監控

每台主機只需運行 `sys_agent`，連接到同一個 MQTT Broker：

```bash
# 主機 1（運行 Agent + Broker + Web）
docker compose --profile full up -d

# 主機 2（只運行 Agent）
docker compose --profile agent up -d

# 主機 3（只運行 Agent）
docker compose --profile agent up -d
```

Web 介面會自動顯示所有主機的監控資料。

### 自訂 Web Server Port

編輯 `.env` 檔案：

```bash
WEB_PORT=3000  # 使用 3000 port
```

### 配置內建 MQTT Broker

如果使用內建的 `mqtt_broker`，需要配置：

1. **編輯 mosquitto.conf**：設定監聽端口、WebSocket 等
2. **建立密碼檔**：

```bash
# 建立 mosquitto 密碼檔
docker run -it --rm eclipse-mosquitto:2.0.21 \
  mosquitto_passwd -c -b /tmp/passwd your_username your_password

# 複製到專案目錄
cp /tmp/passwd ./mosquitto_passwd
```

### 自訂 Web 介面 MQTT 連線

編輯 `monitor.html` 中的 WebSocket 連線設定：

```javascript
const brokerUrl = "ws://YOUR_BROKER_IP:8081";  // MQTT WebSocket URL
const username = "your_username";
const password = "your_password";
```

### MQTT 測試

安裝 Mosquitto 客戶端測試連線：

```bash
# 安裝
sudo apt install mosquitto-clients

# 訂閱監控主題
mosquitto_sub -h YOUR_BROKER_IP -p 1883 \
  -u your_username -P your_password \
  -t "hwmon/#" -v

# 預期輸出
hwmon/server-01 {"cpu": {...}, "memory": {...}, ...}
```

## 🔒 安全性

### 內建安全措施

- ✅ 容器唯讀檔案系統
- ✅ 禁止權限提升（no-new-privileges）
- ✅ 最小權限原則（非 privileged mode）
- ✅ tmpfs 掛載臨時目錄
- ✅ Alpine Linux 基礎映像

### 生產環境建議

1. **使用 HTTPS** - 透過 Caddy 或 Traefik 反向代理
2. **啟用認證** - 在 Nginx 前加上 Basic Auth
3. **環境變數** - 使用 `.env` 檔案管理敏感資訊（不要提交到 Git）
4. **網路隔離** - 限制訪問 IP 範圍
5. **定期更新** - 保持 Docker 映像檔最新

## 🐛 疑難排解

### Agent 無法連線到 MQTT

```bash
# 1. 檢查 Broker 是否運行
telnet YOUR_BROKER_IP 1883

# 2. 檢查 Agent 日誌
docker compose logs sys_agent | tail -20

# 3. 驗證環境變數
docker compose config | grep BROKER
```

### Web 介面無法訪問

```bash
# 1. 確認 port 沒被佔用
sudo netstat -tuln | grep 8088

# 2. 確認容器運行
docker compose ps web_monitor

# 3. 測試 HTTP 連線
curl -v http://localhost:8088
```

### 監控介面顯示「連線中」

1. 確認 MQTT Broker 啟用 WebSocket（通常是 port 8081）
2. 開啟瀏覽器 DevTools → Console 查看錯誤訊息
3. 確認 `monitor.html` 中的 WebSocket 連線設定正確
4. 檢查防火牆是否阻擋 WebSocket 連線

## 📈 效能指標

| 組件 | 記憶體使用 | CPU 使用 | 啟動時間 |
|------|-----------|---------|---------|
| sys_agent | ~50MB | <1% | ~2秒 |
| mqtt_broker | ~20MB | <0.5% | ~1秒 |
| web_monitor | ~10MB | <0.5% | ~1秒 |

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

## 📄 授權

MIT License - 詳見 [LICENSE](LICENSE) 檔案

## 🙏 致謝

- [psutil](https://github.com/giampaolo/psutil) - 系統監控函式庫
- [Paho MQTT](https://github.com/eclipse/paho.mqtt.python) - MQTT 客戶端
- [Eclipse Mosquitto](https://mosquitto.org/) - MQTT Broker
- [Nginx](https://nginx.org/) - Web 伺服器
- [Tailwind CSS](https://tailwindcss.com/) - UI 框架

---

⭐ 如果這個專案對你有幫助，請給個 Star！
