#!/usr/bin/env python3
"""mc — Minecraft 1.18.2 命令行客户端入口"""
import sys
import os

# 脚本所在目录（跟随符号链接）
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)

sys.path.insert(0, os.path.join(SCRIPT_DIR, '..'))  # also check parent

from cli import entry_point

if __name__ == "__main__":
    sys.exit(entry_point())
