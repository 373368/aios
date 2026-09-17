# -*- coding: utf-8 -*-
"""plugin kind 参考实现：模块暴露 TOOL / TOOLS / get_tools() 之一即可。

契约：工具名与注册表条目 name 一致；调用返回文本，失败以 "ERROR:" 开头。
"""
from datetime import datetime

from langchain_core.tools import tool


@tool
def local_time() -> str:
    """返回本机当前日期时间（本地时区，格式 YYYY-MM-DD HH:MM:SS）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


TOOL = local_time
