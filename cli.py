#!/usr/bin/env python3
"""Minecraft 无显示 CLI 客户端入口"""
import argparse
import asyncio
import signal
import sys

from client import MinecraftClient, ping_server


def build_parser():
    p = argparse.ArgumentParser(prog='mc', description='Minecraft 无显示客户端')
    p.add_argument('host', nargs='?', help='服务器地址')
    p.add_argument('port', nargs='?', type=int, default=25565, help='端口，默认 25565')
    p.add_argument('username', nargs='?', default='HermesBot', help='用户名，默认 HermesBot')
    p.add_argument('--version', '-v', default=None, help='Minecraft 版本，如 1.20.1 / 1.8.9 / 758')
    p.add_argument('--ping', action='store_true', help='只 ping 服务器')
    p.add_argument('--auto-version', action='store_true', help='先 ping 自动识别版本再连接')
    p.add_argument('--click-left', nargs=2, metavar=('INTERVAL', 'COUNT'), help='启动后自动左键连击：间隔 秒，次数')
    p.add_argument('--click-right', nargs=2, metavar=('INTERVAL', 'COUNT'), help='启动后自动右键连击：间隔 秒，次数')
    return p


async def run_client(args):
    client = MinecraftClient(args.host, args.port, args.username, version=args.version, headless=True)
    await client.connect()
    await client.login()
    if args.click_left:
        await client.start_clicking('left', float(args.click_left[0]), int(args.click_left[1]), loop=True)
    if args.click_right:
        await client.start_clicking('right', float(args.click_right[0]), int(args.click_right[1]), loop=True)
    await client.play_loop()


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.ping:
        if not args.host:
            parser.error('ping 模式需要 host')
        print(ping_server(args.host, args.port, version=args.version))
        return 0

    if not args.host:
        parser.print_help()
        return 1

    if args.auto_version and not args.version:
        info = ping_server(args.host, args.port)
        resolved = info.get('resolved')
        if resolved:
            args.version = resolved
            print(f'auto version -> {resolved}')
        else:
            print('auto version failed, use default')

    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    try:
        asyncio.run(run_client(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
