import mss
from PIL import Image
import io


class ScreenCapture:
    def __init__(self, quality: int = 50, scale: float = 0.75):
        self.quality = quality
        self.scale = scale
        self.sct = mss.mss()

    def capture(self) -> bytes:
        screenshot = self.sct.grab(self.sct.monitors[1])
        img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')

        w, h = img.size
        img = img.resize((int(w * self.scale), int(h * self.scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=self.quality, optimize=True)
        return buf.getvalue()

    def get_screen_size(self) -> tuple:
        monitor = self.sct.monitors[1]
        w = int(monitor['width'] * self.scale)
        h = int(monitor['height'] * self.scale)
        return w, h
