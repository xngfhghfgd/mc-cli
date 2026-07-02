#!/usr/bin/env python3
"""Minecraft 1.18.2 (protocol 758) 核心协议实现"""
import struct
import zlib
from typing import Tuple

PROTOCOL_VERSION = 758  # 1.18.2
STATE_HANDSHAKING = 0
STATE_STATUS = 1
STATE_LOGIN = 2
STATE_PLAY = 3

# ==================== VarInt / VarLong ====================

def write_varint(value: int) -> bytes:
    """将整数编码为 VarInt"""
    out = bytearray()
    while True:
        temp = value & 0x7F
        value >>= 7
        if value != 0:
            temp |= 0x80
        out.append(temp)
        if not (temp & 0x80):
            break
    return bytes(out)

def read_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """从字节中读取 VarInt → (值, 新的绝对位置)"""
    value = 0
    pos = 0
    while True:
        if offset + pos >= len(data):
            raise ValueError("VarInt 数据不足")
        byte = data[offset + pos]
        value |= (byte & 0x7F) << (pos * 7)
        pos += 1
        if not (byte & 0x80):
            break
        if pos > 5:
            raise ValueError("VarInt 过长")
    return value, offset + pos

async def read_varint_stream(reader) -> Tuple[int, int]:
    """从 StreamReader 中读取 VarInt → (值, 消耗字节数)"""
    value = 0
    pos = 0
    while True:
        byte = await reader.readexactly(1)
        value |= (byte[0] & 0x7F) << (pos * 7)
        pos += 1
        if not (byte[0] & 0x80):
            break
        if pos > 5:
            raise ValueError("VarInt 过长")
    return value, pos

# ==================== 基本类型读写 ====================

def write_string(s: str) -> bytes:
    """写入 Minecraft 字符串 (VarInt 长度前缀 + UTF-8)"""
    encoded = s.encode('utf-8')
    return write_varint(len(encoded)) + encoded

def read_string(data: bytes, offset: int = 0) -> Tuple[str, int]:
    """读取 Minecraft 字符串 → (字符串, 新的绝对位置)"""
    length, consumed = read_varint(data, offset)
    start = consumed  # consumed now = old offset + varint_size = absolute position
    end = start + length
    if end > len(data):
        raise ValueError(f"字符串数据不足: need {end}, have {len(data)}")
    return data[start:end].decode('utf-8'), end

def write_short(value: int) -> bytes:
    return struct.pack('>h', value)

def write_ushort(value: int) -> bytes:
    return struct.pack('>H', value)

def write_int(value: int) -> bytes:
    return struct.pack('>i', value)

def write_long(value: int) -> bytes:
    return struct.pack('>q', value)

def write_double(value: float) -> bytes:
    return struct.pack('>d', value)

def write_float(value: float) -> bytes:
    return struct.pack('>f', value)

def write_bool(value: bool) -> bytes:
    return b'\x01' if value else b'\x00'

def write_byte(value: int) -> bytes:
    return struct.pack('>b', value)

def write_ubyte(value: int) -> bytes:
    return struct.pack('>B', value)

