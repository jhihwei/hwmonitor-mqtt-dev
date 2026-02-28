## 🧭 旋轉螢幕 (向左 90°)

1️⃣ 編輯開機參數

```bash
sudo nano /boot/firmware/cmdline.txt
```

> ⚠️ 注意：整行文字不能換行，請在最後加上

```
 fbcon=rotate:3
```

（前面要有空格）

2️⃣ 儲存後重新開機

```bash
sudo reboot
```

📌 `rotate:3`＝向左 90°（直式）
若想恢復橫式 → 把這段刪掉即可。

---

## 🔠 放大主控台字體

1️⃣ 安裝字體設定工具

```bash
sudo apt install -y console-setup
```

2️⃣ 執行設定精靈

```bash
sudo dpkg-reconfigure console-setup
```

依序選（建議先用 `24x12`，欄位較寬，比較不會截字）：

```
UTF-8 → Terminus → 24x12
```

若你想要更大字再改成 `32x16`。

3️⃣ 套用或重開

```bash
sudo setupcon
# 或
sudo reboot
```

---

## ✅ 推薦組合

| 功能   | 設定                           |
| ---- | ---------------------------- |
| 螢幕方向 | `fbcon=rotate:3`             |
| 字型   | Terminus                     |
| 字體大小 | 24x12（優先）/ 32x16（大字）         |
| 位置   | `/boot/firmware/cmdline.txt` |

---

## 🧪 TUI 不截字檢查

1️⃣ 檢查目前終端大小

```bash
stty size
```

建議直式畫面至少有：
- `28` 欄以上（columns）
- `32` 列以上（rows）

2️⃣ 啟動監控畫面

```bash
uv run python tui_viewer.py
```

3️⃣ 若還是覺得字太擠
- 先改回 `24x12`
- 再執行 `sudo setupcon`
- 或重開機讓設定完全生效

---

## 🎮 PyGame（Buffer Frame）建議（Raspberry Ubuntu ARM）

`pygame_viewer.py` 已改成：
- Backbuffer 離屏渲染
- `pygame.display.update(dirty_rects)` 區域更新（非每幀 `flip` 全畫面）
- 自動分頁（每頁 3 台，預設 15 秒）
- 固定 3 卡版面 + 黏著式翻頁（最後一頁不足 3 台時保留其餘卡位，不會突然變成單一卡）
- 設備列表固定排序顯示（不再因訊息到達時間導致卡片順序跳動）
- 字體整體放大（標題/主資訊/輔助資訊字級上調）
- Footer 改為雙行資訊（`RPI CPU/RAM/TEMP` 使用較大字體）
- 圖表動畫化（趨勢圖填色、掃描線、脈衝端點，並加入翻頁進度條）
- 相容目前 MQTT payload（`cpu/memory/network_io/disk_io/temperatures/gpus`）

### 啟動方式

```bash
uv run python pygame_viewer.py
```

在 Raspberry Ubuntu ARM 的純 console 環境，程式現在會預設使用：
- `SDL_VIDEODRIVER=kmsdrm`
- `PYGAME_FORCE_PORTRAIT=1`

### ARM / Console 建議參數

若你在純 console（無 X11/Wayland）：

```bash
SDL_VIDEODRIVER=kmsdrm uv run python pygame_viewer.py
```

若 `kmsdrm` 不可用再試：

```bash
SDL_VIDEODRIVER=fbcon uv run python pygame_viewer.py
```

### 可調參數（環境變數）

- `PYGAME_FULLSCREEN=1`：全螢幕（預設在無 DISPLAY 時會自動開）
- `PYGAME_FPS=10`：更新上限（建議 8~15）
- `PYGAME_PAGE_INTERVAL=15`：翻頁秒數（想更慢可改 `20` 或 `30`）
- `PYGAME_ANIMATE_UI=1`：UI 動畫開關（若想省資源可設 `0`）
- `PYGAME_STALE_SECONDS=10`：裝置過期顯示 STALE
- `PYGAME_PURGE_SECONDS=300`：裝置多久沒更新後移除
- `PYGAME_FORCE_PORTRAIT=1`：強制以直式邏輯畫布渲染（建議保持 1）
- `PYGAME_PORTRAIT_ROTATE_DEGREE=90`：需要時旋轉角度（可改 `-90`）

