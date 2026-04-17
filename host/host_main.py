import asyncio
import signal
import json
import sys
import os
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
import websockets.exceptions

from common.protocol import pack_message, unpack_message, MSG_SCREEN, MSG_AUTH, MSG_FILE, MSG_FILE_REQ, MSG_QUALITY
from common.auth import generate_pin, hash_pin, verify_pin
from host.screen_capture import ScreenCapture
from host.input_handler import InputHandler
from host.file_transfer import FileServer


class RemoteHost:
    def __init__(self, port: int = 9999, quality: int = 80, scale: float = 1.0, fps: int = 30, pin: str = ''):
        self.port = port
        self.pin = pin if pin else generate_pin()
        self.pin_hash = hash_pin(self.pin)
        self.capture = ScreenCapture(quality=quality, scale=scale)
        self.input_handler = InputHandler(scale=scale)
        self.frame_interval = 1.0 / fps

    def start(self):
        local_ip = self._get_local_ip()
        print("=" * 50)
        print("  원격 데스크톱 호스트 시작 (WebSocket)")
        print("=" * 50)
        print(f"  로컬 IP  : {local_ip}")
        print(f"  포트     : {self.port}")
        print(f"  접속 PIN : {self.pin}")
        print(f"  로컬 주소 : ws://{local_ip}:{self.port}")
        print("=" * 50)
        print("  ngrok 사용 시: ngrok http", self.port)
        print("  클라이언트 주소란에 wss://xxxx.ngrok-free.app 입력")
        print("=" * 50)
        print("클라이언트 연결 대기 중... (종료: Ctrl+C)")

        try:
            asyncio.run(self._serve())
        except KeyboardInterrupt:
            pass
        print("호스트 종료 완료.")

    async def _serve(self):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _handle_signal(signum, frame):
            print("\n종료 신호 수신. 호스트를 종료합니다...")
            loop.call_soon_threadsafe(stop.set)

        signal.signal(signal.SIGINT,  _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        async with websockets.serve(
            self._handle_client, '0.0.0.0', self.port,
            max_size=10 * 1024 * 1024,  # 10MB (고화질 프레임 대응)
            compression=None,            # JPEG 이중 압축 방지
        ):
            await stop.wait()

    async def _handle_client(self, websocket):
        addr = websocket.remote_address
        print(f"\n연결 시도: {addr}")

        if not await self._authenticate(websocket):
            print("인증 실패 - 연결 거부")
            return

        print("인증 성공! 원격 제어 세션 시작")

        screen_task = asyncio.create_task(self._send_screen(websocket))
        input_task  = asyncio.create_task(self._recv_input(websocket))

        done, pending = await asyncio.wait(
            [screen_task, input_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        print("세션 종료. 다음 연결 대기 중... (종료: Ctrl+C)")

    async def _authenticate(self, websocket) -> bool:
        try:
            data = await asyncio.wait_for(websocket.recv(), timeout=10)
            msg_type, payload = unpack_message(data)
            if msg_type != MSG_AUTH:
                return False
            info = json.loads(payload.decode())
            if verify_pin(info.get('pin', ''), self.pin_hash):
                await websocket.send(pack_message(MSG_AUTH, json.dumps({'status': 'ok'}).encode()))
                return True
            await websocket.send(pack_message(MSG_AUTH, json.dumps({'status': 'fail'}).encode()))
            return False
        except Exception as e:
            print(f"인증 오류: {e}")
            return False

    async def _send_screen(self, websocket):
        loop = asyncio.get_running_loop()
        while True:
            try:
                frame = await loop.run_in_executor(None, self.capture.capture)
                await websocket.send(pack_message(MSG_SCREEN, frame))
                await asyncio.sleep(self.frame_interval)
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                print(f"화면 전송 오류: {e}")
                break

    async def _recv_input(self, websocket):
        loop = asyncio.get_running_loop()
        file_server = FileServer(websocket)
        while True:
            try:
                data = await websocket.recv()
                msg_type, payload = unpack_message(data)

                if msg_type in (0x02, 0x03):
                    await loop.run_in_executor(None, self.input_handler.handle, msg_type, payload)
                elif msg_type == MSG_QUALITY:
                    info = json.loads(payload.decode())
                    q = int(info.get('quality', self.capture.quality))
                    s = float(info.get('scale',   self.capture.scale))
                    self.capture.quality        = max(10, min(95, q))
                    self.capture.scale          = max(0.3, min(1.0, s))
                    self.input_handler.inv_scale = 1.0 / self.capture.scale
                    print(f"화질 변경: quality={self.capture.quality}, scale={self.capture.scale}")
                elif msg_type == MSG_FILE_REQ:
                    info = json.loads(payload.decode())
                    await file_server.send_file(info['path'])
                elif msg_type == MSG_FILE:
                    await file_server.receive_file(payload)

            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                print(f"입력 수신 오류: {e}")
                break

    @staticmethod
    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='원격 데스크톱 호스트')
    parser.add_argument('--port',    type=int,   default=9999, help='리스닝 포트 (기본: 9999)')
    parser.add_argument('--quality', type=int,   default=80,   help='JPEG 품질 1-100 (기본: 80)')
    parser.add_argument('--scale',   type=float, default=1.0,  help='화면 스케일 0.1-1.0 (기본: 1.0)')
    parser.add_argument('--fps',     type=int,   default=30,   help='목표 FPS (기본: 30)')
    parser.add_argument('--pin',     type=str,   default='',   help='고정 PIN (미지정 시 랜덤 생성)')
    args = parser.parse_args()

    host = RemoteHost(port=args.port, quality=args.quality, scale=args.scale, fps=args.fps, pin=args.pin)
    host.start()
