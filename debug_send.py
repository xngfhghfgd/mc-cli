#!/usr/bin/env python3
"""调试：测试发送 Chat 包的原始字节"""
import sys, asyncio, struct, zlib
sys.path.insert(0, '/root/mc-cli')

from protocol import write_varint, write_string, write_long

# 模拟 send_packet 的压缩逻辑
threshold = 256

async def send_debug():
    reader, writer = await asyncio.open_connection('localhost', 25566)
    
    # 1. Handshake
    handshake = write_varint(758) + write_string('localhost') + b'\x00\x63' + write_varint(2)
    pkt = write_varint(len(handshake) + 1) + write_varint(0) + handshake
    writer.write(pkt)
    await writer.drain()
    print(f"Sent handshake: {pkt.hex()}")
    
    # 2. Login Start
    login = write_string('DebugBot')
    pkt2 = write_varint(len(login) + 1) + write_varint(0) + login
    writer.write(pkt2)
    await writer.drain()
    print(f"Sent login: {pkt2.hex()}")
    
    # 3. Read until Login Success
    for i in range(5):
        length = (await reader.readexactly(1))[0]
        data = await reader.readexactly(length)
        dl, c = __import__('protocol').read_varint(data, 0)
        raw = data[c:] if dl == 0 else zlib.decompress(data[c:])
        pid, _ = __import__('protocol').read_varint(raw, 0)
        print(f"  Received: id=0x{pid:02X}")
        if pid == 2:  # Login Success
            break
        if pid == 3:  # Set Compression
            threshold, _ = __import__('protocol').read_varint(data, 1)
            print(f"  Compression threshold: {threshold}")
    
    print(f"Logged in! Threshold: {threshold}")
    
    # 4. Test sending a simple packet without compression
    msg = "hi"
    payload = write_varint(5) + write_string(msg)
    print(f"Payload: {payload.hex()} ({len(payload)} bytes)")
    
    # 不压缩直接发送
    raw_pkt = write_varint(len(payload)) + payload
    writer.write(raw_pkt)
    await writer.drain()
    print(f"Sent raw: {raw_pkt.hex()}")
    
    # 压缩发送（模拟 send_packet 行为）
    compressed_pkt = b''
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
