"""Jarvis Connect subsystem.

This package adds the local gateway, device registry, pairing flow, and
protocol definitions used by Jarvis to reach companion devices.
"""

from .service import JarvisConnectService, get_service

__all__ = ["JarvisConnectService", "get_service"]