def read_byte(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return data[offset] if data[offset] < 128 else data[offset] - 256, offset + 1

def read_ubyte(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return data[offset], offset + 1

def read_bool(data: bytes, offset: int = 0) -> Tuple[bool, int]:
    return data[offset] != 0, offset + 1

def read_short(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return struct.unpack_from('>h', data, offset)[0], offset + 2

def read_ushort(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return struct.unpack_from('>H', data, offset)[0], offset + 2

def read_int(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return struct.unpack_from('>i', data, offset)[0], offset + 4

def read_long(data: bytes, offset: int = 0) -> Tuple[int, int]:
    return struct.unpack_from('>q', data, offset)[0], offset + 8

def read_double(data: bytes, offset: int = 0) -> Tuple[float, int]:
    return struct.unpack_from('>d', data, offset)[0], offset + 8

def read_float(data: bytes, offset: int = 0) -> Tuple[float, int]:
    return struct.unpack_from('>f', data, offset)[0], offset + 4

def read_uuid(data: bytes, offset: int = 0) -> Tuple[str, int]:
    """读取 UUID (16 字节) → (UUID 字符串, 消耗字节数)"""
    import uuid as uuid_mod
    u = uuid_mod.UUID(bytes=data[offset:offset+16])
    return str(u), offset + 16


# ==================== 简化 NBT 解析器 ====================
# 只解析我们需要的部分：读取整个 NBT payload 并跳过

NBT_TAG_END = 0
NBT_TAG_BYTE = 1
NBT_TAG_SHORT = 2
NBT_TAG_INT = 3
NBT_TAG_LONG = 4
NBT_TAG_FLOAT = 5
NBT_TAG_DOUBLE = 6
NBT_TAG_BYTE_ARRAY = 7
NBT_TAG_STRING = 8
NBT_TAG_LIST = 9
NBT_TAG_COMPOUND = 10
NBT_TAG_INT_ARRAY = 11
NBT_TAG_LONG_ARRAY = 12

def _nbt_skip_payload(data: bytes, offset: int, tag_type: int) -> int:
    """跳过 NBT payload（不含类型和名称），返回消耗的字节数"""
    if tag_type <= NBT_TAG_END:
        return 0
    elif tag_type == NBT_TAG_BYTE:
        return 1
    elif tag_type == NBT_TAG_SHORT:
        return 2
    elif tag_type == NBT_TAG_INT:
        return 4
    elif tag_type == NBT_TAG_LONG:
        return 8
    elif tag_type == NBT_TAG_FLOAT:
        return 4
    elif tag_type == NBT_TAG_DOUBLE:
        return 8
    elif tag_type == NBT_TAG_BYTE_ARRAY:
        length = struct.unpack_from('>i', data, offset)[0]
        return 4 + length
    elif tag_type == NBT_TAG_STRING:
        length = (data[offset] << 8) | data[offset + 1]
        return 2 + length
    elif tag_type == NBT_TAG_LIST:
        inner = data[offset]
        length = struct.unpack_from('>i', data, offset + 1)[0]
        total = 1 + 4
        for _ in range(length):
            total += _nbt_skip_payload(data, offset + total, inner)
        return total
    elif tag_type == NBT_TAG_COMPOUND:
        total = 0
        while True:
            bt = data[offset + total]
            if bt == NBT_TAG_END:
                return total + 1
            total += _nbt_skip_tag(data, offset + total)
        raise ValueError("COMPOUND missing TAG_End")
    elif tag_type == NBT_TAG_INT_ARRAY:
        length = struct.unpack_from('>i', data, offset)[0]
        return 4 + length * 4
    elif tag_type == NBT_TAG_LONG_ARRAY:
        length = struct.unpack_from('>i', data, offset)[0]
        return 4 + length * 8
    # --- 调试: 遇到未知类型时的上下文 ---
    ctx = data[max(0,offset-20):offset+20].hex()
    raise ValueError(f"未知 NBT 类型: {tag_type} (0x{tag_type:02X}) @ offset {offset}, ctx={ctx}")

def _nbt_skip_tag(data: bytes, offset: int) -> int:
    """跳过带类型+名称的 NBT 标签，返回总消耗"""
    t = data[offset]
    if t == NBT_TAG_END:
        return 1
    # 手动读 ushort（不能用 read_ushort，它返回绝对位置而非消耗数）
    name_len = (data[offset + 1] << 8) | data[offset + 2]
    tag_start = 1 + 2 + name_len  # type(1) + ushort(2) + name
    payload_size = _nbt_skip_payload(data, offset + tag_start, t)
    return tag_start + payload_size

def skip_whole_nbt(data: bytes, offset: int = 0) -> int:
    """跳过整个根 NBT 结构(含根名)，返回消耗的字节数"""
    return _nbt_skip_tag(data, offset)


# ==================== 包 (Packet) 读写 ====================

class PacketIO:
    """Minecraft 协议层的包读写器"""
    
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.compression_threshold = -1  # -1 = 无压缩
    
    async def send_packet(self, packet_id: int, data: bytes = b''):
        """发送一个 Minecraft 包（直接写底层transport）"""
        payload = write_varint(packet_id) + data
        
        if self.compression_threshold >= 0:
            if len(payload) >= self.compression_threshold:
                compressed = zlib.compress(payload, level=6, wbits=-zlib.MAX_WBITS)
                final_payload = write_varint(len(payload)) + compressed
            else:
                final_payload = write_varint(0) + payload
        else:
            final_payload = payload
        
        length_prefix = write_varint(len(final_payload))
        self.writer.transport.write(length_prefix + final_payload)
    
    async def read_packet(self) -> Tuple[int, bytes]:
        """读取一个 Minecraft 包 → (packet_id, data)"""
        # 读取包长度
        packet_length = (await read_varint_stream(self.reader))[0]
        
        # 读取包体
        data = b''
        while len(data) < packet_length:
            chunk = await self.reader.read(packet_length - len(data))
            if not chunk:
                raise ConnectionError("连接已关闭")
            data += chunk
        
        if self.compression_threshold >= 0:
            # 解压缩
            data_length, consumed = read_varint(data, 0)
            uncompressed = data[consumed:]
            if data_length > 0:
                uncompressed = zlib.decompress(uncompressed)
            
            packet_id, p_consumed = read_varint(uncompressed, 0)
            return packet_id, uncompressed[p_consumed:]
        
        # 无压缩
        packet_id, consumed = read_varint(data, 0)
        return packet_id, data[consumed:]
    
    def close(self):
        if self.writer:
            self.writer.close()
