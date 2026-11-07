# -*- coding: utf-8 -*-
"""aula_proto.py —— 3554:FA09 2.4G 无线键盘（AULA / MARVO / YUNZII / iLovbee 同方案）

这个接收器在 2.4G 模式下枚举成厂商接口 UsagePage=0xFF02、Usage=0x0002，
输入 / 输出报告都是 20 字节，Report ID 固定 0x13：

    13 <命令> <子命令> <序号> <15 字节数据> <校验和>
    ^^                                              ^
    Report ID                            前 19 字节之和的低 8 位

电量查询只发一条：

    13 4A 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5D

接收器回复（命令回显，最高位偶尔被置 1）：

    13 4A 01 00 02 61 01 00 ... C2     97%，电池供电
    13 4A 01 00 02 64 10 00 ... D4     插着线（充电中）

    电量 = 回复第 5 字节（0x61 = 97）
    电源状态 = 回复第 6 字节（0x01 = 电池，0x10 = 插线）

插线时接收器把电量固定成 100，所以这时不报百分比，只报“充电中”。
键盘休眠 / 没开机 / 没配对时接收器不会回复；按一下键盘再重试即可。

协议来源：AULA F75 社区的公开实现（sanshoku 的 AULA driver）以及
OpenRGB 上同一个 3554:FA09 接收器的报告。本工具只发送只读的电量查询。

注意：本模块只打开 3554:FA09 的 **2.4G 接收器**接口（0xFF02），
不会打开键盘 USB 线（258A:0199 等）上的接口。也就是说，只有在插线时
才存在的字段不会被误当成无线电量显示。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import hid_win as hw
from hid_win import HidDevice

VID = 0x3554
USAGE_PAGE = 0xFF02
REPORT_ID = 0x13
REPORT_LEN = 20
CMD_BATTERY = 0x4A

LEVEL_AT = 5
STATE_AT = 6
STATE_BATTERY = 0x01
STATE_CABLE = 0x10

RETRY_WAIT = 0.2
TIMEOUT = 0.45


def checksum(report: bytes) -> int:
    """前 19 字节之和的低 8 位。"""
    return sum(report[:REPORT_LEN - 1]) & 0xFF


def request() -> bytes:
    """电量查询请求：13 4A 00 ... 00 5D。"""
    r = bytearray(REPORT_LEN)
    r[0], r[1] = REPORT_ID, CMD_BATTERY
    r[REPORT_LEN - 1] = checksum(r)
    return bytes(r)


def is_answer(report: bytes) -> bool:
    """是不是电量查询的回复：Report ID / 命令回显 / 校验和都对。"""
    return (len(report) >= REPORT_LEN
            and report[0] == REPORT_ID
            and (report[1] & 0x7F) == CMD_BATTERY
            and checksum(report) == report[REPORT_LEN - 1])


def find_interface() -> Optional[hw.HidInterface]:
    """找到键盘接收器的厂商接口（3554:FA09 / 0xFF02 / 20 字节）。"""
    for d in hw.enumerate_hid():
        if d.vid == VID and d.usage_page == USAGE_PAGE and d.output_len == REPORT_LEN:
            return d
    for d in hw.enumerate_hid():
        if d.vid == VID and d.usage_page == USAGE_PAGE:
            return d
    return None


@dataclass
class AulaInfo:
    online: bool = False
    level: Optional[int] = None
    raw_level: Optional[int] = None
    state: Optional[int] = None
    charging: bool = False
    raw: bytes = b""
    detail: str = ""


def parse_reply(report: bytes) -> AulaInfo:
    """把一条通过校验的回复解析成 AulaInfo（无硬件时也可以单测）。"""
    if not is_answer(report):
        return AulaInfo(detail="不是 0x13/0x4A 的有效回复")
    info = AulaInfo(online=True, raw=report, state=report[STATE_AT])
    if info.state == STATE_CABLE:
        info.charging = True
        info.detail = "键盘插着线：充电中（接收器把电量固定报 100）"
    elif info.state == STATE_BATTERY:
        raw_level = report[LEVEL_AT]
        info.raw_level = raw_level
        if 1 <= raw_level <= 100:
            info.level = raw_level
            info.detail = (f"Report 0x13 / 命令 0x4A："
                           f"电量字节[5]=0x{raw_level:02X}")
        else:
            info.detail = f"回复里的电量字节 0x{raw_level:02X} 超出 1-100 范围"
    else:
        info.detail = f"收到了回复，但电源状态 0x{info.state:02X} 未知"
    return info


def read_info(iface: Optional[hw.HidInterface] = None,
              timeout: float = TIMEOUT, retries: int = 2) -> AulaInfo:
    """读取一次键盘电量。

    - 电池供电：level = 1..100，charging=False
    - 插线：level = None，charging=True（接收器把电量固定写 100，不可信）
    - 没回复：online=False，detail 提示键盘在休眠
    """
    info = AulaInfo()
    iface = iface or find_interface()
    if iface is None:
        info.detail = "没找到 2.4G 键盘接收器（3554:FA09 / 0xFF02）"
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
        info.detail = ("键盘没有回复（可能休眠 / 未配对，或这台键盘不在 2.4G "
                       "上报电量；按一下键盘再刷新）")
    except Exception as e:
        info.detail = f"读取失败：{e}"
    return info


def read_battery_only(iface: Optional[hw.HidInterface] = None,
                      timeout: float = 0.4) -> tuple[Optional[int], str]:
    """轻量读取，返回 (电量, 状态/错误说明)，适合托盘常驻轮询。"""
    info = read_info(iface, timeout=timeout, retries=2)
    if info.level is not None:
        return info.level, ""
    return None, info.detail


if __name__ == "__main__":
    i = read_info()
    print("在线:", i.online)
    print("电量:", i.level, f"(原始 {i.raw_level})")
    print("状态:", "充电中" if i.charging else i.state)
    print("报文:", i.raw.hex(" ") if i.raw else "-")
    print("说明:", i.detail)
