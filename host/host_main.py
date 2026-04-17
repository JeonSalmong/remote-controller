import socket
import threading
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.protocol import pack_message, recv_message, MSG_SCREEN, MSG_AUTH, MSG_FILE, MSG_FILE_REQ
from common.auth import generate_pin, hash_pin, verify_pin
from host.screen_capture import ScreenCapture
from host.input_handler import InputHandler
from host.file_transfer import FileServer


class RemoteHost:
    def __init__(self, port: int = 9999, quality: int = 50, scale: float = 0.75, fps: int = 30):
        self.port = port
        self.pin = generate_pin()
        self.pin_hash = hash_pin(self.pin)
        self.capture = ScreenCapture(quality=quality, scale=scale)
        self.handler = InputHandler()
        self.client_conn = None
        self.running = False
        self.frame_interval = 1.0 / fps

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', self.port))
        server.listen(1)

        local_ip = self._get_local_ip()
        print("=" * 50)
        print("  원격 데스크톱 호스트 시작")
        print("=" * 50)
        print(f"  로컬 IP  : {local_ip}")
        print(f"  포트     : {self.port}")
        print(f"  접속 PIN : {self.pin}")
        print("=" * 50)
        print("클라이언트 연결 대기 중...")

        while True:
            try:
                conn, addr = server.accept()
                print(f"\n연결 시도: {addr}")
                if not self._authenticate(conn):
                    print("인증 실패 - 연결 거부")
                    conn.close()
                    continue

                self.client_conn = conn
                self.running = True
                print("인증 성공! 원격 제어 세션 시작")

                t_screen = threading.Thread(target=self._send_screen, daemon=True)
                t_input  = threading.Thread(target=self._recv_input,  daemon=True)
                t_screen.start()
                t_input.start()
                t_screen.join()
                t_input.join()

                print("세션 종료. 다음 연결 대기 중...")
                self.running = False
            except KeyboardInterrupt:
                print("\n호스트 종료")
                server.close()
                break

    def _authenticate(self, conn) -> bool:
        try:
            msg_type, data = recv_message(conn)
            if msg_type != MSG_AUTH:
                return False
            payload = json.loads(data.decode())
            if verify_pin(payload.get('pin', ''), self.pin_hash):
                conn.sendall(pack_message(MSG_AUTH, json.dumps({'status': 'ok'}).encode()))
                return True
            conn.sendall(pack_message(MSG_AUTH, json.dumps({'status': 'fail'}).encode()))
            return False
        except Exception as e:
            print(f"인증 오류: {e}")
            return False

    def _send_screen(self):
        while self.running:
            try:
                frame = self.capture.capture()
                self.client_conn.sendall(pack_message(MSG_SCREEN, frame))
                time.sleep(self.frame_interval)
            except Exception as e:
                print(f"화면 전송 오류: {e}")
                self.running = False
                break

    def _recv_input(self):
        file_server = FileServer(self.client_conn)
        while self.running:
            try:
                msg_type, data = recv_message(self.client_conn)
                if msg_type in (0x02, 0x03):
                    self.handler.handle(msg_type, data)
                elif msg_type == MSG_FILE_REQ:
                    payload = json.loads(data.decode())
                    file_server.send_file(payload['path'])
                elif msg_type == MSG_FILE:
                    file_server.receive_file(data)
            except Exception as e:
                print(f"입력 수신 오류: {e}")
                self.running = False
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
    parser.add_argument('--port',    type=int,   default=9999,  help='리스닝 포트 (기본: 9999)')
    parser.add_argument('--quality', type=int,   default=50,    help='JPEG 품질 1-100 (기본: 50)')
    parser.add_argument('--scale',   type=float, default=0.75,  help='화면 스케일 0.1-1.0 (기본: 0.75)')
    parser.add_argument('--fps',     type=int,   default=30,    help='목표 FPS (기본: 30)')
    args = parser.parse_args()

    host = RemoteHost(port=args.port, quality=args.quality, scale=args.scale, fps=args.fps)
    host.start()
