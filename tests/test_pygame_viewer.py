from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pygame_viewer import (
    DataStore,
    DeviceView,
    compute_visible_hosts_sticky,
    compute_logical_view,
    extract_disk_rates,
    extract_network_rates,
    get_video_driver_candidates,
    paginate_devices,
    scale_color,
    sort_hosts_for_display,
)


def test_extract_network_rates_uses_max_per_nic() -> None:
    network_io = {
        "per_nic": {
            "eth0": {"rate": {"tx_bytes_per_s": 1000, "rx_bytes_per_s": 2000}},
            "wlan0": {"rate": {"tx_bytes_per_s": 1500, "rx_bytes_per_s": 1500}},
        }
    }
    up, down = extract_network_rates(network_io)
    assert up == 1500
    assert down == 2000


def test_extract_disk_rates_sums_all_devices() -> None:
    disk_io = {
        "sda": {"rate": {"read_bytes_per_s": 3000, "write_bytes_per_s": 1000}},
        "nvme0n1": {"rate": {"read_bytes_per_s": 2000, "write_bytes_per_s": 500}},
    }
    read, write = extract_disk_rates(disk_io)
    assert read == 5000
    assert write == 1500


def test_datastore_parses_current_payload_shape() -> None:
    store = DataStore()
    payload = {
        "host": "pi-a",
        "cpu": {"percent_total": 67.4},
        "memory": {"ram": {"percent": 42.1}},
        "disk_io": {
            "sda": {"rate": {"read_bytes_per_s": 1200, "write_bytes_per_s": 800}},
        },
        "network_io": {
            "per_nic": {
                "eth0": {"rate": {"tx_bytes_per_s": 3500, "rx_bytes_per_s": 9200}},
            }
        },
        "temperatures": {
            "coretemp": [{"current": 58.0}],
            "sda": [{"current": 44.0}],
        },
        "gpus": [{"temperature_celsius": 63.0}],
    }
    store.update_from_payload(payload)
    views, version = store.snapshot()
    assert version == 1
    assert len(views) == 1
    assert views[0].host == "pi-a"
    assert views[0].cpu_percent == 67.4
    assert views[0].ram_percent == 42.1
    assert views[0].cpu_temp_c == 58.0
    assert views[0].disk_temp_c == 44.0
    assert views[0].net_down_bps == 9200
    assert views[0].disk_write_bps == 800


def test_paginate_devices_returns_fixed_slots() -> None:
    devices = [
        DeviceView("a", 0, 0, None, (), 0, 0, 0, 0, None, (), (), 0),
        DeviceView("b", 0, 0, None, (), 0, 0, 0, 0, None, (), (), 0),
        DeviceView("c", 0, 0, None, (), 0, 0, 0, 0, None, (), (), 0),
        DeviceView("d", 0, 0, None, (), 0, 0, 0, 0, None, (), (), 0),
    ]
    page, count, idx = paginate_devices(devices, page_index=1, per_page=3)
    assert count == 2
    assert idx == 1
    assert [item.host if item else None for item in page] == ["d", None, None]


def test_compute_logical_view_force_portrait_rotates_landscape() -> None:
    logical_size, rotate = compute_logical_view((480, 320), force_portrait=True)
    assert logical_size == (320, 480)
    assert rotate is True


def test_compute_logical_view_keeps_portrait_when_already_portrait() -> None:
    logical_size, rotate = compute_logical_view((320, 480), force_portrait=True)
    assert logical_size == (320, 480)
    assert rotate is False


def test_compute_visible_hosts_sticky_keeps_three_slots() -> None:
    hosts = ["a", "b", "c", "d"]
    prev = ["a", "b", "c"]
    visible = compute_visible_hosts_sticky(hosts, page_index=1, prev_visible_hosts=prev, per_page=3)
    assert visible == ["d", "b", "c"]


def test_compute_visible_hosts_sticky_fills_with_available_hosts() -> None:
    hosts = ["a", "b", "c", "d", "e"]
    prev = ["a", "b", "c"]
    visible = compute_visible_hosts_sticky(hosts, page_index=1, prev_visible_hosts=prev, per_page=3)
    assert visible == ["d", "e", "c"]


def test_sort_hosts_for_display_is_stable_and_case_insensitive() -> None:
    hosts = ["zeta", "Alpha", "beta", "alpha"]
    assert sort_hosts_for_display(hosts) == ["Alpha", "alpha", "beta", "zeta"]


def test_scale_color_clamps_values() -> None:
    assert scale_color((100, 200, 240), 1.2) == (120, 240, 255)
    assert scale_color((10, 20, 30), 0.5) == (5, 10, 15)


def test_datastore_keeps_insertion_order_when_host_updates() -> None:
    store = DataStore()
    store.update_from_payload({"host": "node-a"})
    store.update_from_payload({"host": "node-b"})
    store.update_from_payload({"host": "node-a"})
    views, _ = store.snapshot()
    assert [view.host for view in views] == ["node-a", "node-b"]


def test_default_driver_prefers_kmsdrm_on_console(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    candidates = get_video_driver_candidates()
    assert candidates[0] == "kmsdrm"


def test_explicit_driver_kept_first(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("SDL_VIDEODRIVER", "fbcon")
    candidates = get_video_driver_candidates()
    assert candidates[0] == "fbcon"
