#!/usr/bin/env python3
"""通过 USART3 为 small_car_f407 更新应用固件。"""

import argparse
import binascii
import hashlib
import hmac
import os
import select
import struct
import termios
import time

SYNC = b"\xaa\x55"
VERSION = 3
MSG_ENTER = 0x06
MSG_INFO = 0x07
MSG_HELLO = 0x10
MSG_BEGIN = 0x11
MSG_DATA = 0x12
MSG_END = 0x13
MSG_BOOT = 0x14
MSG_ACK = 0x85
MSG_INFO_VALUE = 0x89
MSG_STATUS = 0x90
DEV_KEY = b"small-car-ota-dev-key-v1-change!"


class RetryableError(RuntimeError):
    pass


def crc16(data: bytes) -> int:
    value = 0xFFFF
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ 0x1021) & 0xFFFF if value & 0x8000 else (value << 1) & 0xFFFF
    return value


def frame(message: int, sequence: int, payload: bytes = b"") -> bytes:
    body = bytes((VERSION, message, sequence, len(payload))) + payload
    return SYNC + body + struct.pack("<H", crc16(body))


class SerialLink:
    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[0] & ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP |
                                termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON |
                                termios.IXOFF | termios.IXANY)
        attrs[1] = attrs[1] & ~termios.OPOST
        attrs[2] = ((attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB |
                                  getattr(termios, "CRTSCTS", 0))) |
                    termios.CS8 | termios.CLOCAL | termios.CREAD)
        attrs[3] = attrs[3] & ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def close(self):
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        os.close(self.fd)

    def reopen(self):
        self.close()
        time.sleep(0.5)
        self.__init__(self.path)

    def exchange(self, message: int, sequence: int, payload: bytes = b"", timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        outgoing = frame(message, sequence, payload)
        written = 0
        while written < len(outgoing):
            try:
                written += os.write(self.fd, outgoing[written:])
            except BlockingIOError:
                termios.tcflow(self.fd, termios.TCOON)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    termios.tcflush(self.fd, termios.TCOFLUSH)
                    raise TimeoutError(f"发送消息 0x{message:02x} 超时")
                select.select([], [self.fd], [], min(0.1, remaining))

        buffer = bytearray()
        while time.monotonic() < deadline:
            readable, _, _ = select.select([self.fd], [], [], min(0.2, deadline - time.monotonic()))
            if not readable:
                continue
            buffer.extend(os.read(self.fd, 256))
            while len(buffer) >= 8:
                sync_at = buffer.find(SYNC)
                if sync_at < 0:
                    buffer.clear()
                    break
                del buffer[:sync_at]
                if len(buffer) < 8:
                    break
                length = buffer[5]
                total = 8 + length
                if len(buffer) < total:
                    break
                packet = bytes(buffer[:total])
                del buffer[:total]
                body = packet[2:-2]
                if crc16(body) != struct.unpack("<H", packet[-2:])[0]:
                    continue
                if packet[4] != sequence:
                    continue
                return packet[3], packet[6:-2]
        raise TimeoutError(f"等待消息 0x{message:02x} 响应超时")


def expect_ack(response, request: int, accepted_offset=None):
    message, payload = response
    if message != MSG_ACK or len(payload) < 3 or payload[0] != request:
        raise RuntimeError(f"响应格式错误: msg=0x{message:02x}, payload={payload.hex()}")
    offset = struct.unpack("<I", payload[3:7])[0] if len(payload) >= 7 else 0
    if payload[2] != 0:
        # ACK 丢失后重发同一块时，MCU 会返回期望的下一偏移；视为该块已成功。
        if payload[2] == 7 and accepted_offset is not None and offset == accepted_offset:
            return
        if payload[2] == 1:
            raise RetryableError("MCU 检测到帧 CRC 错误")
        raise RuntimeError(f"MCU 拒绝请求 0x{request:02x}: 状态={payload[2]}, offset={offset}")


def decode_application_info(response):
    message, payload = response
    if message != MSG_INFO_VALUE or len(payload) != 16:
        raise RuntimeError(f"固件信息响应格式错误: msg=0x{message:02x}, payload={payload.hex()}")
    return {
        "valid": payload[0] == 1,
        "version": struct.unpack_from("<I", payload, 4)[0],
        "size": struct.unpack_from("<I", payload, 8)[0],
        "crc32": struct.unpack_from("<I", payload, 12)[0],
    }


def decode_bootloader_status(response):
    message, payload = response
    if message != MSG_STATUS:
        raise RuntimeError(f"Bootloader 状态响应错误: msg=0x{message:02x}")
    # 旧 Bootloader 的状态负载只有 9 字节，不包含当前固件信息。
    if len(payload) < 20:
        return None
    return {
        "valid": payload[1] == 1,
        "version": struct.unpack_from("<I", payload, 12)[0],
        "size": struct.unpack_from("<I", payload, 16)[0],
        "crc32": None,
    }


def print_firmware_info(info, source: str):
    if info is None:
        print(f"{source} 未提供当前固件版本（需要更新 Bootloader）")
    elif not info["valid"]:
        print(f"{source} 未检测到有效 App")
    else:
        crc = "" if info["crc32"] is None else f", CRC32=0x{info['crc32']:08X}"
        print(f"当前固件版本: {info['version']}（来源: {source}, 大小: {info['size']} 字节{crc}）")


def query_application_info(link: SerialLink, sequence: int = 1):
    return decode_application_info(link.exchange(MSG_INFO, sequence, timeout=1.0))


def enter_bootloader(link: SerialLink):
    sequence = int(time.monotonic_ns() // 1_000_000) & 0xFF
    # 与状态查询保持相同的同步顺序：先发 INFO，再用新序号发 HELLO。
    try:
        link.exchange(MSG_INFO, sequence, timeout=0.8)
    except (TimeoutError, RuntimeError):
        pass
    try:
        sequence = (sequence + 1) & 0xFF
        response = link.exchange(MSG_HELLO, sequence, timeout=0.8)
        if response[0] == MSG_STATUS:
            return response
    except (TimeoutError, RuntimeError):
        pass

    try:
        sequence = (sequence + 1) & 0xFF
        expect_ack(link.exchange(MSG_ENTER, sequence, timeout=0.8), MSG_ENTER)
    except (TimeoutError, RuntimeError):
        # MCU 复位时末尾 ACK 可能丢失，后续只用 HELLO 判断实际状态。
        pass

    # MCU 复位后重新打开 tty，丢弃 App 阶段的串口状态和残留数据。
    link.reopen()
    for attempt in range(10):
        time.sleep(0.5)
        try:
            sequence = (sequence + 1) & 0xFF
            link.exchange(MSG_INFO, sequence, timeout=0.8)
        except (TimeoutError, RuntimeError):
            pass
        try:
            sequence = (sequence + 1) & 0xFF
            response = link.exchange(MSG_HELLO, sequence, timeout=0.8)
            if response[0] == MSG_STATUS:
                return response
        except (TimeoutError, RuntimeError):
            pass
    raise RuntimeError("应用已复位，但未检测到 Bootloader")


def update(link: SerialLink, image: bytes, version: int, key: bytes):
    image_crc = binascii.crc32(image) & 0xFFFFFFFF
    manifest = struct.pack("<III", len(image), version, image_crc)
    signature = hmac.new(key, manifest + image, hashlib.sha256).digest()
    sequence = int(time.monotonic_ns() // 1_000_000) & 0xFF
    expect_ack(link.exchange(MSG_BEGIN, sequence, manifest + signature, timeout=15.0), MSG_BEGIN)
    for offset in range(0, len(image), 60):
        sequence = (sequence + 1) & 0xFF
        block = image[offset:offset + 60]
        for attempt in range(5):
            try:
                expect_ack(link.exchange(MSG_DATA, sequence, struct.pack("<I", offset) + block),
                           MSG_DATA, offset + len(block))
                time.sleep(0.005)
                break
            except (TimeoutError, RetryableError):
                if attempt == 4:
                    raise
        done = offset + len(block)
        print(f"\r传输进度: {done * 100 // len(image):3d}% ({done}/{len(image)})", end="", flush=True)
    print()
    sequence = (sequence + 1) & 0xFF
    expect_ack(link.exchange(MSG_END, sequence, timeout=4.0), MSG_END)
    sequence = (sequence + 1) & 0xFF
    try:
        expect_ack(link.exchange(MSG_BOOT, sequence, timeout=2.0), MSG_BOOT)
    except TimeoutError:
        # MCU 切换到应用会使 USB 串口末尾 ACK 丢失；END 成功已证明镜像有效。
        print("启动 ACK 未返回，MCU 可能已切换到新应用")


def main():
    parser = argparse.ArgumentParser(description="small_car_f407 MCU OTA 升级")
    parser.add_argument("firmware", nargs="?", help="small_car_f407.bin 路径")
    parser.add_argument("--device", default="/dev/small_car_mcu", help="USART3 串口设备")
    parser.add_argument("--version", type=int, help="写入 OTA 元数据的版本号（允许重复）")
    parser.add_argument("--key-file", help="32 字节 HMAC 密钥文件；未指定时使用开发密钥")
    parser.add_argument("--status", action="store_true", help="只通过串口查询当前固件版本")
    parser.add_argument("--bootloader-ready", action="store_true",
                        help="已确认处于 Bootloader 时跳过复位握手")
    args = parser.parse_args()

    if args.status and (args.firmware is not None or args.version is not None):
        parser.error("--status 不能与固件路径或 --version 同时使用")
    if args.status and args.bootloader_ready:
        parser.error("--status 不能与 --bootloader-ready 同时使用")
    if not args.status and (args.firmware is None or args.version is None):
        parser.error("升级时必须提供固件路径和 --version")
    if args.version is not None and not 0 <= args.version <= 0xFFFFFFFF:
        parser.error("--version 必须在 0 到 4294967295 之间")

    if args.status:
        link = SerialLink(args.device)
        try:
            try:
                print_firmware_info(query_application_info(link), "App 串口响应")
            except (TimeoutError, RuntimeError):
                print_firmware_info(
                    decode_bootloader_status(link.exchange(MSG_HELLO, 2, timeout=1.0)),
                    "Bootloader 串口响应",
                )
        finally:
            link.close()
        return

    image = open(args.firmware, "rb").read()
    key = open(args.key_file, "rb").read() if args.key_file else DEV_KEY
    if len(key) != 32:
        raise SystemExit("HMAC 密钥必须正好为 32 字节")
    if not args.key_file:
        print("警告：正在使用仓库内开发密钥，不可用于生产设备")

    link = SerialLink(args.device)
    try:
        if not args.bootloader_ready:
            boot_status = enter_bootloader(link)
            print_firmware_info(decode_bootloader_status(boot_status), "Bootloader 串口响应")
        print(f"Bootloader 已连接，开始写入 {len(image)} 字节")
        update(link, image, args.version, key)
        time.sleep(0.8)
        try:
            print_firmware_info(query_application_info(link, 240), "升级后 App 串口响应")
        except TimeoutError:
            print(f"升级完成，已写入版本 {args.version}；MCU 已启动新应用")
    finally:
        link.close()


if __name__ == "__main__":
    main()
