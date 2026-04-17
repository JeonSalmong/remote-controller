import os
import json
from common.protocol import pack_message, recv_message, MSG_FILE, MSG_FILE_REQ


class FileClient:
    SAVE_DIR = os.path.expanduser('~/remote_desktop_received')

    def __init__(self, sock):
        self.sock = sock
        os.makedirs(self.SAVE_DIR, exist_ok=True)

    def send_file(self, filepath: str):
        """로컬 파일을 호스트로 전송"""
        if not os.path.isfile(filepath):
            print(f"파일 없음: {filepath}")
            return

        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        meta = json.dumps({'filename': filename, 'size': filesize}).encode()
        self.sock.sendall(pack_message(MSG_FILE, meta))

        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.sock.sendall(pack_message(MSG_FILE, chunk))

        self.sock.sendall(pack_message(MSG_FILE, b'<<EOF>>'))
        print(f"파일 전송 완료: {filename}")

    def request_file(self, remote_path: str):
        """호스트에서 파일 요청 후 수신"""
        req = json.dumps({'path': remote_path}).encode()
        self.sock.sendall(pack_message(MSG_FILE_REQ, req))

        _, meta_data = recv_message(self.sock)
        meta = json.loads(meta_data.decode())
        if 'error' in meta:
            print(f"파일 요청 오류: {meta['error']}")
            return

        filename = meta['filename']
        save_path = os.path.join(self.SAVE_DIR, filename)

        with open(save_path, 'wb') as f:
            while True:
                _, chunk = recv_message(self.sock)
                if chunk == b'<<EOF>>':
                    break
                f.write(chunk)

        print(f"파일 수신 완료: {save_path}")
