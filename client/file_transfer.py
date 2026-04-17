import asyncio
import os
import json

from common.protocol import pack_message, MSG_FILE, MSG_FILE_REQ


class FileClient:
    SAVE_DIR = os.path.expanduser('~/remote_desktop_received')

    def __init__(self, ws, loop: asyncio.AbstractEventLoop):
        self.ws = ws
        self.loop = loop
        os.makedirs(self.SAVE_DIR, exist_ok=True)

    def send_file(self, filepath: str):
        """tkinter 스레드에서 호출. 비동기 전송 스케줄."""
        asyncio.run_coroutine_threadsafe(self._send_async(filepath), self.loop)

    def request_file(self, remote_path: str):
        """tkinter 스레드에서 호출. 파일 요청 전송 (수신은 recv loop 처리)."""
        req = json.dumps({'path': remote_path}).encode()
        asyncio.run_coroutine_threadsafe(
            self.ws.send(pack_message(MSG_FILE_REQ, req)), self.loop
        )

    async def _send_async(self, filepath: str):
        if not os.path.isfile(filepath):
            print(f"파일 없음: {filepath}")
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
