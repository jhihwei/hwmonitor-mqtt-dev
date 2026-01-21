#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HW Monitor MQTT TUI Viewer - Portrait Mode (No-Flicker + Sticky Last Page + Full-Width Blue Title Bar)
- 3 個固定槽位（Slot），避免 mount/remove 造成的閃爍
- 翻頁：若最後一頁不足 3 台，只更新前 N 個槽位，後面沿用上一頁（黏著式）
- 標題列：整條滿版藍底（含右側警示）
"""
import json
import os
import time
from collections import deque
from typing import List, Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Static, Label
from textual.reactive import reactive
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
import psutil
import socket

load_dotenv()

# --- MQTT Configuration ---
BROKER_HOST = os.getenv("BROKER_HOST", "192.168.5.33")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "mqtter")
MQTT_PASS = os.getenv("MQTT_PASS", "seven777")
TOPIC = "sys/agents/+/metrics"

# --- Display Configuration ---
MAX_DEVICES_PER_PAGE = 3           # 固定每頁 3 個
ROTATION_INTERVAL_SECONDS = 5      # 翻頁間隔（秒）
STALE_SECONDS = 10                  # 超過 N 秒未更新即顯示「⚠」

def format_bytes(byte_count):
    if byte_count is None or byte_count == 0:
        return "0B"
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while byte_count >= power and n < len(power_labels) - 1:
        byte_count /= power
        n += 1
    return f"{byte_count:.1f}{power_labels[n]}"

class HostInfoFooter(Static):
    """Footer：顯示本機 CPU / RAM / Temp / GPU 使用率與溫度"""

    def __init__(self) -> None:
        super().__init__()
        self.hostname = socket.gethostname()

    def get_host_temp(self) -> str:
        try:
            temps = psutil.sensors_temperatures()
            for sensor_name in ['cpu_thermal', 'thermal_zone0', 'cpu-thermal']:
                if sensor_name in temps and temps[sensor_name]:
                    return f"{temps[sensor_name][0].current:.0f}°C"
            for sensor_name, entries in temps.items():
                if entries:
                    return f"{entries[0].current:.0f}°C"
        except Exception:
            pass
        return "N/A"

    def get_host_cpu(self) -> float:
        try:
            return psutil.cpu_percent(interval=0)
        except Exception:
            return 0.0

    def get_host_ram(self) -> float:
        try:
            return psutil.virtual_memory().percent
        except Exception:
            return 0.0

    def get_host_gpu_usage(self) -> float:
        try:
            import subprocess
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass

        try:
            import subprocess
            result = subprocess.run(['intel_gpu_top', '-o', '-', '-s', '100'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Render/3D' in line:
                        parts = line.split(':')
                        if len(parts) > 1:
                            pct = parts[1].strip().replace('%', '')
                            return float(pct)
        except Exception:
            pass

        try:
            with open('/sys/class/drm/card0/engine/rcs0/busy_percent', 'r') as f:
                return float(f.read().strip())
        except Exception:
            pass

        try:
            with open('/sys/class/drm/card0/device/gpu_busy_percent', 'r') as f:
                return float(f.read().strip())
        except Exception:
            pass

        return 0.0

    def get_host_gpu_temp(self) -> str:
        try:
            import subprocess
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                return f"{float(result.stdout.strip()):.0f}°C"
        except Exception:
            pass

        try:
            temps = psutil.sensors_temperatures()
            for sensor_name in ['i915', 'coretemp', 'pch_cannonlake']:
                if sensor_name in temps:
                    for entry in temps[sensor_name]:
                        if entry.label and any(x in entry.label.lower() for x in ['gpu', 'gt']):
                            return f"{entry.current:.0f}°C"
        except Exception:
            pass

        try:
            import glob
            for hwmon_path in glob.glob('/sys/class/drm/card0/hwmon/hwmon*/temp*_input'):
                with open(hwmon_path, 'r') as f:
                    temp_millidegrees = int(f.read().strip())
                    return f"{temp_millidegrees / 1000:.0f}°C"
        except Exception:
            pass

        try:
            import subprocess
            result = subprocess.run(['vcgencmd', 'measure_temp'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                temp_str = result.stdout.strip()
                temp_val = temp_str.split('=')[1].replace("'C", "")
                return f"{float(temp_val):.0f}°C"
        except Exception:
            pass

        try:
            temps = psutil.sensors_temperatures()
            for sensor_name in ['amdgpu', 'radeon']:
                if sensor_name in temps and temps[sensor_name]:
                    return f"{temps[sensor_name][0].current:.0f}°C"
        except Exception:
            pass

        return "N/A"

    def on_mount(self) -> None:
        self.set_interval(1, self.update_display)
        self.update_display()

    def update_display(self) -> None:
        from datetime import datetime

        cpu = self.get_host_cpu()
        ram = self.get_host_ram()
        temp = self.get_host_temp()
        gpu = self.get_host_gpu_usage()
        gpu_temp = self.get_host_gpu_temp()

        # 獲取當前時間（24小時制）
        current_time = datetime.now().strftime("%H:%M:%S")

        if cpu >= 75:
            cpu_color = "red"
        elif cpu >= 50:
            cpu_color = "yellow"
        else:
            cpu_color = "green"

        if gpu >= 75:
            gpu_color = "red"
        elif gpu >= 50:
            gpu_color = "yellow"
        else:
            gpu_color = "green"

        if ram >= 80:
            ram_color = "red"
        elif ram >= 60:
            ram_color = "yellow"
        else:
            ram_color = "green"

        temp_val = temp.replace("°C", "").strip()
        try:
            temp_num = float(temp_val)
            if temp_num >= 75:
                temp_color = "red"
            elif temp_num >= 65:
                temp_color = "yellow"
            else:
                temp_color = "cyan"
        except ValueError:
            temp_color = "dim"

        gpu_temp_val = gpu_temp.replace("°C", "").strip()
        try:
            gpu_temp_num = float(gpu_temp_val)
            if gpu_temp_num >= 75:
                gpu_temp_color = "red"
            elif gpu_temp_num >= 65:
                gpu_temp_color = "yellow"
            else:
                gpu_temp_color = "cyan"
        except ValueError:
            gpu_temp_color = "dim"

        # 建立滿版的 footer，左側為系統資訊，右側為時間
        if gpu_temp != "N/A":
            left_content = (
                f"C[{cpu_color}]{cpu:4.1f}%[/{cpu_color}][{temp_color}]{temp:>4}[/{temp_color}] "
                f"G[{gpu_temp_color}]{gpu_temp:>4}[/{gpu_temp_color}] "
                f"R[{ram_color}]{ram:4.1f}%[/{ram_color}]"
            )
        else:
            left_content = (
                f"CPU [{cpu_color}]{cpu:4.1f}%[/{cpu_color}] "
                f"RAM [{ram_color}]{ram:4.1f}%[/{ram_color}] "
                f"[{temp_color}]{temp}[/{temp_color}]"
            )

        # 使用終端寬度計算填充空白，讓時間靠右顯示
        try:
            # 嘗試獲取終端寬度
            import shutil
            term_width = shutil.get_terminal_size().columns - 2  # 減去 padding
            # 估算左側內容的可見字符長度（不含標記）
            import re
            visible_left = re.sub(r'\[.*?\]', '', left_content)
            left_len = len(visible_left)
            time_len = 8  # "HH:MM:SS" = 8 字符
            separator_len = 1  # "│"

            # 計算需要的空白數量
            spaces_needed = max(1, term_width - left_len - time_len - separator_len - 1)
            padding = " " * spaces_needed

            content = f"{left_content}{padding}[dim]│[/dim] [bold cyan]{current_time}[/bold cyan]"
        except:
            # 如果無法獲取終端寬度，使用固定填充
            content = f"{left_content}                                      [dim]│[/dim] [bold cyan]{current_time}[/bold cyan]"

        self.update(content)

class ClockDisplay(Static):
    """固定位置的時間顯示區域"""

    def on_mount(self) -> None:
        self.set_interval(1, self.update_time)
        self.update_time()

    def update_time(self) -> None:
        from datetime import datetime

        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_date = now.strftime("%Y-%m-%d")
        weekday = now.strftime("%A")

        # 建立時間顯示
        time_display = (
            f"[bold bright_cyan]Time[/bold bright_cyan] [bold bright_white]{current_time}[/bold bright_white]  "
            f"[bold bright_cyan]Date[/bold bright_cyan] [bold bright_white]{current_date}[/bold bright_white]  "
            f"[bold bright_cyan]Day[/bold bright_cyan] [bold bright_white]{weekday}[/bold bright_white]"
        )

        self.update(time_display)

class DeviceDisplay(Static):
    """
    Ultra-compact device widget as persistent Slot.
    host_id 可被重新指定，不做 mount/remove，避免閃爍。
    """

    device_data = reactive(None, layout=True)

    def __init__(self, slot_index: int) -> None:
        super().__init__()
        self.slot_index = slot_index
        self.host_id: Optional[str] = None
        self.last_update = 0.0
        # 改為純文字，藍底用 CSS 讓整條滿版
        self.title_label = Label("", id="title")
        self.stale_label = Label("", id="stale")
        self.metrics_label = Label("...", classes="metrics")
        self._stale = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="title-row"):
            yield self.title_label
            yield self.stale_label
        yield self.metrics_label

    def set_host(self, host_id: Optional[str], data: Optional[dict]) -> None:
        """Bind this slot to a host (or None to hide content)."""
        self.host_id = host_id
        if host_id is None:
            # 當沒有主機時，隱藏內容
            self.title_label.update("—")
            self.metrics_label.update(" ")
            self._set_stale(False)
            return

        self.title_label.update(host_id)
        if data:
            self.device_data = data  # 觸發 watch_device_data
        else:
            self.metrics_label.update("…")
            self._set_stale(True)

    def watch_device_data(self, data: dict) -> None:
        if not data:
            return
        self.last_update = time.time()

        cpu_percent = data.get("cpu", {}).get("percent_total", 0)
        ram_percent = data.get("memory", {}).get("ram", {}).get("percent", 0)

        gpu_temps = []
        gpus = data.get("gpus")
        if not gpus:
            g_item = data.get("gpu")
            if isinstance(g_item, list):
                gpus = g_item
            elif isinstance(g_item, dict):
                gpus = [g_item]
            else:
                gpus = []

        for g in gpus:
            if not isinstance(g, dict): continue
            val = g.get("temperature_celsius")
            gpu_temps.append(f"{val:.0f}°C" if val is not None else None)

        gpu_temp = gpu_temps[0] if gpu_temps else None

        cpu_temp = "N/A"
        temps = data.get("temperatures")
        if temps:
            for source, entries in temps.items():
                if any(k in source for k in ["cpu", "k10temp", "coretemp"]):
                    if entries:
                        temp_val = entries[0].get('current')
                        if isinstance(temp_val, (int, float)):
                            cpu_temp = f"{temp_val:.0f}°C"
                            break

        max_disk_temp = "N/A"
        if temps:
            disk_temps = []
            for source, entries in temps.items():
                if any(s in source for s in ["sd", "nvme", "mmcblk", "hd"]):
                    for entry in entries:
                        if isinstance(entry.get('current'), (int, float)):
                            disk_temps.append(entry['current'])
            if disk_temps:
                max_disk_temp = f"{max(disk_temps):.0f}°C"

        # 計算所有網卡中的最大上傳和下傳速度（分別計算）
        network_io = data.get("network_io", {})
        per_nic = network_io.get("per_nic", {})

        # 收集所有網卡的上傳和下傳速度
        upload_speeds = []
        download_speeds = []
        for nic_name, nic_data in per_nic.items():
            rate = nic_data.get("rate", {})
            upload_speeds.append(rate.get("tx_bytes_per_s", 0))
            download_speeds.append(rate.get("rx_bytes_per_s", 0))

        # 分別找出最大值
        net_up = max(upload_speeds) if upload_speeds else 0
        net_down = max(download_speeds) if download_speeds else 0

        disk_io = data.get("disk_io", {})
        total_read = sum(d.get("rate", {}).get("read_bytes_per_s", 0) for d in disk_io.values())
        total_write = sum(d.get("rate", {}).get("write_bytes_per_s", 0) for d in disk_io.values())

        cpu_color = self._get_usage_color(cpu_percent)
        ram_color = self._get_usage_color(ram_percent)
        cpu_temp_color = self._get_temp_color(cpu_temp)
        disk_temp_color = self._get_temp_color(max_disk_temp)

        gpu1_str = ""
        if gpu_temp is not None:
            c = self._get_temp_color(gpu_temp)
            gpu1_str = f" [bold yellow]GPU[/bold yellow][{c}]{gpu_temp:>5}[/{c}]"

        gpu2_str = ""
        if len(gpu_temps) > 1 and gpu_temps[1] is not None:
            g2_t = gpu_temps[1]
            c = self._get_temp_color(g2_t)
            # Align with GPU1 (CPU line width approx 15, RAM line width approx 10, diff 5)
            gpu2_str = f"     [bold yellow]GPU[/bold yellow][{c}]{g2_t:>5}[/{c}]"

        metrics_text = (
            f"[bold cyan]CPU[/bold cyan][{cpu_color}]{cpu_percent:5.1f}%[/{cpu_color}]"
            f"[{cpu_temp_color}]{cpu_temp:>5}[/{cpu_temp_color}]{gpu1_str}\n"
            f"[bold cyan]RAM[/bold cyan] [{ram_color}]{ram_percent:5.1f}%[/{ram_color}]{gpu2_str}\n"
            f"[bold green]NET[/bold green] ▲[yellow]{format_bytes(net_up):>7}[/yellow] "
            f"▼[#FF69B4]{format_bytes(net_down):>7}[/#FF69B4]\n"
            f"[bold magenta]DSK[/bold magenta] ◀[cyan]{format_bytes(total_read):>7}[/cyan] "
            f"▶[yellow]{format_bytes(total_write):>7}[/yellow] "
            f"[{disk_temp_color}]{max_disk_temp:>4}[/{disk_temp_color}]"
        )

        self.metrics_label.update(metrics_text)
        self._set_stale(False)

    def _get_usage_color(self, percent: float) -> str:
        if percent >= 90:
            return "red bold"
        elif percent >= 75:
            return "yellow"
        elif percent >= 50:
            return "green"
        else:
            return "bright_green"

    def _get_temp_color(self, temp: str) -> str:
        if temp == "N/A":
            return "dim"
        try:
            temp_val = float(temp.replace("°C", ""))
            if temp_val >= 80:
                return "red bold"
            elif temp_val >= 70:
                return "yellow"
            elif temp_val >= 60:
                return "green"
            else:
                return "cyan"
        except (ValueError, AttributeError):
            return "dim"

    def _set_stale(self, value: bool) -> None:
        if getattr(self, "_stale", False) == value:
            return
        self._stale = value
        if value:
            self.add_class("stale")
            self.stale_label.update("⚠")
        else:
            self.remove_class("stale")
            self.stale_label.update("")

    def check_staleness(self, now: float):
        if self.host_id and (now - self.last_update > STALE_SECONDS):
            self._set_stale(True)
        else:
            self._set_stale(False)


class MonitorApp(App):
    """Portrait-optimized hardware monitor for 3.5" 720x1280 display (No-Flicker + Sticky + Full-Width Title)."""

    CSS = """
    Screen { background: $surface; }

    #devices_container {
        layout: vertical;
        width: 100%;
        height: 1fr;
        padding: 0 1;
        overflow-y: hidden;   /* 無卷軸避免抖動 */
    }

    DeviceDisplay {
        border: solid $accent;
        background: $panel;
        height: auto;
        min-height: 7;
        padding: 0 0;         /* 與標題列平齊 */
        margin: 0;
    }

    /* ======= 滿版藍底標題列 ======= */
    .title-row {
        layout: horizontal;
        width: 100%;
        height: 1;                  /* 一行高 */
        padding: 0 1;               /* 左右 1 字元內距 */
        background: #1e66f5;        /* 藍底 */
        color: white;               /* 白字 */
    }
    .title-row Label {
        text-style: bold;
        color: white;
    }
    #title {
        width: 1fr;
        content-align: left middle;
    }
    #stale {
        width: auto;
        content-align: right middle;
    }

    /* stale 狀態時，整條標題列轉灰，字色變淡 */
    DeviceDisplay.stale .title-row {
        background: #404040;
        color: #cfcfcf;
    }
    DeviceDisplay.stale .title-row Label {
        color: #cfcfcf;
    }

    .metrics {
        height: auto;
        padding: 0 1;               /* 與標題列左右對齊 */
        margin: 0;
        content-align: left top;
    }

    Header { background: $accent-darken-2; }

    ClockDisplay {
        height: auto;
        width: 100%;
        padding: 1;
        content-align: center middle;
        background: $surface;
    }

    HostInfoFooter {
        background: #1e66f5;     /* 藍底與標題列一致 */
        color: white;            /* 白字 */
        dock: bottom;
        height: 1;
        width: 100%;
        content-align: left middle;   /* 預設左對齊，透過文字格式化來調整 */
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self):
        super().__init__()
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.all_devices_data = {}             # host -> last payload
        self.host_last_seen = {}               # host -> timestamp
        self.display_order: deque[str] = deque()
        self.current_page = 0

        # 上一頁的可見 hosts（用於不足 3 台時的「黏著式」行為）
        self.prev_visible_hosts: List[Optional[str]] = [None] * MAX_DEVICES_PER_PAGE

        # 固定 3 個槽位，永不 mount/remove
        self.slots: List[DeviceDisplay] = [DeviceDisplay(i) for i in range(MAX_DEVICES_PER_PAGE)]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="devices_container"):
            for slot in self.slots:
                yield slot
        yield ClockDisplay()
        yield HostInfoFooter()

    def on_mount(self) -> None:
        self.setup_mqtt()
        self.set_interval(ROTATION_INTERVAL_SECONDS, self.rotate_devices)
        self.set_interval(1, self.check_timeouts)
        self.update_slots()

    # ---------------- MQTT ----------------
    def setup_mqtt(self):
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
        try:
            self.mqtt_client.connect(BROKER_HOST, BROKER_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            self.notify(f"MQTT Error: {e}", severity="error")

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            client.subscribe(TOPIC)
            self.call_from_thread(self.notify, f"Connected: {TOPIC}")
        else:
            self.call_from_thread(self.notify, f"Connect failed: {rc}", severity="error")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            host = payload.get("host")
            if not host:
                return

            is_new = host not in self.all_devices_data
            self.all_devices_data[host] = payload
            self.host_last_seen[host] = time.time()

            if host not in self.display_order:
                self.display_order.append(host)
                is_new = True

            self.call_from_thread(self.update_slots)

            if is_new:
                self.call_from_thread(self.notify, f"Device discovered: {host}")

        except json.JSONDecodeError:
            self.call_from_thread(self.notify, "Bad JSON", severity="warning")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    # ---------------- 翻頁與槽位更新 ----------------
    def rotate_devices(self) -> None:
        num_devices = len(self.display_order)
        if num_devices == 0:
            self.current_page = 0
            self.update_slots()
            return

        if num_devices <= MAX_DEVICES_PER_PAGE:
            self.current_page = 0
        else:
            num_pages = (num_devices + MAX_DEVICES_PER_PAGE - 1) // MAX_DEVICES_PER_PAGE
            self.current_page = (self.current_page + 1) % num_pages

        self.update_slots()

    def _compute_visible_hosts(self) -> List[Optional[str]]:
        """計算這一頁應顯示的 hosts。
        - 一般：取該頁 slice（滿 3 台）
        - 不足 3 台：只更新前 N 個，剩餘沿用上一頁相同位置（黏著）
        """
        base = list(self.display_order)
        num_devices = len(base)

        if num_devices == 0:
            return [None] * MAX_DEVICES_PER_PAGE

        if num_devices <= MAX_DEVICES_PER_PAGE:
            vis = base + [None] * (MAX_DEVICES_PER_PAGE - len(base))
            return vis

        start_index = self.current_page * MAX_DEVICES_PER_PAGE
        end_index = start_index + MAX_DEVICES_PER_PAGE
        page_slice = base[start_index:end_index]  # 可能 < 3

        if len(page_slice) == MAX_DEVICES_PER_PAGE:
            return page_slice

        vis: List[Optional[str]] = [None] * MAX_DEVICES_PER_PAGE
        for i in range(len(page_slice)):
            vis[i] = page_slice[i]
        for i in range(len(page_slice), MAX_DEVICES_PER_PAGE):
            vis[i] = self.prev_visible_hosts[i] if self.prev_visible_hosts else None
        return vis

    def update_slots(self) -> None:
        visible_hosts = self._compute_visible_hosts()

        for i, slot in enumerate(self.slots):
            host = visible_hosts[i]
            data = self.all_devices_data.get(host) if host else None
            slot.set_host(host, data)

        # 更新上一頁快取（供下次不足時黏著使用）
        self.prev_visible_hosts = visible_hosts.copy()

    def check_timeouts(self) -> None:
        """檢查並移除超過 STALE_SECONDS 未更新的裝置"""
        now = time.time()
        to_remove = []

        # 找出超時的裝置
        for host, last_seen in self.host_last_seen.items():
            if now - last_seen > STALE_SECONDS:
                to_remove.append(host)

        if not to_remove:
            return

        # 執行移除
        changed = False
        for host in to_remove:
            if host in self.all_devices_data:
                del self.all_devices_data[host]
                del self.host_last_seen[host]
                if host in self.display_order:
                    self.display_order.remove(host)
                changed = True
                self.notify(f"Device removal: {host} (timeout)", severity="warning")

        if changed:
            self.update_slots()


if __name__ == "__main__":
    app = MonitorApp()
    app.run()
