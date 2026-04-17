import asyncio
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox, filedialog, ttk
import json
import sys
import os
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
import websockets.exceptions

from common.protocol import pack_message, unpack_message, MSG_MOUSE, MSG_KEYBOARD, MSG_AUTH, MSG_SCREEN, MSG_QUALITY, MSG_FILE
from client.screen_viewer import ScreenViewer
from client.file_transfer import FileClient


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'connection_history.json')
RECV_SAVE_DIR = os.path.expanduser('~/remote_desktop_received')


def _load_history() -> list:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 구버전 호환: 'ip' 필드 → 'address'
        for h in data:
            if 'ip' in h and 'address' not in h:
                h['address'] = h.pop('ip')
        return data
    except Exception:
        return []


def _save_history(address: str, port: int, pin: str):
    history = _load_history()
    history = [h for h in history if not (h['address'] == address and h['port'] == port)]
    history.insert(0, {
        'address': address,
        'port': port,
        'pin': base64.b64encode(pin.encode()).decode(),
    })
    history = history[:10]
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _decode_pin(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ''


def _build_uri(address: str, port: int) -> str:
    """IP:port 또는 wss:// URL → WebSocket URI"""
    if '://' in address:
        return address
    return f'ws://{address}:{port}'


class RemoteClient:
    def __init__(self):
        self._ws   = None   # websockets connection (asyncio 스레드 소유)
        self._loop = None   # asyncio 이벤트 루프
        self.running = False
        self.file_client = None
        self._connect_cancelled = False

        # 파일 수신 상태
        self._recv_file_f    = None
        self._recv_file_name = ''

        self.root = tk.Tk()
        self.root.title("원격 데스크톱 클라이언트")
        self.root.geometry("1280x720")
        self.root.configure(bg='black')

        self._build_ui()
        self._show_connect_dialog()

    QUALITY_PRESETS = [
        ('저화질',   50, 0.6),
        ('중화질',   75, 0.85),
        ('고화질',   85, 1.0),
        ('최고화질', 95, 1.0),
    ]

    # ── UI 구성 ────────────────────────────────────────────

    def _build_ui(self):
        toolbar = tk.Frame(self.root, bg='#2b2b2b', height=30)
        toolbar.pack(fill=tk.X, side=tk.TOP)
        toolbar.pack_propagate(False)

        tk.Button(toolbar, text='파일 보내기', command=self._send_file,
                  bg='#3c3f41', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(toolbar, text='파일 받기', command=self._request_file,
                  bg='#3c3f41', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2, pady=2)

        tk.Label(toolbar, text='│', bg='#2b2b2b', fg='#555555').pack(side=tk.LEFT, padx=4)
        tk.Label(toolbar, text='화질:', bg='#2b2b2b', fg='#aaaaaa').pack(side=tk.LEFT)

        self._quality_btns = []
        for label, q, s in self.QUALITY_PRESETS:
            btn = tk.Button(toolbar, text=label,
                            command=lambda q=q, s=s, lbl=label: self._set_quality(q, s, lbl),
                            bg='#3c3f41', fg='white', relief=tk.FLAT, padx=6)
            btn.pack(side=tk.LEFT, padx=1, pady=2)
            self._quality_btns.append((label, btn))

        self._highlight_quality_btn('고화질')

        tk.Label(toolbar, text='│', bg='#2b2b2b', fg='#555555').pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text='전체화면 (F11)', command=self._toggle_fullscreen,
                  bg='#3c3f41', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2, pady=2)

        tk.Button(toolbar, text='연결 끊기', command=self._disconnect,
                  bg='#8b0000', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.RIGHT, padx=4, pady=2)

        self.status_var = tk.StringVar(value='연결 안 됨')
        tk.Label(toolbar, textvariable=self.status_var,
                 bg='#2b2b2b', fg='#aaaaaa').pack(side=tk.RIGHT, padx=8)

        self._toolbar = toolbar

        self.viewer = ScreenViewer(self.root)
        self.viewer.pack(fill=tk.BOTH, expand=True)

        self._fs_hint = tk.Label(
            self.root, text='F11 또는 ESC: 전체화면 종료',
            bg='#000000', fg='#ffffff', font=('Arial', 11)
        )
        self._fs_active = False

        self._bind_events()

    # ── 연결 다이얼로그 ────────────────────────────────────

    def _show_connect_dialog(self):
        self._connect_cancelled = False
        history = _load_history()

        dialog = tk.Toplevel(self.root)
        dialog.title('호스트 연결')
        dialog.geometry('400x270')
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text='최근 접속:').grid(row=0, column=0, padx=12, pady=8, sticky='e')
        history_labels = [f"{h['address']}:{h['port']}" for h in history]
        history_var = tk.StringVar(value=history_labels[0] if history_labels else '')
        history_cb = ttk.Combobox(dialog, textvariable=history_var,
                                  values=history_labels, width=26, state='readonly')
        history_cb.grid(row=0, column=1, padx=8, sticky='w')

        tk.Label(dialog, text='주소:').grid(row=1, column=0, padx=12, pady=6, sticky='e')
        addr_var = tk.StringVar()
        tk.Entry(dialog, textvariable=addr_var, width=28).grid(row=1, column=1, padx=8)

        hint = tk.Label(dialog, text='예) 192.168.1.10  또는  wss://xxx.ngrok-free.app',
                        fg='gray', font=('Arial', 8))
        hint.grid(row=2, column=1, padx=8, sticky='w')

        tk.Label(dialog, text='포트:').grid(row=3, column=0, padx=12, pady=6, sticky='e')
        port_var = tk.StringVar(value='9999')
        tk.Entry(dialog, textvariable=port_var, width=28).grid(row=3, column=1, padx=8)

        tk.Label(dialog, text='PIN 번호:').grid(row=4, column=0, padx=12, pady=6, sticky='e')
        pin_var = tk.StringVar()
        tk.Entry(dialog, textvariable=pin_var, width=28, show='*').grid(row=4, column=1, padx=8)

        def on_history_select(e=None):
            sel = history_var.get()
            for h in history:
                if f"{h['address']}:{h['port']}" == sel:
                    addr_var.set(h['address'])
                    port_var.set(str(h['port']))
                    pin_var.set(_decode_pin(h['pin']))
                    break

        history_cb.bind('<<ComboboxSelected>>', on_history_select)
        if history:
            on_history_select()

        status_lbl = tk.Label(dialog, text='', fg='gray')
        status_lbl.grid(row=5, column=0, columnspan=2, pady=2)

        btn_frame = tk.Frame(dialog)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=8)

        connect_btn = tk.Button(btn_frame, text='연결', width=10)
        connect_btn.pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text='취소', width=10,
                  command=lambda: self.root.destroy()).pack(side=tk.LEFT, padx=6)

        def do_connect():
            address  = addr_var.get().strip()
            port_str = port_var.get().strip()
            pin      = pin_var.get().strip()
            if not address or not pin:
                messagebox.showerror('오류', '주소와 PIN을 입력해주세요', parent=dialog)
                return
            port = int(port_str or '9999')
            _save_history(address, port, pin)
            connect_btn.config(state=tk.DISABLED)
            status_lbl.config(text='연결 중...', fg='orange')
            dialog.update()

            uri = _build_uri(address, port)
            threading.Thread(
                target=self._connect,
                args=(uri, pin, dialog, status_lbl, connect_btn),
                daemon=True,
            ).start()

        connect_btn.config(command=do_connect)
        dialog.protocol('WM_DELETE_WINDOW', lambda: self.root.destroy())
        dialog.bind('<Return>', lambda e: do_connect())

    # ── WebSocket 연결 (백그라운드 스레드) ─────────────────

    def _connect(self, uri: str, pin: str, dialog=None, status_lbl=None, connect_btn=None):
        def set_status(msg, color='gray'):
            if dialog and dialog.winfo_exists():
                self.root.after(0, lambda: status_lbl.config(text=msg, fg=color))

        def re_enable():
            if dialog and dialog.winfo_exists():
                connect_btn.config(state=tk.NORMAL)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(
                self._ws_session(uri, pin, dialog, set_status, re_enable)
            )
        finally:
            self._loop.close()
            self._loop = None

    async def _ws_session(self, uri: str, pin: str, dialog, set_status, re_enable):
        import traceback
        print(f"[연결시도] {uri} 에 WebSocket 연결 중...")
        set_status(f'연결 중... ({uri})', 'orange')
        try:
            async with websockets.connect(
                uri,
                open_timeout=10,
                max_size=10 * 1024 * 1024,
                compression=None,
            ) as ws:
                self._ws = ws
                print("[연결시도] WebSocket 연결 성공")

                if self._connect_cancelled:
                    return

                # PIN 인증
                set_status('PIN 인증 중...', 'orange')
                print("[연결시도] PIN 인증 전송 중...")
                auth_data = json.dumps({'pin': pin}).encode()
                await ws.send(pack_message(MSG_AUTH, auth_data))

                data = await asyncio.wait_for(ws.recv(), timeout=10)
                msg_type, payload = unpack_message(data)
                resp = json.loads(payload.decode())
                print(f"[연결시도] 인증 응답: {resp}")

                if resp.get('status') != 'ok':
                    self.root.after(0, lambda: messagebox.showerror('인증 실패', 'PIN이 틀렸습니다!'))
                    self.root.after(0, re_enable)
                    set_status('PIN 오류', 'red')
                    return

                print("[연결시도] 인증 성공! 화면 수신 시작")
                self.file_client = FileClient(ws, self._loop)
                self.running = True
                self.root.after(0, lambda: self.status_var.set(f'연결됨: {uri}'))
                self.root.after(0, lambda: self.root.title(f'원격 데스크톱 - {uri}'))
                if dialog:
                    self.root.after(0, dialog.destroy)

                await self._recv_loop(ws)

        except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as e:
            msg = f'{type(e).__name__}: {e}'
            print(f"[연결시도] 오류: {msg}\n{traceback.format_exc()}")
            if not self._connect_cancelled:
                set_status(f'오류: {e}', 'red')
                self.root.after(0, lambda: messagebox.showerror('연결 오류', msg))
                self.root.after(0, re_enable)
        finally:
            self.running = False
            self._ws = None

    async def _recv_loop(self, ws):
        os.makedirs(RECV_SAVE_DIR, exist_ok=True)
        recv_file_f    = None
        recv_file_name = ''

        async for raw in ws:
            if not self.running:
                break
            try:
                msg_type, payload = unpack_message(raw)
            except Exception:
                continue

            if msg_type == MSG_SCREEN:
                self.root.after(0, self.viewer.update_frame, payload)

            elif msg_type == MSG_FILE:
                if recv_file_f is None:
                    meta = json.loads(payload.decode())
                    if 'error' in meta:
                        print(f"파일 오류: {meta['error']}")
                    else:
                        recv_file_name = meta['filename']
                        save_path = os.path.join(RECV_SAVE_DIR, recv_file_name)
                        recv_file_f = open(save_path, 'wb')
                else:
                    if payload == b'<<EOF>>':
                        recv_file_f.close()
                        recv_file_f = None
                        print(f"파일 수신 완료: {recv_file_name}")
                    else:
                        recv_file_f.write(payload)

        if recv_file_f:
            recv_file_f.close()

        if self.running:
            self.root.after(0, self._on_disconnected)

    # ── 내부 유틸 ──────────────────────────────────────────

    def _send_raw(self, data: bytes):
        """tkinter 스레드 → asyncio 루프로 WebSocket 전송."""
        if self._ws and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._ws.send(data), self._loop)

    def _on_disconnected(self):
        self.running = False
        self.status_var.set('연결 끊김')
        messagebox.showwarning('연결 끊김', '호스트와의 연결이 끊겼습니다.')

    def _highlight_quality_btn(self, active_label: str):
        for label, btn in self._quality_btns:
            if label == active_label:
                btn.config(bg='#2d6a9f', relief=tk.SUNKEN)
            else:
                btn.config(bg='#3c3f41', relief=tk.FLAT)

    def _set_quality(self, quality: int, scale: float, label: str):
        if not self.running:
            return
        payload = json.dumps({'quality': quality, 'scale': scale}).encode()
        self._send_raw(pack_message(MSG_QUALITY, payload))
        self._highlight_quality_btn(label)
        base = self.status_var.get().split('|')[0].strip()
        self.status_var.set(f'{base} | {label}')

    def _toggle_fullscreen(self):
        self._fs_active = not self._fs_active
        self.root.attributes('-fullscreen', self._fs_active)
        if self._fs_active:
            self._toolbar.pack_forget()
            self._fs_hint.place(relx=1.0, rely=0.0, anchor='ne', x=-8, y=8)
        else:
            self._fs_hint.place_forget()
            self._toolbar.pack(fill=tk.X, side=tk.TOP, before=self.viewer)

    def _disconnect(self):
        self.running = False
        if self._ws and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        self.status_var.set('연결 안 됨')
        self.root.title('원격 데스크톱 클라이언트')

    # ── 이벤트 바인딩 ──────────────────────────────────────

    _LOCAL_KEYS = {'F11', 'Escape'}

    def _bind_events(self):
        v = self.viewer
        v.bind('<Motion>',          self._on_move)
        v.bind('<Button-1>',        lambda e: self._on_mouse(e, 'click',    'left'))
        v.bind('<Button-3>',        lambda e: self._on_mouse(e, 'click',    'right'))
        v.bind('<Double-Button-1>', lambda e: self._on_mouse(e, 'dblclick', 'left'))
        v.bind('<ButtonPress-1>',   lambda e: self._on_mouse(e, 'mousedown','left'))
        v.bind('<ButtonRelease-1>', lambda e: self._on_mouse(e, 'mouseup',  'left'))
        v.bind('<MouseWheel>',      self._on_scroll)
        v.bind('<B1-Motion>',       self._on_drag)
        self.root.bind('<KeyPress>',   self._on_key_press)
        self.root.bind('<KeyRelease>', self._on_key_release)
        self.root.bind('<F11>',    lambda e: self._toggle_fullscreen())
        self.root.bind('<Escape>', lambda e: self._exit_fullscreen())
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _exit_fullscreen(self):
        if self._fs_active:
            self._toggle_fullscreen()

    def _send_mouse(self, action, x, y, **kwargs):
        if not self.running:
            return
        payload = json.dumps({'action': action, 'x': x, 'y': y, **kwargs}).encode()
        self._send_raw(pack_message(MSG_MOUSE, payload))

    def _on_move(self, e):
        x, y = self.viewer.scale_coords(e.x, e.y)
        self._send_mouse('move', x, y)

    def _on_mouse(self, e, action, button):
        x, y = self.viewer.scale_coords(e.x, e.y)
        self._send_mouse(action, x, y, button=button)

    def _on_scroll(self, e):
        x, y = self.viewer.scale_coords(e.x, e.y)
        self._send_mouse('scroll', x, y, delta=e.delta)

    def _on_drag(self, e):
        x, y = self.viewer.scale_coords(e.x, e.y)
        self._send_mouse('drag', x, y)

    def _on_key_press(self, e):
        if not self.running or e.keysym in self._LOCAL_KEYS:
            return
        payload = json.dumps({'action': 'press', 'key': e.keysym}).encode()
        self._send_raw(pack_message(MSG_KEYBOARD, payload))

    def _on_key_release(self, e):
        if not self.running or e.keysym in self._LOCAL_KEYS:
            return
        payload = json.dumps({'action': 'release', 'key': e.keysym}).encode()
        self._send_raw(pack_message(MSG_KEYBOARD, payload))

    # ── 파일 전송 ──────────────────────────────────────────

    def _send_file(self):
        if not self.running:
            messagebox.showwarning('경고', '연결되어 있지 않습니다.')
            return
        path = filedialog.askopenfilename(title='전송할 파일 선택')
        if path:
            self.file_client.send_file(path)

    def _request_file(self):
        if not self.running:
            messagebox.showwarning('경고', '연결되어 있지 않습니다.')
            return
        remote_path = simpledialog.askstring('파일 받기', '호스트의 파일 경로를 입력하세요:')
        if remote_path:
            self.file_client.request_file(remote_path)

    def _on_close(self):
        self._disconnect()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = RemoteClient()
    app.run()
