import os
import json
from common.protocol import pack_message, MSG_FILE


class FileServer:
    """클라이언트 요청에 따라 파일을 전송하거나, 클라이언트가 보내는 파일을 수신한다."""

    SAVE_DIR = os.path.expanduser('~/remote_desktop_received')

    def __init__(self, conn):
        self.conn = conn
        os.makedirs(self.SAVE_DIR, exist_ok=True)

    def send_file(self, filepath: str):
        """지정 파일을 클라이언트로 전송"""
        if not os.path.isfile(filepath):
            meta = json.dumps({'error': '파일 없음'}).encode()
            self.conn.sendall(pack_message(MSG_FILE, meta))
            return

        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        meta = json.dumps({'filename': filename, 'size': filesize}).encode()
        self.conn.sendall(pack_message(MSG_FILE, meta))

        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.conn.sendall(pack_message(MSG_FILE, chunk))

        self.conn.sendall(pack_message(MSG_FILE, b'<<EOF>>'))
        print(f"파일 전송 완료: {filename}")

    def receive_file(self, meta_data: bytes):
        """클라이언트가 보내는 파일 수신 (meta_data = 첫 번째 MSG_FILE 페이로드)"""
        meta = json.loads(meta_data.decode())
        if 'error' in meta:
            print(f"파일 수신 오류: {meta['error']}")
            return

        filename = meta['filename']
        save_path = os.path.join(self.SAVE_DIR, filename)

        with open(save_path, 'wb') as f:
            from common.protocol import recv_message
            while True:
                _, chunk = recv_message(self.conn)
                if chunk == b'<<EOF>>':
                    break
                f.write(chunk)

        print(f"파일 수신 완료: {save_path}")
