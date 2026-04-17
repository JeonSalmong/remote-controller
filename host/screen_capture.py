import threading
import io
from PIL import Image

try:
    import dxcam
    _DXCAM_INSTALLED = True
except ImportError:
    _DXCAM_INSTALLED = False

try:
    import mss as _mss_mod
    _MSS_INSTALLED = True
except ImportError:
    _MSS_INSTALLED = False


class ScreenCapture:
    def __init__(self, quality: int = 80, scale: float = 1.0):
        self._quality = quality
        self._scale   = scale
        self._lock    = threading.Lock()

        self._cam        = None   # dxcam 인스턴스
        self._use_dxcam  = _DXCAM_INSTALLED  # 런타임 폴백 시 False로 전환
        self._mss_local  = threading.local()  # mss 폴백용 스레드-로컬

    # ── thread-safe 프로퍼티 ──────────────────────────────

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

    # ── dxcam 초기화 ─────────────────────────────────────

    def _init_dxcam(self):
        """처음 호출 시 dxcam 시작. 실패하면 mss로 자동 폴백."""
        if self._cam is not None:
            return
        try:
            cam = dxcam.create(output_color='RGB')
            # video_mode=True: get_latest_frame()이 항상 프레임 반환 (None 없음)
            cam.start(target_fps=60, video_mode=True)
            self._cam = cam
            print("[화면캡처] dxcam 시작 완료 (잠금화면 캡처 지원)")
        except Exception as e:
            print(f"[화면캡처] dxcam 초기화 실패: {e}")
            print("[화면캡처] mss 폴백 모드로 전환 (잠금화면 캡처 불가)")
            self._use_dxcam = False

    def cleanup(self):
        if self._cam:
            try:
                self._cam.stop()
            except Exception:
                pass

    # ── 캡처 구현 ─────────────────────────────────────────

    def _capture_dxcam(self) -> Image.Image:
        self._init_dxcam()
        if not self._use_dxcam:           # 초기화 실패 → mss 폴백
            return self._capture_mss()
        frame = self._cam.get_latest_frame()  # video_mode=True이므로 항상 반환
        return Image.fromarray(frame)

    def _capture_mss(self) -> Image.Image:
        if not hasattr(self._mss_local, 'sct'):
            self._mss_local.sct = _mss_mod.mss()
        sct = self._mss_local.sct
        shot = sct.grab(sct.monitors[1])
        return Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')

    # ── 공개 API ──────────────────────────────────────────

    def capture(self) -> bytes:
        with self._lock:
            quality = self._quality
            scale   = self._scale

        img = self._capture_dxcam() if self._use_dxcam else self._capture_mss()

        if scale != 1.0:
            w, h = img.size
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        return buf.getvalue()

    def get_screen_size(self) -> tuple:
        from ctypes import windll
        with self._lock:
            scale = self._scale
        w = windll.user32.GetSystemMetrics(0)
        h = windll.user32.GetSystemMetrics(1)
        return int(w * scale), int(h * scale)
