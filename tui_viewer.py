#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HW Monitor MQTT TUI Viewer - Portrait Mode
- Powered by Textual
- Optimized for 3.5" 720x1280 display with 24x43 character grid
- Displays 3 devices per page (7 rows each) without scrolling
- Ultra-compact layout: zero margins, minimal padding
"""
import json
import os
import time
from collections import deque
from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, Container
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
# For 3.5" 720x1280 display with 24x43 character grid
MAX_DEVICES_PER_PAGE = 3  # Optimized for 3 devices in 43 rows
ROTATION_INTERVAL_SECONDS = 5

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
    """Custom footer showing host CPU and temperature."""

    def __init__(self) -> None:
        super().__init__()
        self.hostname = socket.gethostname()

    def get_host_temp(self) -> str:
        """Get Raspberry Pi CPU temperature."""
        try:
            temps = psutil.sensors_temperatures()
            # Raspberry Pi typically reports under 'cpu_thermal' or 'thermal_zone0'
            for sensor_name in ['cpu_thermal', 'thermal_zone0', 'cpu-thermal']:
                if sensor_name in temps and temps[sensor_name]:
                    return f"{temps[sensor_name][0].current:.0f}°C"
            # Fallback: try any available sensor
            for sensor_name, entries in temps.items():
                if entries:
                    return f"{entries[0].current:.0f}°C"
        except Exception:
            pass
        return "N/A"

    def get_host_cpu(self) -> float:
        """Get host CPU usage percentage."""
        try:
            return psutil.cpu_percent(interval=0)
        except Exception:
            return 0.0

    def get_host_ram(self) -> float:
        """Get host RAM usage percentage."""
        try:
            return psutil.virtual_memory().percent
        except Exception:
            return 0.0

    def get_host_gpu_usage(self) -> float:
        """Get GPU usage percentage."""
        try:
            # Try NVIDIA GPU first
            import subprocess
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass

        try:
            # Try Intel GPU (via sysfs)
            # Intel GPU usage can be found in /sys/class/drm/card0/gt/gt0/rps_cur_freq_mhz
            # or via intel_gpu_top if available
            import subprocess
            result = subprocess.run(['intel_gpu_top', '-o', '-', '-s', '100'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                # Parse intel_gpu_top output for render/3d usage
                for line in result.stdout.split('\n'):
                    if 'Render/3D' in line:
                        # Extract percentage from format like "Render/3D:  15.2%"
                        parts = line.split(':')
                        if len(parts) > 1:
                            pct = parts[1].strip().replace('%', '')
                            return float(pct)
        except Exception:
            pass

        try:
            # Try Intel GPU via sysfs (alternative method)
            # Read engine busy status
            with open('/sys/class/drm/card0/engine/rcs0/busy_percent', 'r') as f:
                return float(f.read().strip())
        except Exception:
            pass

        try:
            # Try AMD GPU (check sysfs)
            with open('/sys/class/drm/card0/device/gpu_busy_percent', 'r') as f:
                return float(f.read().strip())
        except Exception:
            pass

        return 0.0

    def get_host_gpu_temp(self) -> str:
        """Get GPU temperature."""
        try:
            # Try NVIDIA GPU first
            import subprocess
            result = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                return f"{float(result.stdout.strip()):.0f}°C"
        except Exception:
            pass

        try:
            # Try Intel GPU via sensors
            temps = psutil.sensors_temperatures()
            for sensor_name in ['i915', 'coretemp', 'pch_cannonlake']:
                if sensor_name in temps:
                    for entry in temps[sensor_name]:
                        # Look for GPU-related temperature labels
                        if entry.label and any(x in entry.label.lower() for x in ['gpu', 'gt']):
                            return f"{entry.current:.0f}°C"
        except Exception:
            pass

        try:
            # Try Intel GPU via sysfs hwmon
            import glob
            # Intel GPU temp can be found in /sys/class/drm/card0/hwmon/hwmon*/temp*_input
            for hwmon_path in glob.glob('/sys/class/drm/card0/hwmon/hwmon*/temp*_input'):
                with open(hwmon_path, 'r') as f:
                    temp_millidegrees = int(f.read().strip())
                    return f"{temp_millidegrees / 1000:.0f}°C"
        except Exception:
            pass

        try:
            # Try Raspberry Pi GPU
            import subprocess
            result = subprocess.run(['vcgencmd', 'measure_temp'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                temp_str = result.stdout.strip()
                # Output format: temp=45.0'C
                temp_val = temp_str.split('=')[1].replace("'C", "")
                return f"{float(temp_val):.0f}°C"
        except Exception:
            pass

        try:
            # Try AMD GPU via hwmon
            temps = psutil.sensors_temperatures()
            for sensor_name in ['amdgpu', 'radeon']:
                if sensor_name in temps and temps[sensor_name]:
                    return f"{temps[sensor_name][0].current:.0f}°C"
        except Exception:
            pass

        return "N/A"

    def on_mount(self) -> None:
        """Update footer periodically."""
        self.set_interval(1, self.update_display)
        self.update_display()

    def update_display(self) -> None:
        """Update footer content."""
        cpu = self.get_host_cpu()
        ram = self.get_host_ram()
        temp = self.get_host_temp()
        gpu = self.get_host_gpu_usage()
        gpu_temp = self.get_host_gpu_temp()

        # Color code based on CPU usage
        if cpu >= 75:
            cpu_color = "red"
        elif cpu >= 50:
            cpu_color = "yellow"
        else:
            cpu_color = "green"

        # Color code based on GPU usage
        if gpu >= 75:
            gpu_color = "red"
        elif gpu >= 50:
            gpu_color = "yellow"
        else:
            gpu_color = "green"

        # Color code based on RAM usage
        if ram >= 80:
            ram_color = "red"
        elif ram >= 60:
            ram_color = "yellow"
        else:
            ram_color = "green"

        # Color code based on CPU temperature
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

        # Color code based on GPU temperature
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

        # Compact layout: CPU/GPU on same level, minimal spacing
        if gpu_temp != "N/A":
            content = (
                f"C[{cpu_color}]{cpu:4.1f}%[/{cpu_color}][{temp_color}]{temp:>4}[/{temp_color}] "
                f"G[{gpu_temp_color}]{gpu_temp:>4}[/{gpu_temp_color}] "
                f"R[{ram_color}]{ram:4.1f}%[/{ram_color}]"
            )
        else:
            # No GPU detected, fall back to original layout
            content = (
                f"CPU [{cpu_color}]{cpu:4.1f}%[/{cpu_color}] "
                f"RAM [{ram_color}]{ram:4.1f}%[/{ram_color}] "
                f"[{temp_color}]{temp}[/{temp_color}]"
            )
        self.update(content)

class DeviceDisplay(Static):
    """Ultra-compact device widget for portrait displays."""

    device_data = reactive(None, layout=True)

    def __init__(self, host_id: str) -> None:
        super().__init__()
        self.host_id = host_id
        self.last_update = time.time()
        self.title_label = Label(f"[bold white on blue] {self.host_id} [/bold white on blue]")
        self.stale_label = Label("")
        self.metrics_label = Label("...")
        self._stale = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="title-row"):
            yield self.title_label
            yield self.stale_label
        yield self.metrics_label

    def watch_device_data(self, data: dict) -> None:
        if not data:
            return

        self.last_update = time.time()

        # --- Extract all metrics ---
        cpu_percent = data.get("cpu", {}).get("percent_total", 0)
        ram_percent = data.get("memory", {}).get("ram", {}).get("percent", 0)

        # GPU metrics
        gpu_data = data.get("gpu", {})
        gpu_percent = gpu_data.get("usage_percent") if gpu_data else None
        gpu_temp_val = gpu_data.get("temperature_celsius") if gpu_data else None
        gpu_temp = f"{gpu_temp_val:.0f}°C" if gpu_temp_val is not None else None

        # CPU Temperature
        cpu_temp = "N/A"
        if temps := data.get("temperatures"):
            for source, entries in temps.items():
                if any(k in source for k in ["cpu", "k10temp", "coretemp"]):
                    if entries:
                        temp_val = entries[0].get('current')
                        if isinstance(temp_val, (int, float)):
                            cpu_temp = f"{temp_val:.0f}°C"
                            break

        # Disk Temperature
        max_disk_temp = "N/A"
        if temps:
            disk_temps = []
            for source, entries in temps.items():
                if any(s in source for s in ["sd", "nvme", "mmcblk", "hd"]):
                    for entry in entries:
                        if isinstance(entry.get('current'), (int, float)):
                            disk_temps.append(entry['current'])
            if disk_temps:
                max_temp = max(disk_temps)
                max_disk_temp = f"{max_temp:.0f}°C"

        # Network IO
        net_total = data.get("network_io", {}).get("total", {}).get("rate", {})
        net_up = net_total.get("tx_bytes_per_s", 0)
        net_down = net_total.get("rx_bytes_per_s", 0)

        # Disk IO
        disk_io = data.get("disk_io", {})
        total_read = sum(d.get("rate", {}).get("read_bytes_per_s", 0) for d in disk_io.values())
        total_write = sum(d.get("rate", {}).get("write_bytes_per_s", 0) for d in disk_io.values())

        # --- Color Coding ---
        cpu_color = self._get_usage_color(cpu_percent)
        ram_color = self._get_usage_color(ram_percent)
        cpu_temp_color = self._get_temp_color(cpu_temp)
        disk_temp_color = self._get_temp_color(max_disk_temp)

        # --- Compact Format for 24x43 Display (3 devices) ---
        # Row budget: ~12 rows per device (43 rows - 2 header/footer = 41 / 3 ≈ 13)

        # Build CPU/GPU line (compact if GPU exists)
        if gpu_temp is not None:
            gpu_temp_color = self._get_temp_color(gpu_temp)
            gpu_tmp_str = f"{gpu_temp:>5}"

            metrics_text = (
                f"[bold cyan]CPU[/bold cyan][{cpu_color}]{cpu_percent:5.1f}%[/{cpu_color}]"
                f"[{cpu_temp_color}]{cpu_temp:>5}[/{cpu_temp_color}] "
                f"[bold yellow]GPU[/bold yellow]"
                f"[{gpu_temp_color}]{gpu_tmp_str}[/{gpu_temp_color}]\n"
                f"[bold cyan]RAM[/bold cyan] [{ram_color}]{ram_percent:5.1f}%[/{ram_color}]\n"
                f"[bold green]NET[/bold green] ▲[yellow]{format_bytes(net_up):>7}[/yellow] "
                f"▼[blue]{format_bytes(net_down):>7}[/blue]\n"
                f"[bold magenta]DSK[/bold magenta] ◀[cyan]{format_bytes(total_read):>7}[/cyan] "
                f"▶[yellow]{format_bytes(total_write):>7}[/yellow] "
                f"[{disk_temp_color}]{max_disk_temp:>4}[/{disk_temp_color}]"
            )
        else:
            # No GPU, use original layout
            metrics_text = (
                f"[bold cyan]CPU[/bold cyan] [{cpu_color}]{cpu_percent:5.1f}%[/{cpu_color}] "
                f"[{cpu_temp_color}]{cpu_temp:>5}[/{cpu_temp_color}]\n"
                f"[bold cyan]RAM[/bold cyan] [{ram_color}]{ram_percent:5.1f}%[/{ram_color}]\n"
                f"[bold green]NET[/bold green] ▲[yellow]{format_bytes(net_up):>7}[/yellow] "
                f"▼[blue]{format_bytes(net_down):>7}[/blue]\n"
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
        """Toggle stale visual state."""
        if self._stale == value:
            return
        self._stale = value
        if value:
            self.add_class("stale")
            self.stale_label.update("[bold yellow on black]⚠[/bold yellow on black]")
        else:
            self.remove_class("stale")
            self.stale_label.update("")

    def check_staleness(self, now: float):
        if now - self.last_update > 10:
            self._set_stale(True)
        else:
            self._set_stale(False)


class MonitorApp(App):
    """Portrait-optimized hardware monitor for 3.5" 720x1280 display."""

    CSS = """
    /* Optimized for 24x43 character grid (3.5" display) */

    Screen {
        background: $surface;
    }

    #devices_container {
        layout: vertical;
        width: 100%;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    DeviceDisplay {
        border: solid $accent;
        background: $panel;
        height: auto;
        min-height: 7;
        padding: 0 1;
        margin: 0;
    }

    DeviceDisplay Label {
        text-style: bold;
    }

    DeviceDisplay.stale {
        background: #202020;
        color: #808080;
    }

    DeviceDisplay.stale Label {
        color: #808080;
    }

    .title-row {
        layout: horizontal;
        height: auto;
        width: 100%;
        padding-bottom: 0;
    }

    .title-row Label {
        text-style: bold;
    }

    #title {
        width: 1fr;
        content-align: left middle;
    }

    #stale {
        width: auto;
        content-align: right middle;
    }

    .metrics {
        height: auto;
        padding: 0;
        margin: 0;
        content-align: left top;
    }

    Header {
        background: $accent-darken-2;
    }

    HostInfoFooter {
        background: $accent-darken-2;
        dock: bottom;
        height: 1;
        content-align: right middle;
        padding: 0 1;
    }
    """

    def __init__(self):
        super().__init__()
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.all_devices_data = {}
        self.device_widgets = {}
        self.display_order = deque()
        self.current_page = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(id="devices_container")
        yield HostInfoFooter()

    def on_mount(self) -> None:
        self.setup_mqtt()
        self.set_interval(ROTATION_INTERVAL_SECONDS, self.rotate_devices)
        self.set_interval(5, self.check_stale_status)

    def setup_mqtt(self):
        """Configure and connect the MQTT client."""
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

            self.all_devices_data[host] = payload

            if host not in self.device_widgets:
                new_widget = DeviceDisplay(host_id=host)
                self.device_widgets[host] = new_widget
                self.display_order.append(host)
                self.call_from_thread(self.notify, f"Device: {host}")

            self.call_from_thread(self.update_widget_data, host)

        except json.JSONDecodeError:
            self.call_from_thread(self.notify, "Bad JSON", severity="warning")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {e}", severity="error")

    def update_widget_data(self, host: str):
        if host in self.device_widgets and host in self.all_devices_data:
            widget = self.device_widgets[host]
            widget.device_data = self.all_devices_data[host]
            self.update_display()

    def rotate_devices(self) -> None:
        num_devices = len(self.display_order)
        if num_devices <= MAX_DEVICES_PER_PAGE:
            self.current_page = 0
            return

        num_pages = (num_devices + MAX_DEVICES_PER_PAGE - 1) // MAX_DEVICES_PER_PAGE
        self.current_page = (self.current_page + 1) % num_pages
        self.update_display()

    def update_display(self) -> None:
        container = self.query_one("#devices_container")

        start_index = self.current_page * MAX_DEVICES_PER_PAGE
        end_index = start_index + MAX_DEVICES_PER_PAGE

        visible_hosts = [self.display_order[i] for i in range(len(self.display_order)) if start_index <= i < end_index]

        current_widgets = {child.host_id: child for child in container.children if isinstance(child, DeviceDisplay)}

        for host_id, widget in current_widgets.items():
            if host_id not in visible_hosts:
                widget.remove()

        for host_id in visible_hosts:
            if host_id not in current_widgets:
                container.mount(self.device_widgets[host_id])

    def check_stale_status(self) -> None:
        now = time.time()
        for widget in self.device_widgets.values():
            widget.check_staleness(now)


if __name__ == "__main__":
    app = MonitorApp()
    app.run()
