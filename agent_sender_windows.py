#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Async System Monitor for Windows (Multi-rate MQTT sender)
- Gathers hardware data from LibreHardwareMonitor's WMI interface.
- Uses psutil for cross-platform stats like memory and network.
- CPU/MEM/NET send every second, DISK every 3 seconds, TEMP/GPU every 10 seconds.
"""

import asyncio
import json
import os
import platform
import socket
import time
from typing import Any, Dict, Optional, List

# This script is designed for Windows and requires LibreHardwareMonitor.
if platform.system() != "Windows":
    print("❌ This script is only for Windows.")
    exit(1)

try:
    import wmi
    import psutil
    from paho.mqtt import client as mqtt
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ A required package is not installed: {e}")
    print("   Please run: pip install wmi psutil paho-mqtt python-dotenv")
    exit(1)

load_dotenv()

# ===== MQTT CONFIG =====
# Read and strip whitespace from environment variables to prevent errors
BROKER_HOST = os.getenv("BROKER_HOST", "").strip()
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
MQTT_USER   = os.getenv("MQTT_USER", "mqtter")
MQTT_PASS   = os.getenv("MQTT_PASS", "seven777")
HOSTNAME    = socket.gethostname()
TOPIC       = f"sys/agents/{HOSTNAME}/metrics"

# Validate Broker Host
if not BROKER_HOST:
    print("❌ MQTT Error: BROKER_HOST is not set in your .env file or environment variables.")
    print("   Please set it to the IP address or hostname of your MQTT broker.")
    exit(1)

# ===== MQTT Client =====
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"agent-{HOSTNAME}")
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

mqtt_stats = {
    "publish_ok": 0,
    "publish_err": 0,
    "last_publish_rc": None,
    "reconnects": 0, # This will be handled by paho-mqtt library now
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
    if reason_code != 0:
        print(f"⚠️ MQTT unexpectedly disconnected: reason_code={reason_code}")
    mqtt_stats["last_error"] = f"Disconnected: {reason_code}"
mqtt_client.on_disconnect = on_disconnect

# Use paho-mqtt's built-in reconnection logic
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

# Start the network loop and initiate connection
mqtt_client.connect_async(BROKER_HOST, BROKER_PORT)
mqtt_client.loop_start()


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
lhm_sensors: List[Any] = []

# ===== WMI / LibreHardwareMonitor =====
def get_lhm_wmi_data() -> List[Any]:
    """Fetches all sensor data from LibreHardwareMonitor WMI provider."""
    try:
        conn = wmi.WMI(namespace="root/LibreHardwareMonitor")
        sensors = conn.Sensor()
        if not sensors:
            print("⚠️  No sensors found in LHM. Is it monitoring any hardware?")
        return sensors
    except wmi.x_wmi as e:
        if e.com_error.hresult == -2147217394: # 0x8004100e
            print("❌ WMI Error: Namespace 'root/LibreHardwareMonitor' not found.")
            print("   Please ensure:")
            print("   1. LibreHardwareMonitor is currently running.")
            print("   2. You have run LibreHardwareMonitor 'As Administrator'.")
            print("   3. In LHM Options, under 'General', 'WMI Provider' is enabled.")
        else:
            print(f"❌ An unexpected WMI error occurred: {e}")
        return []
    except Exception as e:
        print(f"❌ An unexpected error occurred while fetching WMI data: {e}")
        return []

def process_lhm_data():
    """Processes the raw LHM sensor data into the metrics dictionary."""
    global lhm_sensors
    
    cpu_loads = {}
    cpu_temps = []
    cpu_clocks = []
    gpu_data = {}
    storage_temps = {}

    for sensor in lhm_sensors:
        sensor_type = sensor.SensorType
        name = sensor.Name
        value = sensor.Value
        parent_path = sensor.Parent

        if "cpu" in parent_path:
            if sensor_type == 'Load':
                if name == 'CPU Total':
                    metrics["cpu"]["percent_total"] = value
                elif 'CPU Core' in name:
                    try:
                        core_num = int(name.split('#')[-1]) - 1
                        cpu_loads[core_num] = value
                    except (ValueError, IndexError):
                        pass
            elif sensor_type == 'Temperature':
                cpu_temps.append({"label": name, "current": value})
            elif sensor_type == 'Clock':
                cpu_clocks.append({"label": name, "current": value})

        elif "/gpu-" in parent_path:
            gpu_name = parent_path.split('/')[1]
            if gpu_name not in gpu_data:
                gpu_data[gpu_name] = {}
            if sensor_type == 'Load':
                gpu_data[gpu_name]["usage_percent"] = value
            elif sensor_type == 'Temperature':
                gpu_data[gpu_name]["temperature_celsius"] = value

        elif ("/hdd/" in parent_path or "/nvme/" in parent_path) and sensor_type == 'Temperature':
            try:
                parts = parent_path.strip('/').split('/') # e.g., ['nvme', '0']
                device_key = parts[0] + parts[1]          # e.g., 'nvme0'
            except IndexError:
                device_key = parent_path # Fallback

            if device_key not in storage_temps:
                storage_temps[device_key] = []
            
            label = name if name != 'Temperature' else f"{device_key} Temperature"
            storage_temps[device_key].append({"label": label, "current": value})

    if metrics["cpu"]:
        if cpu_loads:
            metrics["cpu"]["percent_per_core"] = [cpu_loads.get(i, 0) for i in range(len(cpu_loads))]
        if cpu_clocks:
            metrics["cpu"]["freq_mhz_per_core"] = [c['current'] for c in cpu_clocks]
    
    if metrics["temperatures"] is not None:
        if cpu_temps:
            metrics["temperatures"]["cpu"] = cpu_temps
        if storage_temps:
            metrics["temperatures"]["storage"] = storage_temps

    if gpu_data:
        metrics["gpu"] = list(gpu_data.values())[0] if gpu_data else None

# ===== psutil based metrics =====
def get_cpu_base_block() -> Dict[str, Any]:
    return {
        "percent_total": 0,
        "percent_per_core": [],
        "count_logical": psutil.cpu_count(logical=True),
        "count_physical": psutil.cpu_count(logical=False),
        "loadavg": None,
    }

def get_mem_block() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
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

_prev_disk = psutil.disk_io_counters(perdisk=True)
def get_disk_io_block(elapsed: float) -> Dict[str, Any]:
    global _prev_disk
    curr = psutil.disk_io_counters(perdisk=True)
    result: Dict[str, Any] = {}
    for dev, io in curr.items():
        prev = _prev_disk.get(dev)
        if not prev: continue
        result[dev] = {"rate": {
            "read_bytes_per_s": round((io.read_bytes - prev.read_bytes) / elapsed, 3),
            "write_bytes_per_s": round((io.write_bytes - prev.write_bytes) / elapsed, 3),
            "read_iops": round((io.read_count - prev.read_count) / elapsed, 3),
            "write_iops": round((io.write_count - prev.write_count) / elapsed, 3)
        }}
    _prev_disk = curr
    return result

_prev_net = psutil.net_io_counters(pernic=True)
def get_net_io_block(elapsed: float) -> Dict[str, Any]:
    global _prev_net
    curr = psutil.net_io_counters(pernic=True)
    stats = psutil.net_if_stats()
    per_nic: Dict[str, Any] = {}
    total = {"rate": {"rx_bytes_per_s": 0.0, "tx_bytes_per_s": 0.0}, "cumulative": {"bytes_recv": 0, "bytes_sent": 0}}

    for nic, io in curr.items():
        prev = _prev_net.get(nic)
        if not prev: continue
        rx_bps = (io.bytes_recv - prev.bytes_recv) / elapsed
        tx_bps = (io.bytes_sent - prev.bytes_sent) / elapsed
        st = stats.get(nic)
        meta = {"isup": st.isup, "speed_mbps": st.speed, "mtu": st.mtu} if st else {}
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

# ===== MQTT publish =====
def publish_metrics():
    mqtt_stats["is_connected"] = mqtt_client.is_connected()
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
        "mqtt_stats": mqtt_stats
    }
    try:
        if mqtt_client.is_connected():
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
async def loop_psutil_fast():
    last_net = time.time()
    while True:
        metrics["memory"] = get_mem_block()
        metrics["system"] = get_system_block()
        now = time.time()
        metrics["network_io"] = get_net_io_block(max(1e-6, now - last_net))
        last_net = now
        await asyncio.sleep(1)

async def loop_psutil_slow():
    last_disk = time.time()
    while True:
        now = time.time()
        metrics["disk_io"] = get_disk_io_block(max(1e-6, now - last_disk))
        last_disk = now
        await asyncio.sleep(3)

async def loop_lhm_wmi():
    global lhm_sensors
    while True:
        metrics["cpu"] = get_cpu_base_block()
        metrics["temperatures"] = {}
        metrics["gpu"] = None
        lhm_sensors = get_lhm_wmi_data()
        if lhm_sensors:
            process_lhm_data()
        await asyncio.sleep(10) # WMI is slow, 10s is reasonable

async def loop_publish():
    while True:
        publish_metrics()
        await asyncio.sleep(1)

# ===== MAIN =====
async def main():
    print(f"🚀 Async Agent for Windows started on {HOSTNAME}")
    print("   Data source: LibreHardwareMonitor (via WMI) and psutil")
    print("   INFO: This script requires LibreHardwareMonitor to be running with Administrator privileges.")
    psutil.cpu_percent(interval=None, percpu=True)
    await asyncio.gather(
        loop_psutil_fast(),
        loop_psutil_slow(),
        loop_lhm_wmi(),
        loop_publish(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Stopped by user.")
    finally:
        mqtt_client.loop_stop()
        if mqtt_client.is_connected():
            print("🔌 Disconnecting MQTT client...")
            mqtt_client.disconnect()
        print("🔌 MQTT client disconnected.")