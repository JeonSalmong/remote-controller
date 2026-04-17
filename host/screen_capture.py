import mss
import threading
from PIL import Image
import io


class ScreenCapture:
    def __init__(self, quality: int = 80, scale: float = 1.0):
        self._quality = quality
        self._scale = scale
        self._lock = threading.Lock()
        self._local = threading.local()

    # thread-safe property 접근
    @property
    def quality(self):
        with self._lock:
            return self._quality

    @quality.setter
    def quality(self, v):
        with self._lock:
            self._quality = v

    @property
    def scale(self):
        with self._lock:
            return self._scale

    @scale.setter
    def scale(self, v):
        with self._lock:
            self._scale = v

    def _get_sct(self):
        if not hasattr(self._local, 'sct'):
            self._local.sct = mss.mss()
        return self._local.sct

    def capture(self) -> bytes:
        sct = self._get_sct()
        with self._lock:
            quality = self._quality
            scale   = self._scale

        screenshot = sct.grab(sct.monitors[1])
        img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')

        if scale != 1.0:
            w, h = img.size
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        return buf.getvalue()

    def get_screen_size(self) -> tuple:
        sct = self._get_sct()
        monitor = sct.monitors[1]
        with self._lock:
            scale = self._scale
        return int(monitor['width'] * scale), int(monitor['height'] * scale)
