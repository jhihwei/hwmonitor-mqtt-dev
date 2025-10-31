"""Raspberry Pi Wi-Fi provisioning portal."""

from .webui import create_app  # re-export factory

__all__ = ["create_app"]