---

## 🔍 為何看起來還是橫式（重點）

`fbcon=rotate:<n>` 主要是 **Linux 文字主控台** 旋轉，不保證 SDL/PyGame 一定跟著旋轉。  
所以若 PyGame 仍橫式，建議改用 **KMS 的 `video=...rotate=...`** 做系統層旋轉。

---

## 🛠 Ubuntu on Raspberry（建議做法：KMS 旋轉）

1️⃣ 先查目前顯示輸出名稱（Connector）

```bash
ls /sys/class/drm | grep -E 'HDMI|DSI|Composite'
```

常見是：
- `HDMI-A-1`
- `HDMI-A-2`
- `DSI-1`

2️⃣ 設定開機 kernel 參數（單行）

```bash
sudo nano /boot/firmware/cmdline.txt
```

先查支援模式（避免黑屏）：

```bash
cat /sys/class/drm/card0-HDMI-A-1/modes
```

> ⚠️ 請只使用清單內有的模式。  
> 若使用不存在模式（例如某些環境的 `480x320`）可能會出現「沒有訊號」。

在同一行最後加上（範例）：

```text
video=HDMI-A-1:1280x720M@60,rotate=90
```

若方向反了改成：

```text
video=HDMI-A-1:1280x720M@60,rotate=270
```

3️⃣ 重新開機

```bash
sudo reboot
```

4️⃣ 開機後驗證參數是否生效

```bash
cat /proc/cmdline
```

應看得到你加的 `video=...rotate=...`。

---

## ✅ PyGame 端搭配建議

系統已旋轉後，直接執行：

```bash
uv run python pygame_viewer.py
```

若還不對，可切換：
- `PYGAME_PORTRAIT_ROTATE_DEGREE=90`
- `PYGAME_PORTRAIT_ROTATE_DEGREE=-90`

例如：

```bash
PYGAME_PORTRAIT_ROTATE_DEGREE=-90 uv run python pygame_viewer.py
```

---

## ⚙️ systemd 開機自啟（已確認 `90` 方向正確）

如果你要開機直接跑 PyGame 直式版，建議使用以下 service（用你目前路徑）：

```ini
[Unit]
Description=PyGame Viewer Service on LCD
After=network-online.target
Wants=network-online.target

[Service]
User=user
Group=tty
WorkingDirectory=/home/user/monitor

# 你的環境已確認 90 方向正確
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=PYGAME_FORCE_PORTRAIT=1
Environment=PYGAME_PORTRAIT_ROTATE_DEGREE=90

ExecStart=/home/user/monitor/venv/bin/python /home/user/monitor/pygame_viewer.py

StandardInput=tty
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

套用方式：

```bash
sudo nano /etc/systemd/system/pygame-viewer.service
sudo systemctl daemon-reload
sudo systemctl enable --now pygame-viewer.service
sudo systemctl status pygame-viewer.service -n 50
```

若你原本有 `tui_viewer.py` 的 service，可先停用避免衝突：

```bash
sudo systemctl disable --now tui-viewer.service
```

---

## 📎 參考（官方/主要）

- Raspberry Pi 文件（KMS `video=...rotate=...`）  
  https://www.raspberrypi.com/documentation/computers/configuration.html
- Linux Kernel 文件（`fbcon=rotate` 僅主控台旋轉）  
  https://www.kernel.org/doc/html/latest/fb/fbcon.html
- Pygame Display API（`display.update()` / `set_mode()`）  
  https://www.pygame.org/docs/ref/display.html

---
