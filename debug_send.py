#!/usr/bin/env python3
"""调试：测试发送 Chat 包的原始字节"""
import sys, asyncio, zlib
sys.path.insert(0, '/root/mc-cli')

from protocol import resolve_version, write_varint, write_string, write_long

spec = resolve_version('1.18.2')
threshold = 256


async def send_debug():
    reader, writer = await asyncio.open_connection('localhost', 25566)

    handshake = write_varint(spec.protocol) + write_string('localhost') + b'\x00\x63' + write_varint(2)
    pkt = write_varint(len(write_varint(spec.protocol) + write_string('localhost') + b'\x00\x63' + write_varint(2) + write_varint(0))) + write_varint(0) + handshake
    writer.write(pkt)
    await writer.drain()
    print(f"Sent handshake: {pkt.hex()}")

    login = write_string('DebugBot')
    pkt2 = write_varint(len(login) + 1) + write_varint(0) + login
    writer.write(pkt2)
    await writer.drain()
    print(f"Sent login: {pkt2.hex()}")

    for i in range(5):
        length = (await reader.readexactly(1))[0]
        data = await reader.readexactly(length)
        dl, c = __import__('protocol').read_varint(data, 0)
        raw = data[c:] if dl == 0 else zlib.decompress(data[c:])
        pid, _ = __import__('protocol').read_varint(raw, 0)
        print(f"  Received: id=0x{pid:02X}")
        if pid == 2:
            break
        if pid == 3:
            threshold, _ = __import__('protocol').read_varint(data, 1)
            print(f"  Compression threshold: {threshold}")

    print(f"Logged in! Threshold: {threshold}")

    msg = "hi"
    payload = write_varint(5) + write_string(msg)
    print(f"Payload: {payload.hex()} ({len(payload)} bytes)")

    raw_pkt = write_varint(len(payload)) + payload
    writer.write(raw_pkt)
    await writer.drain()
    print(f"Sent raw: {raw_pkt.hex()}")

    if len(payload) >= threshold:
        compressed = zlib.compress(payload)
        compressed_pkt = write_varint(len(payload)) + compressed
    else:
        compressed_pkt = write_varint(0) + payload

    compressed_pkt = write_varint(len(compressed_pkt)) + compressed_pkt
    writer.write(compressed_pkt)
    await writer.drain()
    print(f"Sent compressed: {compressed_pkt.hex()}")

    await asyncio.sleep(1)
    writer.close()


asyncio.run(send_debug())
