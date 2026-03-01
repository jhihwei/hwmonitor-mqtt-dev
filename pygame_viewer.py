#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HW Monitor PyGame Viewer (Raspberry Ubuntu ARM friendly)."""

from __future__ import annotations

import json
import math
import os
import time
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import paho.mqtt.client as mqtt
import psutil
import pygame
from dotenv import load_dotenv

load_dotenv()

# --- MQTT ---
BROKER_HOST = os.getenv("BROKER_HOST", "192.168.5.33")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
TOPIC = "sys/agents/+/metrics"
MQTT_USER = os.getenv("MQTT_USER", "mqtter")
MQTT_PASS = os.getenv("MQTT_PASS", "seven777")

# --- UI / Runtime ---
DEFAULT_WIDTH = int(os.getenv("PYGAME_WIDTH", "320"))
DEFAULT_HEIGHT = int(os.getenv("PYGAME_HEIGHT", "480"))
FPS = int(os.getenv("PYGAME_FPS", "10"))
MAX_CARDS_PER_PAGE = 3
PAGE_INTERVAL_SECONDS = int(os.getenv("PYGAME_PAGE_INTERVAL", "15"))
STALE_SECONDS = int(os.getenv("PYGAME_STALE_SECONDS", "10"))
PURGE_SECONDS = int(os.getenv("PYGAME_PURGE_SECONDS", "300"))
MAX_TRACKED_DEVICES = int(os.getenv("PYGAME_MAX_TRACKED_DEVICES", "24"))
ANIMATE_UI = os.getenv("PYGAME_ANIMATE_UI", "1") == "1"
FORCE_PORTRAIT = os.getenv("PYGAME_FORCE_PORTRAIT", "1") == "1"
PORTRAIT_ROTATE_DEGREE = int(os.getenv("PYGAME_PORTRAIT_ROTATE_DEGREE", "90"))

# --- Colors ---
C_BG = (10, 15, 30)
C_CARD = (22, 32, 48)
C_CARD_STALE = (60, 38, 45)
C_TEXT = (248, 250, 252)
C_DIM = (148, 163, 184)
C_ACCENT = (56, 189, 248)
C_ACCENT_DARK = (14, 116, 144)
C_CPU = (52, 211, 153)
C_RAM = (167, 139, 250)
C_GPU = (249, 115, 22)
C_WARN = (250, 204, 21)
C_CRIT = (248, 113, 113)
C_DISK = (59, 130, 246)


def format_bytes_short(byte_count: float) -> str:
    """Format byte/s into compact units."""
    if not byte_count:
        return "0B"
    power = 1024.0
    units = ["B", "K", "M", "G", "T"]
    value = float(byte_count)
    idx = 0
    while value >= power and idx < len(units) - 1:
        value /= power
        idx += 1
    if value >= 10:
        return f"{int(value)}{units[idx]}"
    return f"{value:.1f}{units[idx]}"


def pick_temp_color(temp_c: Optional[float], base: Tuple[int, int, int] = C_TEXT) -> Tuple[int, int, int]:
    """Pick warning color from temperature."""
    if temp_c is None:
        return C_DIM
    if temp_c >= 100:
        return (255, 0, 0) # Extremely critical
    if temp_c >= 90:
        return C_CRIT
    if temp_c >= 75:
        return C_WARN
    if temp_c >= 60:
        return (220, 180, 80) # Elevated Orange
    return base


