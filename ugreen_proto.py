# -*- coding: utf-8 -*-
"""ugreen_proto.py —— UGREEN 2.4G 无线鼠标（2B89:0043）电量读取

协议靠在本机接收器上直接探测得到：厂商接口 UsagePage=0xFFB5，
Report ID 0xB5，固定 8 字节报文。查询电量的请求是：

    B5 01 00 00 00 00 00 00

接收器回复（7 字节数据，第 0 字节是 Report ID）：

    B5 01 01 38 43 07 00 48
          ^^ ^^
          |  电量百分比（0x38 = 56%）
          状态：0x01 = 有效回复

第 3 字节（从 0 开始数）就是电量。后面的字节随鼠标配置/状态变化，
不作为电量使用；如果第 2 字节不是 0x01，视为无效回复，不猜测。

同一个厂商接口上还有 0x02/0x05（读配置块）、0x04（状态）、0x20（DPI）
等命令，本工具只发送 0x01 这一条只读的电量查询。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import hid_win as hw
from hid_win import HidDevice

VID = 0x2B89
USAGE_PAGE = 0xFFB5
REPORT_ID = 0xB5
REPORT_LEN = 8
CMD_STATUS = 0x01

LEVEL_AT = 3
STATUS_AT = 2
STATUS_OK = 0x01

RETRY_WAIT = 0.12
TIMEOUT = 0.4


def request() -> bytes:
    """电量查询请求：B5 01 00 00 00 00 00 00。"""
    r = bytearray(REPORT_LEN)
    r[0] = REPORT_ID
    r[1] = CMD_STATUS
    return bytes(r)


def is_answer(report: bytes) -> bool:
    """判断是不是 0x01 命令的有效回复。"""
    return (len(report) >= REPORT_LEN
            and report[0] == REPORT_ID
            and report[1] == CMD_STATUS
            and report[STATUS_AT] == STATUS_OK)


def find_interface() -> Optional[hw.HidInterface]:
    """找到 UGREEN 接收器的厂商接口（0xFFB5:0x0001，8 字节）。"""
    for d in hw.enumerate_hid():
        if d.vid == VID and d.usage_page == USAGE_PAGE and d.output_len == REPORT_LEN:
            return d
    for d in hw.enumerate_hid():
        if d.vid == VID and d.usage_page == USAGE_PAGE:
            return d
    return None


@dataclass
class UgreenInfo:
    online: bool = False
    level: Optional[int] = None
    raw_level: Optional[int] = None
    raw: bytes = b""
    detail: str = ""


def parse_reply(report: bytes) -> UgreenInfo:
    """把一条有效回复解析成 UgreenInfo（无硬件时也可以单测）。"""
    if not is_answer(report):
        return UgreenInfo(detail="不是 0xB5/0x01 的有效回复")
    raw_level = report[LEVEL_AT]
    info = UgreenInfo(online=True, raw=report, raw_level=raw_level)
    if 0 <= raw_level <= 100:
        info.level = raw_level
        info.detail = f"Report 0xB5 / 命令 0x01：电量字节[3]=0x{raw_level:02X}"
    else:
        info.detail = f"回复里的电量字节 0x{raw_level:02X} 超出 0-100 范围"
    return info


def read_info(iface: Optional[hw.HidInterface] = None,
              timeout: float = TIMEOUT, retries: int = 3) -> UgreenInfo:
    """读取一次鼠标电量。

    返回的 level 为 0-100；接收器没回复（鼠标休眠 / 没电 / 未配对）时
    online=False，detail 里给出可读的原因。
    """
    info = UgreenInfo()
    iface = iface or find_interface()
    if iface is None:
        info.detail = "没找到 UGREEN 鼠标接收器（2B89:0043 / 0xFFB5）"
        return info
    try:
        with HidDevice(iface.path, write=True) as dev:
            for attempt in range(max(1, retries)):
                if dev.caps.InputReportByteLength:
                    dev.drain()
                dev.write_output(request())
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    r = dev.read_input(timeout_ms=100)
                    if not r or not is_answer(r):
                        continue
                    return parse_reply(r)
                if attempt + 1 < retries:
                    time.sleep(RETRY_WAIT)
        info.detail = "鼠标没有回复（动一下鼠标或换一节电池后重试）"
    except Exception as e:
        info.detail = f"读取失败：{e}"
    return info


def read_battery_only(iface: Optional[hw.HidInterface] = None,
                      timeout: float = TIMEOUT) -> tuple[Optional[int], str]:
    """轻量读取，返回 (电量, 错误说明)，适合托盘常驻轮询。"""
    info = read_info(iface, timeout=timeout, retries=2)
    return info.level, ("" if info.level is not None else info.detail)


if __name__ == "__main__":
    i = read_info()
    print("在线:", i.online)
    print("电量:", i.level, f"(原始 {i.raw_level})")
    print("报文:", i.raw.hex(" ") if i.raw else "-")
    print("说明:", i.detail)
