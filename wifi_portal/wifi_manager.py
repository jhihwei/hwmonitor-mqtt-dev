"""Wi-Fi configuration helpers for Raspberry Pi OS.

This module reads and updates ``wpa_supplicant`` configuration files and
interacts with ``nmcli``/``wpa_cli`` to query or refresh wireless state.
All filesystem paths and interfaces are parameterised so the functions are
testable without needing actual hardware.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


class WifiCommandError(RuntimeError):
    """Raised when a system command related to Wi-Fi management fails."""


class WifiManager:
    """High level helpers for Raspberry Pi Wi-Fi configuration."""

    def __init__(
        self,
        config_path: Path | str = "/etc/wpa_supplicant/wpa_supplicant.conf",
        interface: str = "wlan0",
        backup_suffix: str = ".bak",
    ) -> None:
        self.config_path = Path(config_path)
        self.interface = interface
        self.backup_suffix = backup_suffix

    # ------------------------------------------------------------------
    # wpa_supplicant.conf utilities
    # ------------------------------------------------------------------
    def list_configured_networks(self) -> List[Dict[str, Optional[str]]]:
        """Parse configured networks from ``wpa_supplicant.conf``.

        Returns a list of dictionaries containing SSID, key management and
        whether the network is hidden. Passwords are not exposed for safety.
        """

        if not self.config_path.exists():
            return []

        networks: List[Dict[str, Optional[str]]] = []
        current: Dict[str, Optional[str]] = {}
        inside_network = False

        for line in self.config_path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue

            if stripped.startswith("network={"):
                inside_network = True
                current = {}
                continue

            if inside_network and stripped == "}":
                networks.append(current)
                inside_network = False
                current = {}
                continue

            if not inside_network:
                continue

            if "=" not in stripped:
                continue

            key, value = (part.strip() for part in stripped.split("=", 1))
            value = value.strip('"')  # remove optional quotes

            if key == "ssid":
                current["ssid"] = value
            elif key == "key_mgmt":
                current["key_mgmt"] = value
            elif key == "psk":
                current["has_psk"] = "yes"
            elif key == "scan_ssid":
                current["hidden"] = "yes" if value == "1" else "no"

        return networks

    def add_network(self, ssid: str, psk: str, hidden: bool = False) -> None:
        """Append a new network block to the configuration file."""

        if not ssid:
            raise ValueError("SSID cannot be empty")

        block = ["network={",
                 f"    ssid=\"{ssid}\"",
                 f"    psk=\"{psk}\"",
                 "    key_mgmt=WPA-PSK",
                 ]
        if hidden:
            block.append("    scan_ssid=1")
        block.append("}")

        config_text = "\n".join(block) + "\n"

        if self.config_path.exists():
            backup_path = self.config_path.with_suffix(self.config_path.suffix + self.backup_suffix)
            shutil.copy2(self.config_path, backup_path)

        with self.config_path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + config_text)

    # ------------------------------------------------------------------
    # nmcli helpers
    # ------------------------------------------------------------------
    def scan_networks(self) -> List[Dict[str, Optional[str]]]:
        """Return available Wi-Fi networks using ``nmcli`` output."""

        cmd = [
            "nmcli",
            "-t",
            "-f",
            "SSID,SIGNAL,SECURITY",
            "dev",
            "wifi",
            "list",
            "ifname",
            self.interface,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise WifiCommandError(result.stderr.strip() or "Failed to scan networks")

        networks: List[Dict[str, Optional[str]]] = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            parts = line.split(":")
            ssid, signal, security = (parts + [None, None, None])[:3]
            networks.append(
                {
                    "ssid": ssid or None,
                    "signal": signal or None,
                    "security": security or None,
                }
            )

        return networks

    def current_connection(self) -> Dict[str, Optional[str]]:
        """Return information about the current connection via ``nmcli``."""

        cmd = [
            "nmcli",
            "-t",
            "-f",
            "GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY",
            "device",
            "show",
            self.interface,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise WifiCommandError(result.stderr.strip() or "Failed to get connection info")

        info: Dict[str, Optional[str]] = {
            "connection": None,
            "ip": None,
            "gateway": None,
        }

        for line in result.stdout.splitlines():
            if not line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip() or None
            if key.endswith("connection"):
                info["connection"] = value
            elif key.endswith("ip4.address"):
                info["ip"] = value
            elif key.endswith("ip4.gateway"):
                info["gateway"] = value

        return info

    def reconfigure(self) -> None:
        """Ask ``wpa_supplicant`` to reload configuration via ``wpa_cli``."""

        cmd = ["wpa_cli", "-i", self.interface, "reconfigure"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise WifiCommandError(result.stderr.strip() or "Failed to reconfigure Wi-Fi")


def nmcli_json_scan(interface: str = "wlan0") -> List[Dict[str, Optional[str]]]:
    """Convenience helper to read nmcli JSON output."""

    cmd = ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "--mode", "multiline", "dev", "wifi", "list", "ifname", interface]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise WifiCommandError(result.stderr.strip() or "Failed to scan networks")

    parsed: List[Dict[str, Optional[str]]] = []
    current: Dict[str, Optional[str]] = {}
    for line in result.stdout.splitlines():
        if not line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip() or None
        if key == "ssid":
            if current:
                parsed.append(current)
                current = {}
            current["ssid"] = value
        elif key == "signal":
            current["signal"] = value
        elif key == "security":
            current["security"] = value
    if current:
        parsed.append(current)
    return parsed


__all__ = ["WifiManager", "WifiCommandError", "nmcli_json_scan"]
