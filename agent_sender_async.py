#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Async System Monitor (Multi-rate MQTT sender)
CPU/MEM/NET 每秒、DISK 每 3 秒、TEMP 每 10 秒
- 加入 cpu.loadavg、system.uptime_sec
- 加入 mqtt_stats：publish_ok/err、last_rc、is_connected、reconnects
"""

import asyncio
import json
import os
import re
import socket
import time
import glob
from typing import Any, Dict, Optional

import psutil
from paho.mqtt import client as mqtt
from dotenv import load_dotenv

load_dotenv()

# ===== MQTT CONFIG =====
BROKER_HOST = os.getenv("BROKER_HOST", "192.168.5.32")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
MQTT_USER   = os.getenv("MQTT_USER", "mqtter")
MQTT_PASS   = os.getenv("MQTT_PASS", "seven777")
HOSTNAME    = socket.gethostname()
TOPIC       = f"sys/agents/{HOSTNAME}/metrics"

# ===== MQTT Client =====
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"agent-{HOSTNAME}")
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
mqtt_client.loop_start()

mqtt_stats = {
    "publish_ok": 0,
    "publish_err": 0,
    "last_publish_rc": None,
    "reconnects": 0,
    "is_connected": False,
    "last_error": None,
}

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    mqtt_stats["is_connected"] = (reason_code == 0)
    if reason_code == 0:
        print(f"✅ MQTT connected to {BROKER_HOST}:{BROKER_PORT}")
        mqtt_stats["last_error"] = None
    else:
        print(f"❌ MQTT connect failed: reason_code={reason_code}")
        mqtt_stats["last_error"] = f"Connect failed: {reason_code}"
mqtt_client.on_connect = on_connect

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    mqtt_stats["is_connected"] = False
    print(f"⚠️ MQTT disconnected: reason_code={reason_code}")
    mqtt_stats["last_error"] = f"Disconnected: {reason_code}"
mqtt_client.on_disconnect = on_disconnect

def mqtt_connect():
    try:
        mqtt_client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    except Exception as e:
        mqtt_stats["last_error"] = str(e)
        print(f"⚠️ MQTT connect failed: {e}")

mqtt_connect()

# ===== GLOBAL STATE =====
metrics: Dict[str, Any] = {
    "cpu": None,
    "memory": None,
    "disk_io": None,
    "temperatures": None,
    "network_io": None,
    "system": None,
    "gpu": None,
}

# ===== Helpers =====
def normalize_device_name(name: str) -> str:
    if m := re.match(r"^(nvme\d+n\d+)(?:p\d+)?$", name): return m.group(1)
    if m := re.match(r"^(sd[a-z]+)\d*$", name): return m.group(1)
    if m := re.match(r"^(mmcblk\d+)(?:p\d+)?$", name): return m.group(1)
    if m := re.match(r"^(md\d+)(?:p\d+)?$", name): return m.group(1)
    return name

# ===== CPU / MEM =====
def get_cpu_block() -> Dict[str, Any]:
    freq = psutil.cpu_freq()
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1 = load5 = load15 = None
    return {
        "percent_total": psutil.cpu_percent(interval=None),
        "percent_per_core": psutil.cpu_percent(interval=None, percpu=True),
        "freq_mhz": freq._asdict() if freq else None,
        "count_logical": psutil.cpu_count(logical=True),
        "count_physical": psutil.cpu_count(logical=False),
        "loadavg": [load1, load5, load15],
    }

def get_mem_block() -> Dict[str, Any]:
    vm, sm = psutil.virtual_memory(), psutil.swap_memory()
    return {
        "ram":  {"total": vm.total, "used": vm.used, "available": vm.available, "percent": vm.percent},
        "swap": {"total": sm.total, "used": sm.used, "free": sm.free, "percent": sm.percent},
    }

def get_system_block() -> Dict[str, Any]:
    return {
        "uptime_sec": int(time.time() - psutil.boot_time()),
        "hostname": HOSTNAME,
        "pid": os.getpid(),
    }

# ===== Disk I/O =====
_prev_disk = psutil.disk_io_counters(perdisk=True)
def get_disk_io_block(elapsed: float) -> Dict[str, Any]:
    global _prev_disk
    curr = psutil.disk_io_counters(perdisk=True)
    result: Dict[str, Any] = {}
    for dev, io in curr.items():
        if dev.startswith("loop") or dev.startswith("dm-"):
            continue
        parent = normalize_device_name(dev)
        prev = _prev_disk.get(dev)
        if not prev:
            continue
        rbps = (io.read_bytes - prev.read_bytes) / elapsed
        wbps = (io.write_bytes - prev.write_bytes) / elapsed
        riops = (io.read_count - prev.read_count) / elapsed
        wiops = (io.write_count - prev.write_count) / elapsed
        # 若多個分割區被歸到同一 parent，取加總（同秒內通常只有一筆）
        if parent not in result:
            result[parent] = {"rate": {"read_bytes_per_s": 0.0, "write_bytes_per_s": 0.0, "read_iops": 0.0, "write_iops": 0.0}}
        result[parent]["rate"]["read_bytes_per_s"]  += rbps
        result[parent]["rate"]["write_bytes_per_s"] += wbps
        result[parent]["rate"]["read_iops"]         += riops
        result[parent]["rate"]["write_iops"]        += wiops
    # round
    for v in result.values():
        for k in v["rate"]:
            v["rate"][k] = round(v["rate"][k], 3)
    _prev_disk = curr
    return result

# ===== Network I/O (ALL NICs) =====
_prev_net = psutil.net_io_counters(pernic=True)
def get_net_io_block(elapsed: float) -> Dict[str, Any]:
    global _prev_net
    curr = psutil.net_io_counters(pernic=True)
    stats = psutil.net_if_stats()
    per_nic: Dict[str, Any] = {}
    total = {"rate": {"rx_bytes_per_s": 0.0, "tx_bytes_per_s": 0.0},
             "cumulative": {"bytes_recv": 0, "bytes_sent": 0}}

    for nic, io in curr.items():
        prev = _prev_net.get(nic)
        if not prev:
            continue
        rx_bps = (io.bytes_recv - prev.bytes_recv) / elapsed
        tx_bps = (io.bytes_sent - prev.bytes_sent) / elapsed
        st = stats.get(nic)
        meta = {"isup": None, "speed_mbps": None, "mtu": None, "duplex": None}
        if st:
            meta["isup"] = st.isup
            meta["speed_mbps"] = st.speed if st.speed >= 0 else None
            meta["mtu"] = st.mtu if st.mtu >= 0 else None
            meta["duplex"] = st.duplex

        per_nic[nic] = {
            "rate": {"rx_bytes_per_s": round(rx_bps, 3), "tx_bytes_per_s": round(tx_bps, 3)},
            "cumulative": {"bytes_recv": io.bytes_recv, "bytes_sent": io.bytes_sent},
            "meta": meta
        }
        total["rate"]["rx_bytes_per_s"] += rx_bps
        total["rate"]["tx_bytes_per_s"] += tx_bps
        total["cumulative"]["bytes_recv"] += io.bytes_recv
        total["cumulative"]["bytes_sent"] += io.bytes_sent

    _prev_net = curr
    total["rate"]["rx_bytes_per_s"] = round(total["rate"]["rx_bytes_per_s"], 3)
    total["rate"]["tx_bytes_per_s"] = round(total["rate"]["tx_bytes_per_s"], 3)
    return {"per_nic": per_nic, "total": total}

# ===== Temperatures: map drivetemp -> sda/sdb/mmcblk/vd*, and NVMe -> nvmeXnY =====
import glob
import os
import re
from typing import Optional, Dict, Any

def _resolve_drivetemp_blockdev(hwmon_dir: str) -> Optional[str]:
    """
    從 /sys/class/hwmon/hwmonX （name=drivetemp）追溯到對應的 block 裝置名，例如 sda/sdb/mmcblk0/vda。
    """
    try:
        dev = os.path.realpath(os.path.join(hwmon_dir, "device"))
        # 1) 直接在當前節點找 block 子目錄
        blk = os.path.join(dev, "block")
        if os.path.isdir(blk):
            for e in os.listdir(blk):
                if re.match(r"^(sd[a-z]+|mmcblk\d+|vd[a-z]+)$", e):
                    return e
        # 2) 向上回溯找 block
        cur = dev
        while cur != "/":
            blk = os.path.join(cur, "block")
            if os.path.isdir(blk):
                for e in os.listdir(blk):
                    if re.match(r"^(sd[a-z]+|mmcblk\d+|vd[a-z]+)$", e):
                        return e
            cur = os.path.dirname(cur)
    except Exception:
        pass
    return None

def _read_first(glob_pat: str) -> Optional[float]:
    for p in sorted(glob.glob(glob_pat)):
        try:
            with open(p, "r") as f:
                return int(f.read().strip()) / 1000.0  # 毫度C -> 度C
        except Exception:
            continue
    return None

def _nvme_controller_of_namespace(ns_block: str) -> Optional[str]:
    """
    從 /sys/block/nvmeXnY 找到對應控制器 nvmeX。
    """
    try:
        dev_link = os.path.realpath(f"/sys/block/{ns_block}/device")
        cur = dev_link
        while cur != "/":
            base = os.path.basename(cur)
            if re.fullmatch(r"nvme\d+", base) and os.path.isdir(f"/sys/class/nvme/{base}"):
                return base  # e.g., nvme0
            cur = os.path.dirname(cur)
    except Exception:
        pass
    return None

def _collect_nvme_namespace_temps() -> Dict[str, float]:
    """
    回傳 { 'nvme0n1': 43.5, ... } ：讀取控制器 hwmon Composite 溫度，套用到所有 namespace。
    """
    out: Dict[str, float] = {}
    try:
        blocks = [d for d in os.listdir("/sys/block") if re.match(r"nvme\d+n\d+", d)]
    except FileNotFoundError:
        blocks = []
    for ns in sorted(blocks):
        ctl = _nvme_controller_of_namespace(ns)
        val = _read_first(f"/sys/class/nvme/{ctl}/device/hwmon/hwmon*/temp*_input") if ctl else None
        if val is not None:
            out[ns] = val
    return out

def get_temps_block() -> Optional[Dict[str, Any]]:
    """
    回傳鍵包含：
      - 'sda'、'sdb'、'mmcblk0'、'vda'…（drivetemp 映射）
      - 'nvme0n1'、'nvme1n1'…（NVMe 每 namespace）
      - 以及 CPU/GPU 等一般 sensor（k10temp/coretemp/amdgpu…）
    """
    # 先讀 psutil，保留 CPU/GPU 等非磁碟 sensor
    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        sensors = None

    out: Dict[str, Any] = {}
    if sensors:
        for name, entries in sensors.items():
            # 先排除 drivetemp/nvme，這兩個我們手動更精準地處理
            if name in ("drivetemp", "nvme"):
                continue
            out[name] = [
                {"label": (e.label or ""), "current": e.current, "high": e.high, "critical": e.critical}
                for e in entries
                if e.current is not None
            ]

    # 解析 drivetemp -> sda/sdb/mmcblk/vd*
    hwmon_root = "/sys/class/hwmon"
    if os.path.isdir(hwmon_root):
        try:
            for entry in os.listdir(hwmon_root):
                p = os.path.join(hwmon_root, entry)
                name_file = os.path.join(p, "name")
                if not os.path.isfile(name_file):
                    continue
                try:
                    nm = open(name_file).read().strip()
                except Exception:
                    continue
                if nm != "drivetemp":
                    continue

                blk = _resolve_drivetemp_blockdev(p) or "drivetemp"
                # 讀這個 hwmon 節點裡所有 temp*_input
                for fn in os.listdir(p):
                    if fn.startswith("temp") and fn.endswith("_input"):
                        base = fn[:-6]
                        try:
                            cur = int(open(os.path.join(p, f"{base}_input")).read().strip()) / 1000.0
                            lbl = ""
                            lf = os.path.join(p, f"{base}_label")
                            if os.path.isfile(lf):
                                lbl = open(lf).read().strip()
                            out.setdefault(blk, []).append(
                                {"label": lbl, "current": cur, "high": 0.0, "critical": 0.0}
                            )
                        except Exception:
                            pass
        except Exception:
            pass

    # 解析 NVMe -> 每個 namespace
    try:
        ns_temps = _collect_nvme_namespace_temps()
        for ns, val in ns_temps.items():
            out.setdefault(ns, []).append({"label": "Composite", "current": val, "high": 0.0, "critical": 0.0})
    except Exception:
        pass

    # 後援：若 NVMe 仍沒有對應，才把 psutil 的 'nvme' 通用值套用到各 namespace
    if sensors and sensors.get("nvme"):
        try:
            generic = float(sensors["nvme"][0].current)
        except Exception:
            generic = None
        if generic is not None:
            try:
                blocks = [d for d in os.listdir("/sys/block") if re.match(r"nvme\d+n\d+", d)]
            except FileNotFoundError:
                blocks = []
            for ns in blocks:
                if ns not in out:
                    out[ns] = [{"label": "Composite", "current": generic, "high": 0.0, "critical": 0.0}]

    return out or None

# ===== GPU =====
def get_gpu_usage() -> Optional[float]:
    """Get GPU usage percentage."""
    import subprocess
    try:
        # Try NVIDIA GPU first
        result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass

    try:
        # Try Intel GPU (via intel_gpu_top)
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
        # Try Intel GPU via sysfs
        with open('/sys/class/drm/card0/engine/rcs0/busy_percent', 'r') as f:
            return float(f.read().strip())
    except Exception:
        pass

    try:
        # Try AMD GPU
        with open('/sys/class/drm/card0/device/gpu_busy_percent', 'r') as f:
            return float(f.read().strip())
    except Exception:
        pass

    return None

def get_gpu_temp() -> Optional[float]:
    """Get GPU temperature in Celsius."""
    import subprocess
    try:
        # Try NVIDIA GPU first
        result = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass

    try:
        # Try Intel GPU via sensors
        temps = psutil.sensors_temperatures()
        for sensor_name in ['i915', 'coretemp', 'pch_cannonlake']:
            if sensor_name in temps:
                for entry in temps[sensor_name]:
                    if entry.label and any(x in entry.label.lower() for x in ['gpu', 'gt']):
                        return entry.current
    except Exception:
        pass

    try:
        # Try Intel GPU via sysfs hwmon
        for hwmon_path in glob.glob('/sys/class/drm/card0/hwmon/hwmon*/temp*_input'):
            with open(hwmon_path, 'r') as f:
                temp_millidegrees = int(f.read().strip())
                return temp_millidegrees / 1000.0
    except Exception:
        pass

    try:
        # Try Raspberry Pi GPU
        result = subprocess.run(['vcgencmd', 'measure_temp'],
                                capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            temp_str = result.stdout.strip()
            temp_val = temp_str.split('=')[1].replace("'C", "")
            return float(temp_val)
    except Exception:
        pass

    try:
        # Try AMD GPU
        temps = psutil.sensors_temperatures()
        for sensor_name in ['amdgpu', 'radeon']:
            if sensor_name in temps and temps[sensor_name]:
                return temps[sensor_name][0].current
    except Exception:
        pass

    return None

def get_gpu_block() -> Optional[Dict[str, Any]]:
    """Collect GPU metrics."""
    usage = get_gpu_usage()
    temp = get_gpu_temp()

    # Only return GPU block if we have at least one valid metric
    if usage is not None or temp is not None:
        return {
            "usage_percent": usage,
            "temperature_celsius": temp,
        }
    return None


# ===== MQTT publish =====
def publish_metrics():
    payload = {
        "ts": int(time.time()),
        "host": HOSTNAME,
        "system": metrics["system"],
        "cpu": metrics["cpu"],
        "memory": metrics["memory"],
        "disk_io": metrics["disk_io"],
        "temperatures": metrics["temperatures"],
        "network_io": metrics["network_io"],
        "gpu": metrics["gpu"],
        "mqtt_stats": {
            "publish_ok": mqtt_stats["publish_ok"],
            "publish_err": mqtt_stats["publish_err"],
            "last_publish_rc": mqtt_stats["last_publish_rc"],
            "is_connected": mqtt_stats["is_connected"],
            "reconnects": mqtt_stats["reconnects"],
            "last_error": mqtt_stats["last_error"],
        }
    }
    try:
        # 更小的 JSON（減少頻寬）
        info = mqtt_client.publish(TOPIC, json.dumps(payload, separators=(',', ':')), qos=0, retain=False)
        mqtt_stats["last_publish_rc"] = info.rc
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            mqtt_stats["publish_ok"] += 1
        else:
            mqtt_stats["publish_err"] += 1
    except Exception as e:
        mqtt_stats["publish_err"] += 1
        mqtt_stats["last_error"] = str(e)

# ===== Async tasks =====
async def loop_cpu_mem():
    while True:
        metrics["cpu"] = get_cpu_block()
        metrics["memory"] = get_mem_block()
        metrics["system"] = get_system_block()
        await asyncio.sleep(1)

async def loop_disk():
    last = time.time()
    while True:
        now = time.time()
        metrics["disk_io"] = get_disk_io_block(max(1e-6, now - last))
        last = now
        await asyncio.sleep(3)

async def loop_temps():
    while True:
        metrics["temperatures"] = get_temps_block()
        await asyncio.sleep(10)

async def loop_gpu():
    while True:
        metrics["gpu"] = get_gpu_block()
        await asyncio.sleep(5)  # GPU metrics every 5 seconds

async def loop_network():
    last = time.time()
    while True:
        now = time.time()
        metrics["network_io"] = get_net_io_block(max(1e-6, now - last))
        last = now
        await asyncio.sleep(1)

async def loop_publish():
    while True:
        publish_metrics()
        await asyncio.sleep(1)

async def mqtt_reconnector():
    """自動重連機制，使用指數退避策略"""
    retry_delay = 3  # 初始重連延遲（秒）
    max_delay = 60   # 最大重連延遲（秒）

    while True:
        if not mqtt_client.is_connected():
            mqtt_stats["reconnects"] += 1
            print(f"🔄 嘗試重連 MQTT (第 {mqtt_stats['reconnects']} 次)...")
            mqtt_connect()

            # 等待連線結果
            await asyncio.sleep(2)

            # 根據連線狀態調整延遲
            if mqtt_stats["is_connected"]:
                retry_delay = 3  # 重連成功，重置延遲
            else:
                # 連線失敗，使用指數退避
                retry_delay = min(retry_delay * 2, max_delay)
                print(f"⏳ 重連失敗，{retry_delay} 秒後重試")
        else:
            # 已連線，保持短間隔檢查
            retry_delay = 3

        await asyncio.sleep(retry_delay)

# ===== MAIN =====
async def main():
    print(f"🚀 Async Agent started on {HOSTNAME}")
    # 預熱 CPU 計算（提升第一筆準確度）
    psutil.cpu_percent(interval=None, percpu=True)
    await asyncio.gather(
        loop_cpu_mem(),
        loop_disk(),
        loop_temps(),
        loop_gpu(),
        loop_network(),
        loop_publish(),
        mqtt_reconnector(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 stopped by user")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
