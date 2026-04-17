import asyncio
import os
import json

from common.protocol import pack_message, unpack_message, MSG_FILE


class FileServer:
    SAVE_DIR = os.path.expanduser('~/remote_desktop_received')

    def __init__(self, websocket):
        self.ws = websocket
        os.makedirs(self.SAVE_DIR, exist_ok=True)

    async def send_file(self, filepath: str):
        if not os.path.isfile(filepath):
            meta = json.dumps({'error': '파일 없음'}).encode()
            await self.ws.send(pack_message(MSG_FILE, meta))
            return

        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        meta = json.dumps({'filename': filename, 'size': filesize}).encode()
        await self.ws.send(pack_message(MSG_FILE, meta))

        loop = asyncio.get_running_loop()
        with open(filepath, 'rb') as f:
            while True:
                chunk = await loop.run_in_executor(None, f.read, 65536)
                if not chunk:
                    break
                await self.ws.send(pack_message(MSG_FILE, chunk))

        await self.ws.send(pack_message(MSG_FILE, b'<<EOF>>'))
        print(f"파일 전송 완료: {filename}")

    async def receive_file(self, meta_data: bytes):
        meta = json.loads(meta_data.decode())
        if 'error' in meta:
            print(f"파일 수신 오류: {meta['error']}")
            return

        filename = meta['filename']
        save_path = os.path.join(self.SAVE_DIR, filename)

        loop = asyncio.get_running_loop()
        with open(save_path, 'wb') as f:
            while True:
                data = await self.ws.recv()
                _, chunk = unpack_message(data)
                if chunk == b'<<EOF>>':
                    break
                await loop.run_in_executor(None, f.write, chunk)

        print(f"파일 수신 완료: {save_path}")
