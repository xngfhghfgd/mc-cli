#!/usr/bin/env python3
"""mc-cli — Minecraft 1.18.2 命令行客户端

用法:
    mc <服务器地址> [端口] [用户名]
    mc ping <服务器地址> [端口]

基础移动命令:
    /w /a /s /d        持续移动
    /stop              停止移动
    /jump              跳跃一次
    /j                 跳跃一次（别名）
    /q                 退出
"""
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client import MinecraftClient, ping_server

class ChatApp:
    def __init__(self, host: str, port: int, username: str):
        self.host = host
        self.port = port
        self.username = username
        self.client = MinecraftClient(host, port, username)
        self.client.on_chat = self._on_chat
        self.client.on_disconnect = self._on_disconnect
        self.client.on_ready = self._on_ready
        self._input_queue = asyncio.Queue()
        self._input_task = None

    def _on_chat(self, sender_uuid: str, message: str):
        now = datetime.now().strftime('%H:%M:%S')
        print('[' + now + '] ' + message)
        print('> ', end='', flush=True)

    def _on_disconnect(self, reason: str):
        print('已断开: ' + reason)

    def _on_ready(self):
        print('已加入游戏，输入 /q 退出')
        print('> ', end='', flush=True)

    async def _read_input(self):
        loop = asyncio.get_event_loop()
        while self.client.running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if line is None or line.strip() == '':
                    continue
                await self._input_queue.put(line.strip())
            except (EOFError, KeyboardInterrupt):
                await self._input_queue.put('/q')
                break

    async def _process_input(self):
        while self.client.running:
            text = await self._input_queue.get()
            cmd = text.lower()
            if cmd == '/q':
                await self.client.disconnect()
                break
            elif cmd in {'/jump', '/j'}:
                await self.client.jump_once()
            elif cmd in {'/forward', '/w'}:
                await self.client.set_move('forward', True)
            elif cmd in {'/back', '/s'}:
                await self.client.set_move('back', True)
            elif cmd in {'/left', '/a'}:
                await self.client.set_move('left', True)
            elif cmd in {'/right', '/d'}:
                await self.client.set_move('right', True)
            elif cmd in {'/stop', '/x'}:
                await self.client.stop_all_movement()
            elif text.startswith('/'):
                await self.client.send_chat(text)
            else:
                await self.client.send_chat(text)

    async def run(self):
        print('==== Minecraft 1.18.2 命令行客户端 ====')
        print('服务器: ' + self.host + ':' + str(self.port))
        print('用户名: ' + self.username)
        print('====================================')
        try:
            await self.client.connect()
            await self.client.login()
        except Exception as e:
            print('连接或登录失败: ' + str(e))
            return 1
        self._input_task = asyncio.create_task(self._read_input())
        input_processor = asyncio.create_task(self._process_input())
        try:
            await self.client.play_loop()
        finally:
            await self.client.disconnect()
            if self._input_task:
                self._input_task.cancel()
            input_processor.cancel()
        return 0

async def cmd_ping(host: str, port: int):
    result = await ping_server(host, port)
    print(result)
    return 0 if 'error' not in result else 1

def print_usage():
    print(__doc__)
    return 1

async def main():
    args = sys.argv[1:]
    if not args:
        return print_usage()
    if args[0] == 'ping':
        host = args[1] if len(args) > 1 else 'localhost'
        port = int(args[2]) if len(args) > 2 else 25565
        return await cmd_ping(host, port)
    host = args[0]
    port = int(args[1]) if len(args) > 1 else 25565
    username = os.environ.get('MC_USERNAME', args[2] if len(args) > 2 else 'HermesBot')
    return await ChatApp(host, port, username).run()

def entry_point():
    return asyncio.run(main())

if __name__ == '__main__':
    sys.exit(entry_point())
