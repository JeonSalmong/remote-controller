import socket
import threading
import time
import json
import sys
import os
import signal
import ctypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.protocol import pack_message, recv_message, MSG_SCREEN, MSG_AUTH, MSG_FILE, MSG_FILE_REQ, MSG_QUALITY
from common.auth import generate_pin, hash_pin, verify_pin
from host.screen_capture import ScreenCapture
from host.input_handler import InputHandler
from host.file_transfer import FileServer


class RemoteHost:
    def __init__(self, port: int = 9999, quality: int = 80, scale: float = 1.0, fps: int = 30):
        self.port = port
        self.pin = generate_pin()
        self.pin_hash = hash_pin(self.pin)
        self.capture = ScreenCapture(quality=quality, scale=scale)
        self.handler = InputHandler(scale=scale)
        self.client_conn = None
        self.running = False
        self.frame_interval = 1.0 / fps

    def start(self):
        self._stop_event = threading.Event()

        # Ctrl+C / 프로세스 종료 시그널 처리
        def _handle_signal(sig, frame):
            print("\n종료 신호 수신. 호스트를 종료합니다...")
            self._stop_event.set()

        signal.signal(signal.SIGINT,  _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', self.port))
        server.listen(1)
        server.settimeout(1.0)  # accept() 블로킹 해제 주기 (1초마다 종료 여부 확인)

        local_ip = self._get_local_ip()
        print("=" * 50)
        print("  원격 데스크톱 호스트 시작")
        print("=" * 50)
        print(f"  로컬 IP  : {local_ip}")
        print(f"  포트     : {self.port}")
        print(f"  접속 PIN : {self.pin}")
        print("=" * 50)
        print("클라이언트 연결 대기 중... (종료: Ctrl+C)")

        while not self._stop_event.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue  # 1초마다 _stop_event 확인
            except OSError:
                break

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

            # 세션 중에도 Ctrl+C 감지
            while t_screen.is_alive() and t_input.is_alive():
                if self._stop_event.is_set():
                    self.running = False
                    conn.close()
                    break
                time.sleep(0.5)

            t_screen.join(timeout=2)
            t_input.join(timeout=2)

            self.running = False
            # 다음 세션을 위해 dxcam 재시작할 수 있도록 정리
            self.capture.cleanup()
            self.capture = ScreenCapture(
                quality=self.capture.quality,
                scale=self.capture.scale
            )
            if not self._stop_event.is_set():
                print("세션 종료. 다음 연결 대기 중... (종료: Ctrl+C)")

        server.close()
        print("호스트 종료 완료.")

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
        fail_count = 0
        MAX_FAILS  = 5  # 연속 실패 허용 횟수

        while self.running:
            try:
                frame = self.capture.capture()
                self.client_conn.sendall(pack_message(MSG_SCREEN, frame))
                fail_count = 0
                time.sleep(self.frame_interval)
            except OSError as e:
                # 소켓 오류 = 연결 끊김 → 즉시 종료
                print(f"[화면전송] 소켓 오류: {e}")
                self.running = False
                break
            except Exception as e:
                fail_count += 1
                print(f"[화면전송] 캡처 오류({fail_count}/{MAX_FAILS}): {e}")
                if fail_count >= MAX_FAILS:
                    print("[화면전송] 최대 재시도 초과 - 연결 종료")
                    self.running = False
                    break
                time.sleep(0.5)  # 잠깐 대기 후 재시도

    def _recv_input(self):
        file_server = FileServer(self.client_conn)
        while self.running:
            try:
                msg_type, data = recv_message(self.client_conn)
                if msg_type in (0x02, 0x03):
                    self.handler.handle(msg_type, data)
                elif msg_type == MSG_QUALITY:
                    payload = json.loads(data.decode())
                    q = int(payload.get('quality', self.capture.quality))
                    s = float(payload.get('scale', self.capture.scale))
                    self.capture.quality = max(10, min(95, q))
                    self.capture.scale   = max(0.3, min(1.0, s))
                    self.handler.inv_scale = 1.0 / self.capture.scale
                    print(f"화질 변경: quality={self.capture.quality}, scale={self.capture.scale}")
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


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='원격 데스크톱 호스트')
    parser.add_argument('--port',    type=int,   default=9999, help='리스닝 포트 (기본: 9999)')
    parser.add_argument('--quality', type=int,   default=80,   help='JPEG 품질 1-100 (기본: 80)')
    parser.add_argument('--scale',   type=float, default=1.0,  help='화면 스케일 0.1-1.0 (기본: 1.0)')
    parser.add_argument('--fps',     type=int,   default=30,   help='목표 FPS (기본: 30)')
    args = parser.parse_args()

    if not _is_admin():
        print("=" * 50)
        print("  [경고] 관리자 권한으로 실행되지 않았습니다.")
        print("  Windows 잠금 화면 캡처 및 입력은")
        print("  관리자 권한 실행 시에만 정상 동작합니다.")
        print("  run_host.py 를 '관리자 권한으로 실행' 하세요.")
        print("=" * 50)
    else:
        from host.screen_capture import _USE_DXCAM
        if _USE_DXCAM:
            print("[정보] dxcam (DXGI) 사용 중 - 잠금 화면 캡처 지원")
        else:
            print("[경고] dxcam 미설치 - 잠금 화면 캡처 불가")
            print("       pip install dxcam  으로 설치하세요.")

    host = RemoteHost(port=args.port, quality=args.quality, scale=args.scale, fps=args.fps)
    host.start()
