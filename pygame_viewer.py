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
C_BG = (15, 23, 42)
C_CARD = (30, 41, 59)
C_CARD_STALE = (60, 38, 45)
C_TEXT = (248, 250, 252)
C_DIM = (148, 163, 184)
C_ACCENT = (56, 189, 248)
C_ACCENT_DARK = (14, 116, 144)
C_CPU = (52, 211, 153)
C_RAM = (167, 139, 250)
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


def pick_temp_color(temp_c: Optional[float]) -> Tuple[int, int, int]:
    """Pick warning color from temperature value."""
    if temp_c is None:
        return C_DIM
    if temp_c >= 80:
        return C_CRIT
    if temp_c >= 70:
        return C_WARN
    return C_TEXT


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
    cpu_temp_c: Optional[float]
    gpu_temps_c: Tuple[float, ...]
    net_up_bps: float
    net_down_bps: float
    disk_read_bps: float
    disk_write_bps: float
    disk_temp_c: Optional[float]
    cpu_hist: Tuple[float, ...]
    ram_hist: Tuple[float, ...]
    last_seen_ts: float


@dataclass
class DeviceState:
    """Mutable runtime state for each host."""

    host: str
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    cpu_temp_c: Optional[float] = None
    gpu_temps_c: Tuple[float, ...] = ()
    net_up_bps: float = 0.0
    net_down_bps: float = 0.0
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0
    disk_temp_c: Optional[float] = None
    cpu_hist: Deque[float] = field(default_factory=lambda: deque([0.0] * 30, maxlen=60))
    ram_hist: Deque[float] = field(default_factory=lambda: deque([0.0] * 30, maxlen=60))
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
                    cpu_temp_c=state.cpu_temp_c,
                    gpu_temps_c=state.gpu_temps_c,
                    net_up_bps=state.net_up_bps,
                    net_down_bps=state.net_down_bps,
                    disk_read_bps=state.disk_read_bps,
                    disk_write_bps=state.disk_write_bps,
                    disk_temp_c=state.disk_temp_c,
                    cpu_hist=tuple(state.cpu_hist),
                    ram_hist=tuple(state.ram_hist),
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
    phase: float = 0.0,
) -> None:
    """Draw sparkline with lightweight animation in rect."""
    data = list(values)
    if len(data) < 2 or rect.width <= 2 or rect.height <= 2:
        return
    pygame.draw.rect(surface, (26, 35, 53), rect, border_radius=4)
    max_val = 100.0
    step_x = rect.width / (len(data) - 1)
    points: List[Tuple[float, float]] = []
    for idx, val in enumerate(data):
        clamped = max(0.0, min(max_val, float(val)))
        px = rect.x + idx * step_x
        py = rect.y + rect.height - (clamped / max_val * rect.height)
        points.append((px, py))

    fill_points = [(rect.x, rect.bottom - 1), *points, (rect.right - 1, rect.bottom - 1)]
    pygame.draw.polygon(surface, scale_color(color, 0.25), fill_points)
    pygame.draw.lines(surface, color, False, points, 2)

    pulse_radius = 2 + int((math.sin(phase * math.tau) + 1.0) * 1.5)
    last_x, last_y = points[-1]
    pygame.draw.circle(surface, scale_color(color, 1.2), (int(last_x), int(last_y)), pulse_radius)

    sweep_ratio = phase % 1.0
    sweep_x = rect.x + int(sweep_ratio * max(1, rect.width - 1))
    pygame.draw.line(surface, scale_color(color, 1.1), (sweep_x, rect.y + 1), (sweep_x, rect.bottom - 2), 1)


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
    font_footer_main = pygame.font.SysFont("dejavusansmono", 18, bold=True)
    font_footer_meta = pygame.font.SysFont("dejavusansmono", 14)
    font_cache_key: Optional[Tuple[int, int, int, int, int, int]] = None

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
        title_size = clamp_int(height // 14, 26, 40)
        main_size = clamp_int(height // 21, 20, 28)
        small_size = clamp_int(height // 26, 17, 22)
        top_size = clamp_int(height // 22, 17, 28)
        footer_main_size = clamp_int(int(main_size * 0.95), 19, 30)
        footer_meta_size = clamp_int(int(small_size * 0.9), 15, 20)

        current_font_key = (top_size, title_size, main_size, small_size, footer_main_size, footer_meta_size)
        if current_font_key != font_cache_key:
            font_top = pygame.font.SysFont("dejavusansmono", top_size, bold=True)
            font_title = pygame.font.SysFont("dejavusansmono", title_size, bold=True)
            font_main = pygame.font.SysFont("dejavusansmono", main_size)
            font_small = pygame.font.SysFont("dejavusansmono", small_size)
            font_footer_main = pygame.font.SysFont("dejavusansmono", footer_main_size, bold=True)
            font_footer_meta = pygame.font.SysFont("dejavusansmono", footer_meta_size)
            font_cache_key = current_font_key
            redraw_top = True
            redraw_cards = True
            redraw_footer = True

        margin = max(8, width // 42)
        top_h = font_top.get_height() + 12
        footer_h = font_footer_main.get_height() + font_footer_meta.get_height() + 12
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
            left_max = max(20, width - margin * 3 - font_top.size(right)[0] - font_small.size(page_text)[0] - 40)
            left = fit_text(font_top, left, left_max)
            backbuffer.blit(font_top.render(left, True, (0, 0, 0)), (margin, 6))
            backbuffer.blit(
                font_small.render(page_text, True, (0, 0, 0)),
                (width // 2 - font_small.size(page_text)[0] // 2, top_h - font_small.get_height() - 2),
            )
            backbuffer.blit(font_top.render(right, True, (0, 0, 0)), (width - margin - font_top.size(right)[0], 6))

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

                title_color = C_CRIT if stale else C_TEXT
                title = fit_text(font_title, dev.host, rect.width - 24 - 70)
                backbuffer.blit(font_title.render(title, True, title_color), (rect.x + 10, rect.y + 8))
                if stale:
                    stale_txt = font_small.render("STALE", True, C_CRIT)
                    backbuffer.blit(stale_txt, (rect.right - stale_txt.get_width() - 10, rect.y + 12))

                y = rect.y + 12 + font_title.get_height() + 6
                line_h = font_main.get_height() + max(3, font_main.get_height() // 5)
                line_max = rect.width - 20
                wide_mode = rect.width >= 240

                if wide_mode:
                    cpu_text = f"CPU {dev.cpu_percent:3.0f}% {format_temp(dev.cpu_temp_c)}"
                    ram_text = f"RAM {dev.ram_percent:3.0f}%"
                    half_w = (rect.width - 24) // 2
                    backbuffer.blit(font_main.render(fit_text(font_main, cpu_text, half_w), True, C_CPU), (rect.x + 10, y))
                    backbuffer.blit(
                        font_main.render(fit_text(font_main, ram_text, half_w), True, C_RAM),
                        (rect.x + 14 + half_w, y),
                    )
                else:
                    line = f"C {dev.cpu_percent:3.0f}% {format_temp(dev.cpu_temp_c)}  R {dev.ram_percent:3.0f}%"
                    backbuffer.blit(font_main.render(fit_text(font_main, line, line_max), True, C_CPU), (rect.x + 10, y))

                y += line_h
                line = f"NET ↑{format_bytes_short(dev.net_up_bps)} ↓{format_bytes_short(dev.net_down_bps)}"
                backbuffer.blit(font_main.render(fit_text(font_main, line, line_max), True, C_RAM), (rect.x + 10, y))

                y += line_h
                line = f"DSK ↑{format_bytes_short(dev.disk_read_bps)} ↓{format_bytes_short(dev.disk_write_bps)} T{format_temp(dev.disk_temp_c)}"
                disk_color = pick_temp_color(dev.disk_temp_c)
                backbuffer.blit(font_main.render(fit_text(font_main, line, line_max), True, disk_color), (rect.x + 10, y))

                y += line_h
                gpu = " ".join(format_temp(t) for t in dev.gpu_temps_c) if dev.gpu_temps_c else "NA"
                age = int(max(0.0, now - dev.last_seen_ts))
                line = f"GPU {gpu}  AGE {age}s"
                backbuffer.blit(font_small.render(fit_text(font_small, line, line_max), True, C_DIM), (rect.x + 10, y))

                spark_h = clamp_int(rect.height // 6, 16, 30)
                spark_y = rect.bottom - spark_h - 10
                spark_w = (rect.width - 26) // 2
                cpu_spark_rect = pygame.Rect(rect.x + 10, spark_y, spark_w, spark_h)
                ram_spark_rect = pygame.Rect(rect.x + 16 + spark_w, spark_y, spark_w, spark_h)

                label_y = spark_y - font_small.get_height() - 2
                if label_y > y:
                    backbuffer.blit(font_small.render("CPU", True, C_CPU), (cpu_spark_rect.x, label_y))
                    backbuffer.blit(font_small.render("RAM", True, C_RAM), (ram_spark_rect.x, label_y))

                base_phase = (now * 0.55 + slot_index * 0.17) % 1.0
                draw_sparkline(backbuffer, dev.cpu_hist, C_CPU, cpu_spark_rect, phase=base_phase)
                draw_sparkline(backbuffer, dev.ram_hist, C_RAM, ram_spark_rect, phase=(base_phase + 0.36) % 1.0)
                dirty_rects.append(rect)

        if redraw_footer:
            pygame.draw.rect(backbuffer, C_ACCENT_DARK, footer_rect)
            host_cpu = psutil.cpu_percent(interval=0)
            host_ram = psutil.virtual_memory().percent
            host_temp = get_host_temp()
            footer_main = f"RPI C{host_cpu:2.0f}% R{host_ram:2.0f}% T{format_temp(host_temp)}"
            footer_meta = f"MQTT {len(devices)}  DRV {driver_name}"
            footer_main = fit_text(font_footer_main, footer_main, width - margin * 2 - 14)
            footer_meta = fit_text(font_footer_meta, footer_meta, width - margin * 2 - 14)

            main_y = footer_rect.y + 2
            meta_y = main_y + font_footer_main.get_height() + 1
            backbuffer.blit(font_footer_main.render(footer_main, True, C_TEXT), (margin, main_y))
            backbuffer.blit(font_footer_meta.render(footer_meta, True, C_TEXT), (margin, meta_y))

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