def pick_usage_color(percent: float, base: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Pick warning color from usage percent."""
    if percent >= 90.0:
        return C_CRIT
    if percent >= 80.0:
        return C_WARN
    return base


def fit_text(font: pygame.font.Font, text: str, max_width: int) -> str:
    """Ellipsize text by pixel width."""
    if max_width <= 0:
        return ""
    if font.size(text)[0] <= max_width:
        return text
    ellipsis = "…"
    if font.size(ellipsis)[0] > max_width:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid] + ellipsis
        if font.size(candidate)[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ellipsis


def extract_gpu_temps(payload: Dict[str, Any]) -> List[float]:
    """Extract up to two GPU temps from payload."""
    gpus = payload.get("gpus")
    if not gpus:
        gpu_item = payload.get("gpu")
        if isinstance(gpu_item, list):
            gpus = gpu_item
        elif isinstance(gpu_item, dict):
            gpus = [gpu_item]
        else:
            gpus = []

    temps: List[float] = []
    for item in gpus:
        if not isinstance(item, dict):
            continue
        val = item.get("temperature_celsius")
        if isinstance(val, (int, float)):
            temps.append(float(val))
    return temps[:2]


def extract_gpu_percent(payload: Dict[str, Any]) -> float:
    """Extract max GPU percent from payload."""
    gpus = payload.get("gpus")
    if not gpus:
        gpu_item = payload.get("gpu")
        gpus = gpu_item if isinstance(gpu_item, list) else ([gpu_item] if isinstance(gpu_item, dict) else [])
    
    loads = []
    for item in gpus:
        if not isinstance(item, dict):
            continue
        for key in ("load_percent", "percent", "utilization", "gpu_percent"):
            val = item.get(key)
            if isinstance(val, (int, float)):
                loads.append(float(val))
                break
    return max(loads) if loads else 0.0


def extract_cpu_temp(temps_block: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract CPU temperature from temperature block."""
    if not temps_block:
        return None
    for source, entries in temps_block.items():
        if not any(k in str(source).lower() for k in ("cpu", "k10temp", "coretemp")):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            cur = entry.get("current") if isinstance(entry, dict) else None
            if isinstance(cur, (int, float)):
                return float(cur)
    return None


def extract_disk_temp(temps_block: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract max disk temperature from temperature block."""
    if not temps_block:
        return None
    disk_temps: List[float] = []
    for source, entries in temps_block.items():
        source_name = str(source).lower()
        if not any(k in source_name for k in ("sd", "nvme", "mmcblk", "hd", "vd")):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            cur = entry.get("current") if isinstance(entry, dict) else None
            if isinstance(cur, (int, float)):
                disk_temps.append(float(cur))
    return max(disk_temps) if disk_temps else None


def extract_network_rates(network_io: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    """Extract max upload/download rate among NICs."""
    if not network_io:
        return 0.0, 0.0
    per_nic = network_io.get("per_nic", {})
    if not isinstance(per_nic, dict):
        total = network_io.get("total", {}).get("rate", {})
        return (
            float(total.get("tx_bytes_per_s", 0.0) or 0.0),
            float(total.get("rx_bytes_per_s", 0.0) or 0.0),
        )

    max_up = 0.0
    max_down = 0.0
    for nic_data in per_nic.values():
        if not isinstance(nic_data, dict):
            continue
        rate = nic_data.get("rate", {})
        max_up = max(max_up, float(rate.get("tx_bytes_per_s", 0.0) or 0.0))
        max_down = max(max_down, float(rate.get("rx_bytes_per_s", 0.0) or 0.0))
    return max_up, max_down


def extract_disk_rates(disk_io: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    """Extract summed disk read/write rate."""
    if not isinstance(disk_io, dict):
        return 0.0, 0.0
    read = 0.0
    write = 0.0
    for dev in disk_io.values():
        if not isinstance(dev, dict):
            continue
        rate = dev.get("rate", {})
        read += float(rate.get("read_bytes_per_s", 0.0) or 0.0)
        write += float(rate.get("write_bytes_per_s", 0.0) or 0.0)
    return read, write


def format_temp(temp_c: Optional[float]) -> str:
    """Format temperature."""
    if temp_c is None:
        return "NA"
    return f"{temp_c:.0f}°"


def extract_primary_gpu_temp(gpu_temps: Sequence[float]) -> Optional[float]:
    """Pick primary GPU temperature for compact render."""
    if not gpu_temps:
        return None
    return max(float(temp) for temp in gpu_temps)


def temp_to_percent(temp_c: Optional[float], max_temp: float = 95.0) -> float:
    """Convert temperature to 0..100 percent scale."""
    if temp_c is None:
        return 0.0
    safe_max = max(1.0, max_temp)
    ratio = max(0.0, min(1.0, float(temp_c) / safe_max))
    return ratio * 100.0


def clamp_int(value: int, low: int, high: int) -> int:
    """Clamp integer into [low, high]."""
    return max(low, min(high, value))


def scale_color(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    """Scale RGB color with clamp."""
    return tuple(clamp_int(int(channel * factor), 0, 255) for channel in color)


def sort_hosts_for_display(hosts: Sequence[str]) -> List[str]:
    """Return stable host order for page rendering."""
    return sorted(hosts, key=lambda host: (host.casefold(), host))


def compute_visible_hosts_sticky(
    hosts: Sequence[str],
    page_index: int,
    prev_visible_hosts: Sequence[Optional[str]],
    per_page: int = MAX_CARDS_PER_PAGE,
) -> List[Optional[str]]:
    """Return fixed-size visible host list with sticky fallback for last partial page."""
    if not hosts:
        return [None] * per_page

    host_count = len(hosts)
    if host_count <= per_page:
        return list(hosts) + [None] * (per_page - host_count)

    page_count = max(1, math.ceil(host_count / per_page))
    page_index = max(0, min(page_index, page_count - 1))
    start = page_index * per_page
    page_hosts = list(hosts[start : start + per_page])

    if len(page_hosts) == per_page:
        return page_hosts

    visible = page_hosts.copy()
    prev = list(prev_visible_hosts)[:per_page]
    while len(prev) < per_page:
        prev.append(None)

    for slot in range(len(page_hosts), per_page):
        candidate = prev[slot]
        if candidate and candidate in hosts and candidate not in visible:
            visible.append(candidate)
            continue
        fallback = next((h for h in hosts if h not in visible), None)
        visible.append(fallback)

    return visible[:per_page]


@dataclass(frozen=True)
class DeviceView:
    """Immutable snapshot used by renderer."""

    host: str
    cpu_percent: float
    ram_percent: float
    gpu_percent: float
    cpu_temp_c: Optional[float]
    gpu_temps_c: Tuple[float, ...]
    net_up_bps: float
    net_down_bps: float
    disk_read_bps: float
    disk_write_bps: float
    disk_temp_c: Optional[float]
    cpu_hist: Tuple[float, ...]
    ram_hist: Tuple[float, ...]
    cpu_temp_hist: Tuple[float, ...]
    gpu_temp_hist: Tuple[float, ...]
    last_seen_ts: float


@dataclass
class DeviceState:
    """Mutable runtime state for each host."""

    host: str
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    gpu_percent: float = 0.0
    cpu_temp_c: Optional[float] = None
    gpu_temps_c: Tuple[float, ...] = ()
    net_up_bps: float = 0.0
    net_down_bps: float = 0.0
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0
    disk_temp_c: Optional[float] = None
    cpu_hist: Deque[float] = field(default_factory=lambda: deque([0.0] * 30, maxlen=60))
    ram_hist: Deque[float] = field(default_factory=lambda: deque([0.0] * 30, maxlen=60))
    cpu_temp_hist: Deque[float] = field(default_factory=lambda: deque([0.0] * 30, maxlen=60))
    gpu_temp_hist: Deque[float] = field(default_factory=lambda: deque([0.0] * 30, maxlen=60))
    last_seen_ts: float = 0.0


class DataStore:
    """Thread-safe metrics store."""

    def __init__(self) -> None:
        self._devices: OrderedDict[str, DeviceState] = OrderedDict()
        self._lock = threading.Lock()
        self._version = 0

    def update_from_payload(self, payload: Dict[str, Any]) -> None:
        """Update host state from raw payload."""
        host = payload.get("host") or payload.get("device_id")
        if not host:
            return

        cpu_percent = float(payload.get("cpu", {}).get("percent_total", 0.0) or 0.0)
        ram_percent = float(payload.get("memory", {}).get("ram", {}).get("percent", 0.0) or 0.0)
        temps = payload.get("temperatures")
        cpu_temp = extract_cpu_temp(temps)
        disk_temp = extract_disk_temp(temps)
        gpu_temps = tuple(extract_gpu_temps(payload))
        gpu_temp_peak = extract_primary_gpu_temp(gpu_temps)
        gpu_percent = extract_gpu_percent(payload)
        net_up, net_down = extract_network_rates(payload.get("network_io"))
        disk_read, disk_write = extract_disk_rates(payload.get("disk_io"))
        now = time.time()

        with self._lock:
            state = self._devices.get(host)
            if state is None:
                state = DeviceState(host=host)
                self._devices[host] = state

            state.cpu_percent = cpu_percent
            state.ram_percent = ram_percent
            state.gpu_percent = gpu_percent
            state.cpu_temp_c = cpu_temp
            state.gpu_temps_c = gpu_temps
            state.net_up_bps = net_up
            state.net_down_bps = net_down
            state.disk_read_bps = disk_read
            state.disk_write_bps = disk_write
            state.disk_temp_c = disk_temp
            state.last_seen_ts = now
            state.cpu_hist.append(cpu_percent)
            state.ram_hist.append(ram_percent)
            state.cpu_temp_hist.append(cpu_temp if cpu_temp is not None else 0.0)
            state.gpu_temp_hist.append(gpu_temp_peak if gpu_temp_peak is not None else 0.0)

            while len(self._devices) > MAX_TRACKED_DEVICES:
                self._devices.popitem(last=False)

            self._version += 1

    def purge_old(self, now: float) -> bool:
        """Remove devices that have been missing for too long."""
        changed = False
        with self._lock:
            remove_hosts = [
                host
                for host, state in self._devices.items()
                if now - state.last_seen_ts > PURGE_SECONDS
            ]
            for host in remove_hosts:
                self._devices.pop(host, None)
                changed = True
            if changed:
                self._version += 1
        return changed

    def snapshot(self) -> Tuple[List[DeviceView], int]:
        """Return immutable snapshot + version."""
        with self._lock:
            views = [
                DeviceView(
                    host=state.host,
                    cpu_percent=state.cpu_percent,
                    ram_percent=state.ram_percent,
                    gpu_percent=state.gpu_percent,
                    cpu_temp_c=state.cpu_temp_c,
                    gpu_temps_c=state.gpu_temps_c,
                    net_up_bps=state.net_up_bps,
                    net_down_bps=state.net_down_bps,
                    disk_read_bps=state.disk_read_bps,
                    disk_write_bps=state.disk_write_bps,
                    disk_temp_c=state.disk_temp_c,
                    cpu_hist=tuple(state.cpu_hist),
                    ram_hist=tuple(state.ram_hist),
                    cpu_temp_hist=tuple(state.cpu_temp_hist),
                    gpu_temp_hist=tuple(state.gpu_temp_hist),
                    last_seen_ts=state.last_seen_ts,
                )
                for state in self._devices.values()
            ]
            return views, self._version


def paginate_devices(
    devices: Sequence[DeviceView], page_index: int, per_page: int = MAX_CARDS_PER_PAGE
) -> Tuple[List[Optional[DeviceView]], int, int]:
    """Slice devices into fixed-size page slots."""
    if not devices:
        return [None] * per_page, 1, 0
    page_count = max(1, math.ceil(len(devices) / per_page))
    page_index = max(0, min(page_index, page_count - 1))
    start = page_index * per_page
    current = list(devices[start : start + per_page])
    if len(current) < per_page:
        current.extend([None] * (per_page - len(current)))
    return current, page_count, page_index


def get_host_temp() -> Optional[float]:
    """Get local host temp (best effort)."""
    try:
        temps = psutil.sensors_temperatures()
        for sensor_name in ("cpu_thermal", "thermal_zone0", "cpu-thermal"):
            if sensor_name in temps and temps[sensor_name]:
                return float(temps[sensor_name][0].current)
        for entries in temps.values():
            if entries and isinstance(entries[0].current, (int, float)):
                return float(entries[0].current)
    except Exception:
        return None
    return None


def draw_sparkline(
    surface: pygame.Surface,
    values: Iterable[float],
    color: Tuple[int, int, int],
    rect: pygame.Rect,
    max_val: float = 100.0,
    phase: float = 0.0,
) -> None:
    """Draw sparkline as a smooth area chart."""
    data = list(values)
    if len(data) < 2 or rect.width <= 2 or rect.height <= 2:
        return
    
    # Background
    pygame.draw.rect(surface, (20, 28, 45), rect, border_radius=4)
    
    # Faint horizontal grid lines
    grid_color = (36, 48, 70)
    for pct in (0.25, 0.5, 0.75):
        y = rect.y + int(rect.height * pct)
        pygame.draw.line(surface, grid_color, (rect.x, y), (rect.right, y))

    max_val = float(max_val)
    step_x = rect.width / max(1, len(data) - 1)
    points: List[Tuple[float, float]] = []
    for idx, val in enumerate(data):
        clamped = max(0.0, min(max_val, float(val)))
        px = rect.x + idx * step_x
        py = rect.y + rect.height - (clamped / max_val * rect.height)
        points.append((px, py))

    # Filled Area
    fill_points = [(rect.x, rect.bottom), *points, (rect.right, rect.bottom)]
    if len(fill_points) > 2:
        pygame.draw.polygon(surface, scale_color(color, 0.25), fill_points)
        
    # Antialiased curve
    if len(points) >= 2:
        pygame.draw.aalines(surface, color, False, points)

    # Pulse 
    pulse_radius = 2 + int((math.sin(phase * math.tau) + 1.0) * 1.5)
    last_x, last_y = points[-1]
    pygame.draw.circle(surface, scale_color(color, 1.2), (int(last_x), int(last_y)), pulse_radius)

    sweep_ratio = phase % 1.0
    sweep_x = rect.x + int(sweep_ratio * max(1, rect.width - 1))
    pygame.draw.line(surface, scale_color(color, 1.1), (sweep_x, rect.y + 1), (sweep_x, rect.bottom - 1), 1)


def draw_arc_gauge(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    value_text: str,
    percent: float,
    color: Tuple[int, int, int],
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    thickness: int = 6,
    missing: bool = False,
) -> None:
    """Draw circular arc gauge (supersampling for antialiasing thick rings)."""
    if rect.width <= 4 or rect.height <= 4:
        return

    center = rect.center
    radius = min(rect.width, rect.height) // 2 - thickness // 2
    bg_color = C_DIM if missing else (32, 45, 66)
    
    # Base circle
    pygame.draw.circle(surface, bg_color, center, radius, thickness)
    
    if not missing and percent > 0:
        ratio = max(0.0, min(1.0, percent / 100.0))
        angle = ratio * 2 * math.pi
        start_angle = math.pi / 2 - angle
        
        steps = max(10, int(angle * 12))
        if steps > 0:
            # Draw adjacent antialiased lines for thickness
            for off in range(-thickness//2, thickness//2 + 1):
                points = []
                r = radius + off
                if r <= 0: continue
                for i in range(steps + 1):
                    theta = start_angle + i * (angle / steps)
                    x = center[0] + r * math.cos(theta)
                    y = center[1] - r * math.sin(theta)
                    points.append((x, y))
                if len(points) > 1:
                    pygame.draw.aalines(surface, scale_color(color, 1.1), False, points)

    text_color = C_DIM if missing else C_TEXT
    val_sur = font.render(value_text, True, text_color)
    lbl_sur = font_small.render(label, True, text_color)
    
    val_y = center[1] - val_sur.get_height() // 2 - 2
    lbl_y = center[1] + val_sur.get_height() // 2 - 2
    
    if val_sur.get_height() + lbl_sur.get_height() > rect.height * 0.95:
        surface.blit(val_sur, (center[0] - val_sur.get_width() // 2, center[1] - val_sur.get_height() // 2))
    else:
        surface.blit(val_sur, (center[0] - val_sur.get_width() // 2, val_y))
        surface.blit(lbl_sur, (center[0] - lbl_sur.get_width() // 2, lbl_y))


def get_video_driver_candidates() -> List[Optional[str]]:
    """Pick suitable SDL video drivers for environment."""
    env_driver = os.getenv("SDL_VIDEODRIVER")
    if os.getenv("DISPLAY"):
        # Desktop session: prefer system default.
        candidates: List[Optional[str]] = [None, "wayland", "x11"]
    else:
        # Console session (Raspberry/ARM): prefer kmsdrm by default.
        candidates = ["kmsdrm", "fbcon", None, "wayland", "x11"]

    if env_driver:
        candidates = [env_driver, *candidates]

    deduped: List[Optional[str]] = []
    seen = set()
    for driver in candidates:
        if driver in seen:
            continue
        seen.add(driver)
        deduped.append(driver)
    return deduped


def compute_logical_view(
    physical_size: Tuple[int, int],
    force_portrait: bool = FORCE_PORTRAIT,
) -> Tuple[Tuple[int, int], bool]:
    """Return logical render size and whether output rotation is required."""
    width, height = physical_size
    if force_portrait and width > height:
        return (height, width), True
    return (width, height), False


def init_display() -> Tuple[pygame.Surface, str]:
    """Initialize pygame display with backend fallback."""
    os.environ.setdefault("SDL_VIDEO_DOUBLE_BUFFER", "1")
    os.environ.setdefault("SDL_KMSDRM_REQUIRE_DRM_MASTER", "1")
    if not os.getenv("DISPLAY"):
        os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

    user_fullscreen = os.getenv("PYGAME_FULLSCREEN")
    fullscreen = user_fullscreen == "1" if user_fullscreen is not None else not bool(os.getenv("DISPLAY"))
    flags = pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE
    size = (0, 0) if fullscreen else (DEFAULT_WIDTH, DEFAULT_HEIGHT)

    errors: List[str] = []
    candidates = get_video_driver_candidates()
    for driver in candidates:
        if driver is None:
            os.environ.pop("SDL_VIDEODRIVER", None)
        else:
            os.environ["SDL_VIDEODRIVER"] = driver
        try:
            pygame.display.quit()
            pygame.display.init()
            screen = pygame.display.set_mode(size, flags)
            return screen, pygame.display.get_driver()
        except pygame.error as exc:
            errors.append(f"{driver or 'auto'}: {exc}")

    raise RuntimeError("Display init failed: " + " | ".join(errors))


def connect_mqtt(store: DataStore) -> mqtt.Client:
    """Create and connect mqtt client."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(m_client, _userdata, _flags, rc, _properties=None):
        if rc == 0:
            m_client.subscribe(TOPIC)
            print(f"[MQTT] Connected, subscribed: {TOPIC}")
        else:
            print(f"[MQTT] Connect failed rc={rc}")

    def on_message(_client, _userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            store.update_from_payload(payload)
        except Exception as exc:
            print(f"[MQTT] Message parse error: {exc}")

    client.on_connect = on_connect
    client.on_message = on_message
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    try:
        client.connect(BROKER_HOST, BROKER_PORT, 60)
        client.loop_start()
    except Exception as exc:
        print(f"[MQTT] Connect exception: {exc}")
    return client


def main() -> None:
    """Run pygame hardware monitor."""
    pygame.init()
    pygame.font.init()

    screen, driver_name = init_display()
    logical_size, rotate_output = compute_logical_view(screen.get_size(), FORCE_PORTRAIT)
    backbuffer = pygame.Surface(logical_size).convert()
    clock = pygame.time.Clock()

    font_top = pygame.font.SysFont("dejavusansmono", 18, bold=True)
    font_title = pygame.font.SysFont("dejavusansmono", 22, bold=True)
    font_main = pygame.font.SysFont("dejavusansmono", 18)
    font_small = pygame.font.SysFont("dejavusansmono", 14)
    font_footer = pygame.font.SysFont("dejavusansmono", 20, bold=True)
    font_cache_key: Optional[Tuple[int, int, int, int, int]] = None

    store = DataStore()
    mqtt_client = connect_mqtt(store)

    page_index = 0
    last_page_rotate = time.time()
    last_second = -1
    last_store_version = -1
    prev_visible_hosts: List[Optional[str]] = [None] * MAX_CARDS_PER_PAGE
    running = True

    print(
        f"[Display] driver={driver_name}, physical={screen.get_size()}, logical={logical_size}, "
        f"rotate={rotate_output}, fullscreen={bool(screen.get_flags() & pygame.FULLSCREEN)}"
    )

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                logical_size, rotate_output = compute_logical_view(screen.get_size(), FORCE_PORTRAIT)
                backbuffer = pygame.Surface(logical_size).convert()
                last_store_version = -1

        now = time.time()
        second_now = int(now)
        second_changed = second_now != last_second
        if second_changed:
            last_second = second_now
            store.purge_old(now)

        devices, version = store.snapshot()
        page_count = max(1, math.ceil(len(devices) / MAX_CARDS_PER_PAGE)) if devices else 1
        if now - last_page_rotate >= PAGE_INTERVAL_SECONDS:
            page_index = (page_index + 1) % page_count
            last_page_rotate = now

        _, page_count, page_index = paginate_devices(devices, page_index)
        host_to_view = {device.host: device for device in devices}
        current_hosts = sort_hosts_for_display([device.host for device in devices])
        visible_hosts = compute_visible_hosts_sticky(
            hosts=current_hosts,
            page_index=page_index,
            prev_visible_hosts=prev_visible_hosts,
            per_page=MAX_CARDS_PER_PAGE,
        )
        devices_for_cards: List[Optional[DeviceView]] = [host_to_view.get(host) if host else None for host in visible_hosts]
        prev_visible_hosts = visible_hosts.copy()
        active_count = sum(1 for device in devices_for_cards if device is not None)

        animate_this_frame = ANIMATE_UI and active_count > 0
        redraw_cards = animate_this_frame or second_changed or version != last_store_version
        redraw_top = animate_this_frame or second_changed or redraw_cards
        redraw_footer = second_changed or version != last_store_version
        last_store_version = version

        width, height = backbuffer.get_size()
        title_size = clamp_int(height // 13, 28, 42)
        main_size = clamp_int(height // 20, 22, 30)
        small_size = clamp_int(height // 22, 20, 30)
        top_size = clamp_int(height // 21, 18, 30)
        footer_size = small_size  # 資訊文字size 和 底部bar 一樣

        current_font_key = (top_size, title_size, main_size, small_size, footer_size)
        if current_font_key != font_cache_key:
            font_top = pygame.font.SysFont("dejavusansmono", top_size, bold=True)
            font_title = pygame.font.SysFont("dejavusansmono", title_size, bold=True)
            font_main = pygame.font.SysFont("dejavusansmono", main_size)
            font_small = pygame.font.SysFont("dejavusansmono", small_size)
            font_footer = pygame.font.SysFont("dejavusansmono", footer_size, bold=True)
            font_cache_key = current_font_key
            redraw_top = True
            redraw_cards = True
            redraw_footer = True

        margin = max(8, width // 42)
        top_h = font_top.get_height() + 12
        footer_h = font_footer.get_height() + 10
        gap = max(6, height // 100)
        content_top = top_h + margin
        content_bottom = height - footer_h - margin
        content_h = max(1, content_bottom - content_top - gap * (MAX_CARDS_PER_PAGE - 1))
        card_h = max(90, content_h // MAX_CARDS_PER_PAGE)

        top_rect = pygame.Rect(0, 0, width, top_h)
        footer_rect = pygame.Rect(0, height - footer_h, width, footer_h)
        content_rect = pygame.Rect(0, top_h, width, height - top_h - footer_h)
        card_rects = [
            pygame.Rect(
                margin,
                content_top + idx * (card_h + gap),
                width - margin * 2,
                card_h,
            )
            for idx in range(MAX_CARDS_PER_PAGE)
        ]

        dirty_rects: List[pygame.Rect] = []

        if redraw_top:
            pygame.draw.rect(backbuffer, C_ACCENT, top_rect)
            left = f"HW Monitor ({len(devices)} host)"
            right = datetime.now().strftime("%H:%M:%S")
            page_text = f"{page_index + 1}/{page_count}"
            right_x = width - margin - font_top.size(right)[0]
            page_x = right_x - font_small.size(page_text)[0] - margin * 2
            
            left_max = max(20, page_x - margin - 20)
            left = fit_text(font_top, left, left_max)
            backbuffer.blit(font_top.render(left, True, (0, 0, 0)), (margin, 6))
            backbuffer.blit(font_small.render(page_text, True, (0, 0, 0)), (page_x, 6 + (font_top.get_height() - font_small.get_height()) // 2))
            backbuffer.blit(font_top.render(right, True, (0, 0, 0)), (right_x, 6))

            progress_bg = pygame.Rect(margin, top_h - 4, max(4, width - margin * 2), 3)
            pygame.draw.rect(backbuffer, (18, 32, 51), progress_bg, border_radius=2)
            if PAGE_INTERVAL_SECONDS > 0:
                elapsed = max(0.0, now - last_page_rotate)
                ratio = min(1.0, elapsed / PAGE_INTERVAL_SECONDS)
                progress_fg = progress_bg.copy()
                progress_fg.width = max(1, int(progress_bg.width * ratio))
                pygame.draw.rect(backbuffer, C_TEXT, progress_fg, border_radius=2)
            dirty_rects.append(top_rect)

        if redraw_cards:
            pygame.draw.rect(backbuffer, C_BG, content_rect)
            dirty_rects.append(content_rect)

            if active_count == 0:
                empty = "Waiting for MQTT metrics..."
                detail = "Topic: sys/agents/+/metrics"
                x = width // 2
                y = content_rect.y + content_rect.height // 2 - font_title.get_height()
                empty_surface = font_title.render(fit_text(font_title, empty, width - margin * 2), True, C_DIM)
                detail_surface = font_small.render(fit_text(font_small, detail, width - margin * 2), True, C_DIM)
                backbuffer.blit(empty_surface, (x - empty_surface.get_width() // 2, y))
                backbuffer.blit(detail_surface, (x - detail_surface.get_width() // 2, y + font_title.get_height() + 8))

            for slot_index, rect in enumerate(card_rects):
                dev = devices_for_cards[slot_index]
                stale = dev is None or (now - dev.last_seen_ts > STALE_SECONDS)
                card_color = C_CARD_STALE if stale and dev is not None else C_CARD
                pygame.draw.rect(backbuffer, card_color, rect, border_radius=12)
                pygame.draw.rect(backbuffer, C_ACCENT_DARK, rect, width=1, border_radius=12)

                if dev is None:
                    txt = font_main.render("No device", True, C_DIM)
                    backbuffer.blit(txt, (rect.x + 12, rect.y + 10))
                    dirty_rects.append(rect)
                    continue

                # 3-Column Layout Calculations
                col1_w = int(rect.width * 0.35)
                col2_w = int(rect.width * 0.25)
                col3_w = rect.width - col1_w - col2_w

                # --- Left Column: Node Info & Stats ---
                left_x = rect.x + 10
                current_y = rect.y + 10
                
                title_color = C_CRIT if stale else C_TEXT
                title = fit_text(font_title, dev.host, col1_w - 6)
                backbuffer.blit(font_title.render(title, True, title_color), (left_x, current_y))
                current_y += font_title.get_height() + 6
                
                # Status
                pygame.draw.circle(backbuffer, C_CRIT if stale else C_CPU, (left_x + 6, current_y + 6), 4)
                status_txt = "STALE" if stale else "ACTIVE"
                backbuffer.blit(font_small.render(status_txt, True, C_CRIT if stale else C_DIM), (left_x + 16, current_y))
                current_y += font_small.get_height() + 10

                # Data explicitly labeled (CPU, GPU, DSK, NET)
                lbl_bg = (32, 45, 66)
                lbl_fg = (160, 175, 200)

                def draw_badge(cx: int, cy: int, label: str, val_text: str, val_color: Tuple[int, int, int], pad: int = 4) -> int:
                    lbl_surf = font_small.render(label, True, lbl_fg)
                    val_surf = font_small.render(val_text, True, val_color)
                    bw = lbl_surf.get_width() + 4
                    pygame.draw.rect(backbuffer, lbl_bg, (cx, cy, bw, font_small.get_height() + 2), border_radius=2)
                    backbuffer.blit(lbl_surf, (cx + 2, cy + 1))
                    backbuffer.blit(val_surf, (cx + bw + 2, cy + 1))
                    return cx + bw + 2 + val_surf.get_width() + pad

                # Disk Temp & IO
                bx = left_x
                d_val = dev.disk_temp_c
                if d_val is not None:
                    bx = draw_badge(bx, current_y, "DSK", format_temp(d_val), pick_temp_color(d_val))
                else:
                    bx = draw_badge(bx, current_y, "DSK", "NA", C_DIM)
                
                rw_str = f"R:{format_bytes_short(dev.disk_read_bps)} W:{format_bytes_short(dev.disk_write_bps)}"
                rw_w = font_small.size(rw_str)[0] + 6
                if (bx - left_x + rw_w) <= col1_w + 15:
                    backbuffer.blit(font_small.render(rw_str, True, (120, 140, 180)), (bx, current_y + 1))
                    current_y += font_small.get_height() + 4
                else:
                    current_y += font_small.get_height() + 4
                    backbuffer.blit(font_small.render(rw_str, True, (120, 140, 180)), (left_x + 30, current_y + 1))
                    current_y += font_small.get_height() + 4

                # Network
                n_up = f"↑{format_bytes_short(dev.net_up_bps)}"
                n_dn = f"↓{format_bytes_short(dev.net_down_bps)}"
                nx = draw_badge(left_x, current_y, "NET", n_up, C_WARN)
                
                dn_w = font_small.size(n_dn)[0]
                if (nx - left_x + dn_w) <= col1_w + 15:
                    backbuffer.blit(font_small.render(n_dn, True, C_CPU), (nx, current_y + 1))
                else:
                    current_y += font_small.get_height() + 4
                    backbuffer.blit(font_small.render(n_dn, True, C_CPU), (left_x + 30, current_y + 1))

                # --- Middle Column: Circular Gauges ---
                mid_x = rect.x + col1_w
                
                has_gpu = dev.gpu_percent > 0 or dev.gpu_temps_c
                num_gauges = 3 if has_gpu else 2
                gauge_size = min(col2_w - 6, max(30, (rect.height - 24) // num_gauges))
                
                total_h = num_gauges * gauge_size + (num_gauges - 1) * 4
                start_y = rect.y + 10 + max(0, (rect.height - 20 - total_h) // 2)
                
                cpu_g_rect = pygame.Rect(mid_x + (col2_w - gauge_size) // 2, start_y, gauge_size, gauge_size)
                ram_g_rect = pygame.Rect(mid_x + (col2_w - gauge_size) // 2, cpu_g_rect.bottom + 4, gauge_size, gauge_size)
                
                c_cpu = pick_usage_color(dev.cpu_percent, C_CPU)
                c_ram = pick_usage_color(dev.ram_percent, C_RAM)
                
                draw_arc_gauge(backbuffer, cpu_g_rect, "CPU", f"{dev.cpu_percent:2.0f}%", dev.cpu_percent, c_cpu, font_small, font_small, 6, False)
                draw_arc_gauge(backbuffer, ram_g_rect, "RAM", f"{dev.ram_percent:2.0f}%", dev.ram_percent, c_ram, font_small, font_small, 6, False)

                if has_gpu:
                    gpu_g_rect = pygame.Rect(mid_x + (col2_w - gauge_size) // 2, ram_g_rect.bottom + 4, gauge_size, gauge_size)
                    c_gpu = pick_usage_color(dev.gpu_percent, C_GPU)
                    draw_arc_gauge(backbuffer, gpu_g_rect, "GPU", f"{dev.gpu_percent:2.0f}%", dev.gpu_percent, c_gpu, font_small, font_small, 6, False)

                # --- Right Column: History Graph ---
                right_x = mid_x + col2_w
                chart_w = col3_w - 12
                chart_h = max(20, rect.height - 20)
                
                # Split chart into CPU and GPU/RAM depending on space
                spark1 = pygame.Rect(right_x, rect.y + 10, chart_w, chart_h // 2 - 4)
                spark2 = pygame.Rect(right_x, spark1.bottom + 8, chart_w, chart_h // 2 - 4)
                
                if chart_h >= 24:
                    c_color = pick_temp_color(dev.cpu_temp_c, C_CPU) if dev.cpu_temp_c else C_DIM
                    draw_sparkline(backbuffer, dev.cpu_temp_hist, c_color, spark1, max_val=110.0, phase=(now * 0.55 + slot_index * 0.17) % 1.0)
                    top_text = font_small.render(f"CPU {format_temp(dev.cpu_temp_c)}", True, c_color)
                    backbuffer.blit(top_text, (spark1.x + 4, spark1.y + 2))
                    
                    g_val = extract_primary_gpu_temp(dev.gpu_temps_c)
                    g_color = pick_temp_color(g_val, C_GPU) if g_val else C_DIM
                    draw_sparkline(backbuffer, dev.gpu_temp_hist, g_color, spark2, max_val=110.0, phase=(now * 0.55 + slot_index * 0.17 + 0.36) % 1.0)
                    bot_text = font_small.render(f"GPU {format_temp(g_val)}", True, g_color)
                    backbuffer.blit(bot_text, (spark2.x + 4, spark2.y + 2))
                
                dirty_rects.append(rect)

        if redraw_footer:
            pygame.draw.rect(backbuffer, (12, 18, 30), footer_rect)
            
            # Block 1: Host System Stats
            host_cpu = psutil.cpu_percent(interval=0)
            host_ram = psutil.virtual_memory().percent
            host_temp = format_temp(get_host_temp())
            h_str = f" SYS C:{host_cpu:2.0f}% R:{host_ram:2.0f}% T:{host_temp} "
            h_txt = font_footer.render(h_str, True, C_TEXT)
            b1_bg = pygame.Rect(margin, footer_rect.y + 4, h_txt.get_width() + 8, footer_h - 8)
            pygame.draw.rect(backbuffer, C_CARD, b1_bg, border_radius=4)
            backbuffer.blit(h_txt, (b1_bg.x + 4, b1_bg.y + (b1_bg.height - h_txt.get_height()) // 2))

            # Block 2: MQTT Status
            m_str = f" MQTT:{len(devices)} "
            m_txt = font_footer.render(m_str, True, C_BG)
            b2_bg = pygame.Rect(b1_bg.right + 8, footer_rect.y + 4, m_txt.get_width() + 8, footer_h - 8)
            mqtt_color = C_CPU if len(devices) > 0 else (100, 110, 120)
            pygame.draw.rect(backbuffer, mqtt_color, b2_bg, border_radius=4)
            backbuffer.blit(m_txt, (b2_bg.x + 4, b2_bg.y + (b2_bg.height - m_txt.get_height()) // 2))

            # Heartbeat Pulse
            pulse_color = C_CPU if int(now * 2) % 2 == 0 else C_ACCENT
            dot_x = footer_rect.right - margin - 5
            dot_y = footer_rect.y + footer_h // 2
            pygame.draw.circle(backbuffer, pulse_color, (dot_x, dot_y), 4)
            
            dirty_rects.append(footer_rect)

        if dirty_rects:
            if rotate_output:
                rotated = pygame.transform.rotate(backbuffer, PORTRAIT_ROTATE_DEGREE)
                if rotated.get_size() != screen.get_size():
                    rotated = pygame.transform.smoothscale(rotated, screen.get_size())
                screen.blit(rotated, (0, 0))
                pygame.display.flip()
            else:
                for rect in dirty_rects:
                    screen.blit(backbuffer, rect, rect)
                pygame.display.update(dirty_rects)

        clock.tick(FPS)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    pygame.quit()


if __name__ == "__main__":
    main()
