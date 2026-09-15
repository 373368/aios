# -*- coding: utf-8 -*-
"""wfengine 自检原语：把 argv 原样 JSON 输出到 stdout（无副作用）。"""
import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

print(json.dumps(sys.argv[1:], ensure_ascii=False))