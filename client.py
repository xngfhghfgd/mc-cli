#!/usr/bin/env python3
"""Minecraft 多版本无显示 CLI 客户端 — 连接、登录、聊天、基础移动"""
import asyncio
import json
import math
from dataclasses import dataclass
import time
from typing import Optional

from protocol import (
    PacketIO,
    VersionSpec,
    detect_version_from_status,
    resolve_version,
    write_varint,
    write_string,
    write_ushort,
    write_long,
    write_double,
    write_float,
    write_bool,
    read_varint,
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


@dataclass
class ActionPlan:
    mode: str = 'idle'
    interval: float = 0.1
    count: int = 1
    delay_before: float = 0.0
    loop: bool = False
    state: str = 'stopped'


class VersionAdapter:
    def __init__(self, spec: VersionSpec):
        self.spec = spec
        self.protocol = spec.protocol
        self.name = spec.name
        self.legacy = self.protocol <= 47
        self.very_legacy = self.protocol <= 5

        if self.very_legacy:
            self.ids = {'handshake': 0x02, 'login_start': 0x01, 'login_disconnect': 0x00, 'login_encryption': None, 'login_success': 0x01, 'login_compression': None, 'login_custom_query': None, 'chat_in': 0x03, 'chat_out': 0x03, 'disconnect_play': 0x40, 'keepalive_in': 0x00, 'keepalive_out': 0x00, 'join_game': 0x01, 'player_pos': 0x0D, 'teleport_confirm': 0x00, 'server_player_pos': 0x08}
        elif self.legacy:
            self.ids = {'handshake': 0x00, 'login_start': 0x00, 'login_disconnect': 0x00, 'login_encryption': 0x01, 'login_success': 0x02, 'login_compression': None, 'login_custom_query': None, 'chat_in': 0x02, 'chat_out': 0x01, 'disconnect_play': 0x40, 'keepalive_in': 0x00, 'keepalive_out': 0x00, 'join_game': 0x01, 'player_pos': 0x04, 'teleport_confirm': 0x00, 'server_player_pos': 0x08}
        else:
            self.ids = {'handshake': 0x00, 'login_start': 0x00, 'login_disconnect': 0x00, 'login_encryption': 0x01, 'login_success': 0x02, 'login_compression': 0x03, 'login_custom_query': 0x04, 'chat_in': 0x0E, 'chat_out': 0x03, 'disconnect_play': 0x1A, 'keepalive_in': 0x24, 'keepalive_out': 0x0F, 'join_game': 0x26, 'player_pos': 0x12, 'teleport_confirm': 0x00, 'server_player_pos': 0x36}

    def handshake_payload(self, host: str, port: int, next_state: int) -> bytes:
        return write_varint(self.protocol) + write_string(host) + write_ushort(port) + write_varint(next_state)


class MinecraftClient:
    def __init__(self, host: str, port: int = 25565, username: str = 'HermesBot', version: str = None, headless: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.version = resolve_version(version)
        self.adapter = VersionAdapter(self.version)
        self.headless = headless
        self.packet_io: Optional[PacketIO] = None
        self.running = False
        self.on_chat = None
        self.on_disconnect = None
        self.on_ready = None
        self.on_raw_chat = None
        self._stdin_task: Optional[asyncio.Task] = None
        self._stdin_prompt = '> '
        self._chat_history = []
        self._max_history = 50
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
        self._move_action_task: Optional[asyncio.Task] = None
        self._click_left_task: Optional[asyncio.Task] = None
        self._click_right_task: Optional[asyncio.Task] = None
        self._click_state = {'left': ActionPlan(), 'right': ActionPlan()}
        self._keepalive_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._last_packet_at = time.time()

    def log(self, msg: str):
        if not self.headless:
            print(msg)

    async def connect(self):
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self.packet_io = PacketIO(reader, writer)
        self.log(f'  ✓ 已连接到 {self.host}:{self.port}')
        self.log(f'  ✓ 使用版本 {self.version.name} (protocol {self.version.protocol})')

    async def login(self):
        await self.packet_io.send_packet(self.adapter.ids['handshake'], self.adapter.handshake_payload(self.host, self.port, 2))
        await self.packet_io.send_packet(self.adapter.ids['login_start'], write_string(self.username))
        self.log(f'  ✓ 已发送登录请求 (用户: {self.username})')
        while True:
            packet_id, data = await self.packet_io.read_packet()
            self._last_packet_at = time.time()
            if packet_id == self.adapter.ids['login_disconnect']:
                reason_str, _ = read_string(data, 0)
                try:
                    reason = json.loads(reason_str)
                    msg = reason.get('text', reason_str)
                except json.JSONDecodeError:
                    msg = reason_str
                raise ConnectionRefusedError(f'登录被拒绝: {msg}')
            if self.adapter.ids['login_encryption'] is not None and packet_id == self.adapter.ids['login_encryption']:
                raise NotImplementedError('服务器需要正版验证(加密登录)，仅支持离线模式服务器。')
            if packet_id == self.adapter.ids['login_success']:
                if self.adapter.very_legacy:
                    uuid_hex = data[:16].hex()
                    uuid_str = '-'.join([uuid_hex[:8], uuid_hex[8:12], uuid_hex[12:16], uuid_hex[16:20], uuid_hex[20:32]])
                    username_str, _ = read_string(data, 16)
                else:
                    uuid_str, off = read_string(data, 0)
                    username_str, _ = read_string(data, off)
                self.log(f'  ✓ 登录成功！UUID: {uuid_str}, 用户名: {username_str}')
                self.running = True
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                self._watchdog_task = asyncio.create_task(self._watchdog_loop())
                self._stdin_task = asyncio.create_task(self._stdin_chat_loop())
                return True
            if self.adapter.ids['login_compression'] is not None and packet_id == self.adapter.ids['login_compression']:
                threshold, _ = read_varint(data, 0)
                self.packet_io.compression_threshold = threshold
                self.log(f'  ✓ 启用了压缩 (阈值: {threshold})')
                continue
            if self.adapter.ids['login_custom_query'] is not None and packet_id == self.adapter.ids['login_custom_query']:
                msg_id, consumed = read_varint(data, 0)
                _channel, _ = read_string(data, consumed)
                await self.packet_io.send_packet(0x02, write_varint(msg_id) + bytes([0]))
                continue
            self.log(f'  ⚠ 未知登录包 ID: 0x{packet_id:02X}, 跳过')

    async def _keepalive_loop(self):
        while self.running:
            try:
                await asyncio.sleep(30)
                if self.running and self.packet_io:
                    pass
            except asyncio.CancelledError:
                return

    async def _watchdog_loop(self):
        while self.running:
            try:
                await asyncio.sleep(30)
                if time.time() - self._last_packet_at > 90:
                    await self.disconnect()
                    return
            except asyncio.CancelledError:
                return

    async def play_loop(self):
        if self.on_ready:
            self.on_ready()
        while self.running:
            try:
                packet_id, data = await self.packet_io.read_packet()
                self._last_packet_at = time.time()
            except (ConnectionError, asyncio.IncompleteReadError) as e:
                self.log(f'\n⚠ 连接断开: {e}')
                self.running = False
                break
            await self._handle_packet(packet_id, data)

    async def _handle_packet(self, packet_id: int, data: bytes):
        if packet_id == self.adapter.ids['chat_in']:
            if self.adapter.legacy:
                json_str, offset = read_string(data, 0)
                pos, _ = read_byte(data, offset)
                try:
                    msg = _parse_chat_static(json.loads(json_str))
                except json.JSONDecodeError:
                    msg = json_str
                display = ('' if pos == 0 else '[系统] ') + msg
            else:
                json_str, _ = read_string(data, 0)
                try:
                    msg = _parse_chat_static(json.loads(json_str))
                except json.JSONDecodeError:
                    msg = json_str
                display = msg
            if self.on_chat:
                self.on_chat('', display)
            else:
                self._echo_remote_chat(display)

        elif packet_id in (self.adapter.ids['server_player_pos'], 0x38):
            off = 0
            self._x, off = read_double(data, off)
            self._y, off = read_double(data, off)
            self._z, off = read_double(data, off)
            self._yaw, off = read_float(data, off)
            self._pitch, off = read_float(data, off)
            flags, off = read_byte(data, off)
            teleport_id, _ = read_varint(data, off)
            self._on_ground = bool(flags & 0x01)
            await self.packet_io.send_packet(self.adapter.ids['teleport_confirm'], write_varint(teleport_id))

        elif packet_id == self.adapter.ids['disconnect_play']:
            reason_str, _ = read_string(data, 0)
            try:
                msg = _parse_chat_static(json.loads(reason_str))
            except json.JSONDecodeError:
                msg = reason_str
            self.log(f'\n⚠ 被服务器断开: {msg}')
            if self.on_disconnect:
                self.on_disconnect(msg)
            self.running = False

        elif packet_id == self.adapter.ids['keepalive_in']:
            keep_alive_id, _ = read_long(data, 0)
            await self.packet_io.send_packet(self.adapter.ids['keepalive_out'], write_long(keep_alive_id))

        elif packet_id == self.adapter.ids['join_game']:
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
            self.log(f'  ✓ 加入世界: {world_name} (游戏模式: {self._gamemode})')

    async def send_chat(self, message: str):
        if not self.running or not self.packet_io:
            return
        await self.packet_io.send_packet(self.adapter.ids['chat_out'], write_string(message))


    async def _send_interact_action(self, side: str = 'left'):
        if not self.running or not self.packet_io:
            return
        # 稳定性优先：点击动作在不同版本上差异很大。
        # 这里统一回退为“发送聊天占位”，避免错误协议包导致服务器断开。
        # 后续若要完善，可以按版本分别实现攻击/交互/释放使用中的正式协议包。
        msg = '[left-click]' if side == 'left' else '[right-click]'
        await self.send_chat(msg)

    def _clamp_interval(self, interval: float) -> float:
        return max(0.05, float(interval))

    async def _click_loop(self, side: str, interval: float, count: int, delay_before: float = 0.0, loop: bool = False):
        interval = self._clamp_interval(interval)
        count = max(1, int(count))
        delay_before = max(0.0, float(delay_before))
        while self.running:
            if delay_before:
                await asyncio.sleep(delay_before)
                delay_before = 0.0
            for _ in range(count):
                if not self.running:
                    return
                if side == 'left':
                    self.log('[动作] 左键')
                else:
                    self.log('[动作] 右键')
                # 这里先保留为通用动作触发点；后续可接具体交互包/方块交互
                await self._send_interact_action(side=side)
                await asyncio.sleep(interval)
            if not loop:
                return

    async def start_clicking(self, side: str, interval: float, count: int, delay_before: float = 0.0, loop: bool = False):
        if side not in ('left', 'right'):
            raise ValueError('side must be left or right')
        task_attr = '_click_left_task' if side == 'left' else '_click_right_task'
        old = getattr(self, task_attr)
        if old is not None:
            old.cancel()
        task = asyncio.create_task(self._click_loop(side, interval, count, delay_before, loop))
        setattr(self, task_attr, task)
        return task

    async def stop_clicking(self, side: str = None):
        targets = []
        if side in (None, 'left'):
            targets.append('_click_left_task')
        if side in (None, 'right'):
            targets.append('_click_right_task')
        for attr in targets:
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                setattr(self, attr, None)


    def _echo_local_chat(self, message: str):
        self._chat_history.append(message)
        if len(self._chat_history) > self._max_history:
            self._chat_history = self._chat_history[-self._max_history:]
        self.log(f'[我] {message}')

    def _echo_remote_chat(self, message: str):
        self.log(f'[服] {message}')


    def _prompted_input(self):
        try:
            return input(self._stdin_prompt)
        except (EOFError, KeyboardInterrupt):
            raise


    async def _stdin_chat_loop(self):
        loop = asyncio.get_running_loop()
        while self.running:
            try:
                line = await loop.run_in_executor(None, self._prompted_input)
            except (EOFError, KeyboardInterrupt):
                return
            msg = line.strip()
            if not msg:
                continue
            if msg.startswith('/quit') or msg == '/exit':
                await self.disconnect()
                return
            if msg.startswith('/aswd'):
                parts = msg.split()
                if len(parts) >= 3 and parts[1] in ('on', 'off'):
                    self._move_state = {'forward': parts[1] == 'on', 'back': False, 'left': False, 'right': False}
                    self.log(f'[移动] aswd={parts[1]}')
                    continue
            if msg.startswith('/click'):
                parts = msg.split()
                try:
                    side = parts[1]
                    interval = float(parts[2]) if len(parts) > 2 else 0.1
                    count = int(parts[3]) if len(parts) > 3 else 1
                    delay = float(parts[4]) if len(parts) > 4 else 0.0
                    loop_flag = len(parts) > 5 and parts[5].lower() in ('1','true','yes','loop','on')
                    await self.start_clicking(side, interval, count, delay, loop_flag)
                    self.log(f'[动作] {side} click started interval={max(0.05, interval):.2f}s count={count} delay={delay:.2f}s loop={loop_flag}')
                except Exception as e:
                    self.log(f'[动作] 参数错误: {e}')
                continue
            if msg.startswith('/stopclick'):
                parts = msg.split()
                side = parts[1] if len(parts) > 1 else None
                await self.stop_clicking(side)
                self.log('[动作] click stopped')
                continue
            self._echo_local_chat(msg)
            await self.send_chat(msg)
            if self.on_raw_chat:
                self.on_raw_chat(msg)

    async def _send_position(self):
        if not self.running or not self.packet_io:
            return
        payload = write_double(self._x) + write_double(self._y) + write_double(self._z) + write_bool(self._on_ground)
        await self.packet_io.send_packet(self.adapter.ids['player_pos'], payload)

    async def disconnect(self):
        self.running = False
        for task in (self._keepalive_task, self._move_task, self._watchdog_task, self._stdin_task, self._move_action_task, self._click_left_task, self._click_right_task):
            if task is not None:
                task.cancel()
        self._keepalive_task = self._move_task = self._watchdog_task = self._stdin_task = self._move_action_task = self._click_left_task = self._click_right_task = None
        if self.packet_io:
            self.packet_io.close()


def ping_server(host: str, port: int = 25565, timeout: float = 5, version: str = None) -> dict:
    spec = resolve_version(version)
    async def _ping():
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        except asyncio.TimeoutError:
            return {'error': '连接超时'}
        except Exception as e:
            return {'error': str(e)}
        io = PacketIO(reader, writer)
        try:
            await io.send_packet(0x00, write_varint(spec.protocol) + write_string(host) + write_ushort(port) + write_varint(1))
            await io.send_packet(0x00, b'')
            _, data = await io.read_packet()
            json_str, _ = read_string(data, 0)
            status = json.loads(json_str)
            latency_start = time.time()
            await io.send_packet(0x01, write_long(int(time.time() * 1000)))
            await io.read_packet()
            latency = int((time.time() - latency_start) * 1000)
            io.close()
            desc = status.get('description', '')
            description = _parse_chat_static(desc) if isinstance(desc, dict) else str(desc)
            players = status.get('players', {})
            version_data = status.get('version', {})
            return {'online': True, 'latency': latency, 'motd': description, 'players_online': players.get('online', 0), 'players_max': players.get('max', 0), 'version': version_data.get('name', '未知'), 'protocol': version_data.get('protocol', 0), 'resolved': detect_version_from_status(status)}
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
