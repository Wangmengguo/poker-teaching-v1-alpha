#!/usr/bin/env python
import os
import sys
from pathlib import Path

# 添加 packages 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
