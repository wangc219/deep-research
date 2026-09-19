#!/usr/bin/env python3
"""Compatibility entry point; protocol logic is provider-neutral."""
from __future__ import annotations

import os
import runpy
from pathlib import Path

os.environ.setdefault("EQUIPMENT_DR_BRIDGE_UPSTREAM_URL", os.environ.get("EQUIPMENT_DR_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions"))
os.environ.setdefault("EQUIPMENT_DR_BRIDGE_API_KEY_ENV", os.environ.get("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", "DEEPSEEK_API_KEY"))
os.environ.setdefault("EQUIPMENT_DR_BRIDGE_MODEL", os.environ.get("EQUIPMENT_DR_DEEPSEEK_MODEL", ""))
runpy.run_path(str(Path(__file__).with_name("responses_chat_bridge.py")), run_name="__main__")
