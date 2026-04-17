import threading
import time
import io
from PIL import Image

try:
    import dxcam
    _DXCAM_INSTALLED = True
except ImportError:
    _DXCAM_INSTALLED = False
    print("[화면캡처] dxcam 미설치 → mss 사용 (잠금화면 캡처 불가)")

try:
    import mss as _mss_mod
    _MSS_INSTALLED = True
except ImportError:
    _MSS_INSTALLED = False


class ScreenCapture:
    def __init__(self, quality: int = 80, scale: float = 1.0):
        self._quality    = quality
        self._scale      = scale
        self._lock       = threading.Lock()
        self._cam        = None
        self._use_dxcam  = _DXCAM_INSTALLED
        self._mss_local  = threading.local()

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
        if self._cam is not None:
            return
        try:
            print("[화면캡처] dxcam 초기화 중...")
            self._cam = dxcam.create(output_color='RGB')
            # 첫 프레임 warm-up (grab()이 처음엔 None 반환할 수 있음)
            for i in range(20):
                f = self._cam.grab()
                if f is not None:
                    print(f"[화면캡처] dxcam 준비 완료 (warm-up {i+1}회)")
                    return
                time.sleep(0.05)
            # warm-up 후에도 None → mss 폴백
            raise RuntimeError("warm-up 후에도 프레임 없음")
        except Exception as e:
            print(f"[화면캡처] dxcam 초기화 실패: {e}")
            print("[화면캡처] mss 폴백 모드 전환 (잠금화면 캡처 불가)")
            self._cam = None
            self._use_dxcam = False

    # ── 캡처 구현 ─────────────────────────────────────────

    def _capture_dxcam(self) -> Image.Image:
        self._init_dxcam()
        if not self._use_dxcam:
            return self._capture_mss()

        # grab() 재시도 (화면 변화 없으면 None 반환)
        for _ in range(10):
            frame = self._cam.grab()
            if frame is not None:
                return Image.fromarray(frame)
            time.sleep(0.033)

        # 지속 실패 → mss 폴백
        print("[화면캡처] dxcam grab 반복 실패 → mss 폴백")
        self._use_dxcam = False
        return self._capture_mss()

    def _capture_mss(self) -> Image.Image:
        if not _MSS_INSTALLED:
            raise RuntimeError("mss 미설치. pip install mss 실행 필요")
        if not hasattr(self._mss_local, 'sct'):
            self._mss_local.sct = _mss_mod.mss()
        sct  = self._mss_local.sct
        shot = sct.grab(sct.monitors[1])
        return Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')

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

    def cleanup(self):
        if self._cam:
            try:
                del self._cam
            except Exception:
                pass
            self._cam = None

    def get_screen_size(self) -> tuple:
        from ctypes import windll
        with self._lock:
            scale = self._scale
        w = windll.user32.GetSystemMetrics(0)
        h = windll.user32.GetSystemMetrics(1)
        return int(w * scale), int(h * scale)
