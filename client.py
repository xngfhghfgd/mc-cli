#!/usr/bin/env python3
"""Minecraft 1.18.2 CLI 客户端 — 连接、登录、聊天、基础移动"""
import asyncio
import json
import math
import time
from typing import Optional

from protocol import (
    PROTOCOL_VERSION,
    PacketIO,
    read_varint,
    write_varint,
    write_string,
    write_ushort,
    write_long,
    write_double,
    write_float,
    write_bool,
    read_string,
    read_byte,
    read_ubyte,
    read_bool,
    read_int,
    read_long,
    read_double,
    read_float,
    skip_whole_nbt,
)

class MinecraftClient:
    def __init__(self, host: str, port: int = 25565, username: str = 'HermesBot'):
        self.host = host
        self.port = port
        self.username = username
        self.packet_io: Optional[PacketIO] = None
        self.running = False
        self.on_chat = None
        self.on_disconnect = None
        self.on_ready = None
        self._entity_id = 0
        self._gamemode = 0
        self._x = 0.0
        self._y = 0.0
        self._z = 0.0
        self._yaw = 0.0
        self._pitch = 0.0
        self._on_ground = True
        self._move_task: Optional[asyncio.Task] = None
        self._move_state = {'forward': False, 'back': False, 'left': False, 'right': False}
        self._move_speed = 0.12
        self._jump_cooldown = 0.0

    async def connect(self):
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self.packet_io = PacketIO(reader, writer)
        print('  ✓ 已连接到 %s:%s' % (self.host, self.port))

    async def login(self):
        handshake_data = write_varint(PROTOCOL_VERSION) + write_string(self.host) + write_ushort(self.port) + write_varint(2)
        await self.packet_io.send_packet(0x00, handshake_data)
        await self.packet_io.send_packet(0x00, write_string(self.username))
        print('  ✓ 已发送登录请求 (用户: %s)' % self.username)
        while True:
            packet_id, data = await self.packet_io.read_packet()
            if packet_id == 0x00:
                reason_str, _ = read_string(data, 0)
                try:
                    reason = json.loads(reason_str)
                    msg = reason.get('text', reason_str)
                    if 'extra' in reason:
                        msg = ''.join(ext.get('text', '') for ext in reason['extra'])
                except json.JSONDecodeError:
                    msg = reason_str
                raise ConnectionRefusedError('登录被拒绝: %s' % msg)
            if packet_id == 0x01:
                raise NotImplementedError('服务器需要正版验证(加密登录)，仅支持离线模式服务器。')
            if packet_id == 0x02:
                uuid_hex = data[:16].hex()
                uuid_str = '-'.join([uuid_hex[:8], uuid_hex[8:12], uuid_hex[12:16], uuid_hex[16:20], uuid_hex[20:32]])
                username_str, _ = read_string(data, 16)
                print('  ✓ 登录成功！UUID: %s, 用户名: %s' % (uuid_str, username_str))
                return True
            if packet_id == 0x03:
                threshold, _ = read_varint(data, 0)
                self.packet_io.compression_threshold = threshold
                print('  ✓ 启用了压缩 (阈值: %s)' % threshold)
            if packet_id == 0x04:
                msg_id, consumed = read_varint(data, 0)
                _channel, _ = read_string(data, consumed)
                await self.packet_io.send_packet(0x02, write_varint(msg_id) + bytes([0]))
            else:
                print('  ⚠ 未知登录包 ID: 0x%02X, 跳过' % packet_id)

    async def play_loop(self):
        self.running = True
        if self.on_ready:
            self.on_ready()
        while self.running:
            try:
                packet_id, data = await self.packet_io.read_packet()
            except (ConnectionError, asyncio.IncompleteReadError) as e:
                print('\n⚠ 连接断开: %s' % e)
                self.running = False
                break
            await self._handle_packet(packet_id, data)

    async def _handle_packet(self, packet_id: int, data: bytes):
        if packet_id == 0x0E:
            json_str, offset = read_string(data, 0)
            pos, _ = read_byte(data, offset)
            try:
                msg = _parse_chat_static(json.loads(json_str))
            except json.JSONDecodeError:
                msg = json_str
            prefix = '' if pos == 0 else '[系统] '
            display = prefix + msg
            if self.on_chat:
                self.on_chat('', display)
            else:
                print('\n' + display)
                print('> ', end='', flush=True)
        elif packet_id in (0x36, 0x38):
            off = 0
            self._x, off = read_double(data, off)
            self._y, off = read_double(data, off)
            self._z, off = read_double(data, off)
            self._yaw, off = read_float(data, off)
            self._pitch, off = read_float(data, off)
            flags, off = read_byte(data, off)
            teleport_id, _ = read_varint(data, off)
            self._on_ground = bool(flags & 0x01)
            await self.packet_io.send_packet(0x00, write_varint(teleport_id))
            print('  ✓ 位置更新: (%.2f, %.2f, %.2f)' % (self._x, self._y, self._z))
        elif packet_id == 0x1A:
            reason_str, _ = read_string(data, 0)
            try:
                msg = _parse_chat_static(json.loads(reason_str))
            except json.JSONDecodeError:
                msg = reason_str
            print('\n⚠ 被服务器断开: %s' % msg)
            if self.on_disconnect:
                self.on_disconnect(msg)
            self.running = False
        elif packet_id == 0x24:
            keep_alive_id, _ = read_long(data, 0)
            await self.packet_io.send_packet(0x0F, write_long(keep_alive_id))
        elif packet_id == 0x26:
            off = 0
            self._entity_id, off = read_int(data, off)
            _, off = read_bool(data, off)
            self._gamemode, off = read_ubyte(data, off)
            _, off = read_byte(data, off)
            world_count, off = read_varint(data, off)
            for _ in range(world_count):
                _, off = read_string(data, off)
            off += skip_whole_nbt(data, off)
            off += skip_whole_nbt(data, off)
            world_name, off = read_string(data, off)
            _, off = read_long(data, off)
            _, off = read_varint(data, off)
            _, off = read_varint(data, off)
            _, off = read_varint(data, off)
            _, off = read_bool(data, off)
            _, off = read_bool(data, off)
            _, off = read_bool(data, off)
            _, off = read_bool(data, off)
            print('  ✓ 加入世界: %s (游戏模式: %s)' % (world_name, self._gamemode))

    async def send_chat(self, message: str):
        if not self.running or not self.packet_io:
            print('⚠ 未连接')
            return
        await self.packet_io.send_packet(0x03, write_string(message))

    async def _send_position(self):
        if not self.running or not self.packet_io:
            return
        payload = write_double(self._x) + write_double(self._y) + write_double(self._z) + write_bool(self._on_ground)
        await self.packet_io.send_packet(0x12, payload)

    def _direction_vector(self, direction: str):
        yaw = math.radians(self._yaw)
        sin_y = math.sin(yaw)
        cos_y = math.cos(yaw)
        forward_x, forward_z = -sin_y, cos_y
        right_x, right_z = cos_y, sin_y
        if direction == 'forward':
            return forward_x, forward_z
        if direction == 'back':
            return -forward_x, -forward_z
        if direction == 'left':
            return -right_x, -right_z
        if direction == 'right':
            return right_x, right_z
        return 0.0, 0.0

    async def set_move(self, direction: str, enabled: bool):
        if direction not in self._move_state:
            print('⚠ 不支持的方向: %s' % direction)
            return
        self._move_state[direction] = enabled
        if enabled and self._move_task is None:
            self._move_task = asyncio.create_task(self._movement_loop())
        if not any(self._move_state.values()) and self._move_task is not None:
            self._move_task.cancel()
            self._move_task = None
        print(('开始' if enabled else '停止') + ' ' + direction)

    async def stop_all_movement(self):
        for k in list(self._move_state):
            self._move_state[k] = False
        if self._move_task is not None:
            self._move_task.cancel()
            self._move_task = None
        print('✓ 已停止移动')

    async def jump_once(self):
        if not self.running or not self.packet_io:
            print('⚠ 未连接')
            return
        if time.time() < self._jump_cooldown:
            return
        self._jump_cooldown = time.time() + 0.25
        self._y += 0.42
        self._on_ground = False
        await self._send_position()
        print('✓ 跳跃')

    async def _movement_loop(self):
        try:
            while self.running and any(self._move_state.values()):
                dx = dz = 0.0
                fx, fz = self._direction_vector('forward')
                rx, rz = self._direction_vector('right')
                if self._move_state['forward']:
                    dx += fx * self._move_speed
                    dz += fz * self._move_speed
                if self._move_state['back']:
                    dx -= fx * self._move_speed
                    dz -= fz * self._move_speed
                if self._move_state['left']:
                    dx -= rx * self._move_speed
                    dz -= rz * self._move_speed
                if self._move_state['right']:
                    dx += rx * self._move_speed
                    dz += rz * self._move_speed
                self._x += dx
                self._z += dz
                await self._send_position()
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            pass
        finally:
            self._move_task = None

    async def disconnect(self):
        self.running = False
        if self._move_task is not None:
            self._move_task.cancel()
            self._move_task = None
        if self.packet_io:
            self.packet_io.close()


