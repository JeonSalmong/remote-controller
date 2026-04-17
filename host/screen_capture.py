import threading
import io
from PIL import Image

try:
    import dxcam
    _USE_DXCAM = True
except ImportError:
    _USE_DXCAM = False
    import mss


class ScreenCapture:
    def __init__(self, quality: int = 80, scale: float = 1.0):
        self._quality = quality
        self._scale   = scale
        self._lock    = threading.Lock()
        self._cam     = None
        self._last_frame = None   # dxcam이 None 반환 시 이전 프레임 재사용
        self._mss_local  = threading.local()  # mss 폴백용

    # ── thread-safe 프로퍼티 ───────────────────────────────

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

    # ── 캡처 ──────────────────────────────────────────────

    def _init_dxcam(self):
        """dxcam 인스턴스 초기화 (호출 스레드에서 한 번만)"""
        if self._cam is None:
            self._cam = dxcam.create(output_color='RGB')

    def capture(self) -> bytes:
        with self._lock:
            quality = self._quality
            scale   = self._scale

        img = self._capture_dxcam() if _USE_DXCAM else self._capture_mss()

        if scale != 1.0:
            w, h = img.size
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        return buf.getvalue()

    def _capture_dxcam(self) -> Image.Image:
        self._init_dxcam()
        frame = self._cam.grab()   # 변화 없으면 None

        if frame is not None:
            self._last_frame = frame
        elif self._last_frame is None:
            # 첫 캡처 시 None이면 잠깐 대기 후 재시도
            import time; time.sleep(0.05)
            frame = self._cam.grab()
            if frame is None:
                raise RuntimeError("첫 화면 캡처 실패")
            self._last_frame = frame
        else:
            frame = self._last_frame   # 화면 변화 없음 → 이전 프레임 재사용

        return Image.fromarray(frame)

    def _capture_mss(self) -> Image.Image:
        """dxcam 미설치 시 폴백 (잠금화면 캡처 불가)"""
        if not hasattr(self._mss_local, 'sct'):
            self._mss_local.sct = mss.mss()
        sct = self._mss_local.sct
        shot = sct.grab(sct.monitors[1])
        return Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')

    def get_screen_size(self) -> tuple:
        from ctypes import windll
        with self._lock:
            scale = self._scale
        w = windll.user32.GetSystemMetrics(0)
        h = windll.user32.GetSystemMetrics(1)
        return int(w * scale), int(h * scale)
