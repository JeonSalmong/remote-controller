import mss
import threading
from PIL import Image
import io


class ScreenCapture:
    def __init__(self, quality: int = 50, scale: float = 0.75):
        self.quality = quality
        self.scale = scale
        self._local = threading.local()

    def _get_sct(self):
        # mss 인스턴스는 스레드 로컬로 관리 (스레드 간 공유 불가)
        if not hasattr(self._local, 'sct'):
            self._local.sct = mss.mss()
        return self._local.sct

    def capture(self) -> bytes:
        sct = self._get_sct()
        screenshot = sct.grab(sct.monitors[1])
        img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')

        w, h = img.size
        img = img.resize((int(w * self.scale), int(h * self.scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=self.quality, optimize=True)
        return buf.getvalue()

    def get_screen_size(self) -> tuple:
        sct = self._get_sct()
        monitor = sct.monitors[1]
        w = int(monitor['width'] * self.scale)
        h = int(monitor['height'] * self.scale)
        return w, h