def ping_server(host: str, port: int = 25565, timeout: float = 5) -> dict:
    async def _ping():
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        except asyncio.TimeoutError:
            return {'error': '连接超时'}
        except Exception as e:
            return {'error': str(e)}
        io = PacketIO(reader, writer)
        try:
            handshake = write_varint(PROTOCOL_VERSION) + write_string(host) + write_ushort(port) + write_varint(1)
            await io.send_packet(0x00, handshake)
            await io.send_packet(0x00, b'')
            _, data = await io.read_packet()
            json_str, _ = read_string(data, 0)
            status = json.loads(json_str)
            start = time.time()
            ping_time = int(time.time() * 1000)
            await io.send_packet(0x01, write_long(ping_time))
            _, _ = await io.read_packet()
            latency = int((time.time() - start) * 1000)
            io.close()
            desc = status.get('description', '')
            description = _parse_chat_static(desc) if isinstance(desc, dict) else str(desc)
            players = status.get('players', {})
            version_data = status.get('version', {})
            return {'online': True, 'latency': latency, 'motd': description, 'players_online': players.get('online', 0), 'players_max': players.get('max', 0), 'version': version_data.get('name', '未知'), 'protocol': version_data.get('protocol', 0), 'raw': json_str}
        except Exception as e:
            io.close()
            return {'error': str(e)}
    return asyncio.run(_ping())


def _parse_chat_static(chat) -> str:
    if chat is None:
        return ''
    if isinstance(chat, str):
        return chat
    if isinstance(chat, list):
        return ''.join(_parse_chat_static(item) for item in chat)
    if isinstance(chat, dict):
        text = chat.get('text', '')
        if 'extra' in chat:
            text += ''.join(_parse_chat_static(ext) for ext in chat['extra'])
        if 'translate' in chat:
            with_args = chat.get('with', [])
            text = chat.get('translate', '')
            if with_args:
                text += ' [' + ', '.join(_parse_chat_static(a) for a in with_args) + ']'
        return text
    return str(chat)
