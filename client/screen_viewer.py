import tkinter as tk
from PIL import Image, ImageTk
import io
import threading


class ScreenViewer(tk.Canvas):
    """수신된 JPEG 프레임을 표시하는 캔버스 위젯"""

    def __init__(self, master, **kwargs):
        super().__init__(master, cursor='crosshair', bg='black', **kwargs)
        self._photo = None
        self.host_w = 1920
        self.host_h = 1080
        self._lock = threading.Lock()

    def update_frame(self, jpeg_bytes: bytes):
        try:
            img = Image.open(io.BytesIO(jpeg_bytes))
            self.host_w, self.host_h = img.size

            cw = self.winfo_width() or self.host_w
            ch = self.winfo_height() or self.host_h
            img = img.resize((cw, ch), Image.LANCZOS)

            with self._lock:
                self._photo = ImageTk.PhotoImage(img)
                self.create_image(0, 0, anchor=tk.NW, image=self._photo)
        except Exception:
            pass

    def scale_coords(self, x: int, y: int) -> tuple:
        cw = self.winfo_width() or 1
        ch = self.winfo_height() or 1
        return int(x / cw * self.host_w), int(y / ch * self.host_h)
