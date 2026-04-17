import socket
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox, filedialog, ttk
import json
import sys
import os
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.protocol import pack_message, recv_message, MSG_MOUSE, MSG_KEYBOARD, MSG_AUTH, MSG_SCREEN
from client.screen_viewer import ScreenViewer
from client.file_transfer import FileClient


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'connection_history.json')


def _load_history() -> list:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(ip: str, port: int, pin: str):
    history = _load_history()
    # 동일 IP+포트 항목이 있으면 제거 후 최신으로 앞에 추가
    history = [h for h in history if not (h['ip'] == ip and h['port'] == port)]
    history.insert(0, {
        'ip': ip,
        'port': port,
        'pin': base64.b64encode(pin.encode()).decode(),
    })
    history = history[:10]  # 최대 10개 보관
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _decode_pin(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ''


class RemoteClient:
    def __init__(self):
        self.sock = None
        self.running = False
        self.file_client = None
        self._connect_cancelled = False

        self.root = tk.Tk()
        self.root.title("원격 데스크톱 클라이언트")
        self.root.geometry("1280x720")
        self.root.configure(bg='black')

        self._build_ui()
        self._show_connect_dialog()

    def _build_ui(self):
        # 툴바
        toolbar = tk.Frame(self.root, bg='#2b2b2b', height=30)
        toolbar.pack(fill=tk.X, side=tk.TOP)
        toolbar.pack_propagate(False)

        tk.Button(toolbar, text='파일 보내기', command=self._send_file,
                  bg='#3c3f41', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(toolbar, text='파일 받기', command=self._request_file,
                  bg='#3c3f41', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(toolbar, text='연결 끊기', command=self._disconnect,
                  bg='#8b0000', fg='white', relief=tk.FLAT, padx=8).pack(side=tk.RIGHT, padx=4, pady=2)

        self.status_var = tk.StringVar(value='연결 안 됨')
        tk.Label(toolbar, textvariable=self.status_var, bg='#2b2b2b', fg='#aaaaaa').pack(side=tk.RIGHT, padx=8)

        # 화면 뷰어
        self.viewer = ScreenViewer(self.root)
        self.viewer.pack(fill=tk.BOTH, expand=True)

        self._bind_events()

    def _show_connect_dialog(self):
        self._connect_cancelled = False
        history = _load_history()

        dialog = tk.Toplevel(self.root)
        dialog.title('호스트 연결')
        dialog.geometry('360x250')
        dialog.resizable(False, False)
        dialog.grab_set()

        # 최근 접속 드롭다운
        tk.Label(dialog, text='최근 접속:').grid(row=0, column=0, padx=12, pady=8, sticky='e')
        history_labels = [f"{h['ip']}:{h['port']}" for h in history]
        history_var = tk.StringVar(value=history_labels[0] if history_labels else '')
        history_cb = ttk.Combobox(dialog, textvariable=history_var,
                                     values=history_labels, width=20, state='readonly')
        history_cb.grid(row=0, column=1, padx=8, sticky='w')

        tk.Label(dialog, text='호스트 IP:').grid(row=1, column=0, padx=12, pady=6, sticky='e')
        ip_var = tk.StringVar()
        tk.Entry(dialog, textvariable=ip_var, width=22).grid(row=1, column=1, padx=8)

        tk.Label(dialog, text='포트:').grid(row=2, column=0, padx=12, pady=6, sticky='e')
        port_var = tk.StringVar(value='9999')
        tk.Entry(dialog, textvariable=port_var, width=22).grid(row=2, column=1, padx=8)

        tk.Label(dialog, text='PIN 번호:').grid(row=3, column=0, padx=12, pady=6, sticky='e')
        pin_var = tk.StringVar()
        tk.Entry(dialog, textvariable=pin_var, width=22, show='*').grid(row=3, column=1, padx=8)

        # 최근 접속 선택 시 자동 입력
        def on_history_select(e=None):
            sel = history_var.get()
            for h in history:
                if f"{h['ip']}:{h['port']}" == sel:
                    ip_var.set(h['ip'])
                    port_var.set(str(h['port']))
                    pin_var.set(_decode_pin(h['pin']))
                    break

        history_cb.bind('<<ComboboxSelected>>', on_history_select)

        # 저장된 항목이 있으면 첫 번째 항목 자동 입력
        if history:
            on_history_select()

        status_lbl = tk.Label(dialog, text='', fg='gray')
        status_lbl.grid(row=4, column=0, columnspan=2, pady=2)

        btn_frame = tk.Frame(dialog)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=8)

        connect_btn = tk.Button(btn_frame, text='연결', width=10)
        connect_btn.pack(side=tk.LEFT, padx=6)
        cancel_btn = tk.Button(btn_frame, text='취소', width=10,
                               command=lambda: self.root.destroy())
        cancel_btn.pack(side=tk.LEFT, padx=6)

        def do_connect():
            host_ip = ip_var.get().strip()
            port_str = port_var.get().strip()
            pin = pin_var.get().strip()
            if not host_ip or not pin:
                messagebox.showerror('오류', 'IP와 PIN을 입력해주세요', parent=dialog)
                return
            port = int(port_str or '9999')
            _save_history(host_ip, port, pin)  # 성공 여부와 관계없이 입력값 저장
            connect_btn.config(state=tk.DISABLED)
            cancel_btn.config(command=self._cancel_connect)
            status_lbl.config(text='연결 중...', fg='orange')
            dialog.update()
            threading.Thread(
                target=self._connect,
                args=(host_ip, port, pin, dialog, status_lbl, connect_btn),
                daemon=True
            ).start()

        connect_btn.config(command=do_connect)
        dialog.protocol('WM_DELETE_WINDOW', lambda: self.root.destroy())
        dialog.bind('<Return>', lambda e: do_connect())

    def _cancel_connect(self):
        """연결 시도 중 취소"""
        self._connect_cancelled = True
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.root.destroy()

    def _connect(self, host_ip: str, port: int, pin: str, dialog=None, status_lbl=None, connect_btn=None):
        def set_status(msg, color='gray'):
            if dialog and dialog.winfo_exists():
                self.root.after(0, lambda: status_lbl.config(text=msg, fg=color))

        def re_enable():
            if dialog and dialog.winfo_exists():
                connect_btn.config(state=tk.NORMAL)

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((host_ip, port))
            self.sock.settimeout(None)

            if self._connect_cancelled:
                return

            # PIN 인증
            auth_data = json.dumps({'pin': pin}).encode()
            self.sock.sendall(pack_message(MSG_AUTH, auth_data))
            msg_type, data = recv_message(self.sock)
            resp = json.loads(data.decode())

            if resp.get('status') != 'ok':
                self.root.after(0, lambda: messagebox.showerror('인증 실패', 'PIN이 틀렸습니다!'))
                self.sock.close()
                self.root.after(0, re_enable)
                set_status('PIN 오류', 'red')
                return

            self.file_client = FileClient(self.sock)
            self.running = True
            self.root.after(0, lambda: self.status_var.set(f'연결됨: {host_ip}:{port}'))
            self.root.after(0, lambda: self.root.title(f'원격 데스크톱 - {host_ip}'))
            if dialog:
                self.root.after(0, dialog.destroy)

            threading.Thread(target=self._recv_screen, daemon=True).start()

        except socket.timeout:
            set_status('연결 시간 초과', 'red')
            self.root.after(0, lambda: messagebox.showerror(
                '연결 실패', f'연결 시간이 초과됐습니다.\nIP/포트를 확인하세요.'))
            self.root.after(0, re_enable)
        except ConnectionRefusedError:
            set_status('연결 거부됨', 'red')
            self.root.after(0, lambda: messagebox.showerror(
                '연결 실패', f'{host_ip}:{port} 에 연결할 수 없습니다.\n호스트가 실행 중인지 확인하세요.'))
            self.root.after(0, re_enable)
        except OSError as e:
            if not self._connect_cancelled:
                set_status(f'오류: {e}', 'red')
                self.root.after(0, lambda: messagebox.showerror('연결 오류', str(e)))
                self.root.after(0, re_enable)

    def _recv_screen(self):
        while self.running:
            try:
                msg_type, data = recv_message(self.sock)
                if msg_type == MSG_SCREEN:
                    self.root.after(0, self.viewer.update_frame, data)
            except Exception as e:
                if self.running:
                    print(f"화면 수신 오류: {e}")
                    self.root.after(0, self._on_disconnected)
                break

    def _on_disconnected(self):
        self.running = False
        self.status_var.set('연결 끊김')
        messagebox.showwarning('연결 끊김', '호스트와의 연결이 끊겼습니다.')

    def _disconnect(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.status_var.set('연결 안 됨')
        self.root.title('원격 데스크톱 클라이언트')

    # ── 이벤트 바인딩 ──────────────────────────────────────

    def _bind_events(self):
        v = self.viewer
        v.bind('<Motion>',      self._on_move)
        v.bind('<Button-1>',    lambda e: self._on_mouse(e, 'click', 'left'))
        v.bind('<Button-3>',    lambda e: self._on_mouse(e, 'click', 'right'))
        v.bind('<Double-Button-1>', lambda e: self._on_mouse(e, 'dblclick', 'left'))
        v.bind('<ButtonPress-1>',   lambda e: self._on_mouse(e, 'mousedown', 'left'))
        v.bind('<ButtonRelease-1>', lambda e: self._on_mouse(e, 'mouseup', 'left'))
        v.bind('<MouseWheel>',  self._on_scroll)
        v.bind('<B1-Motion>',   self._on_drag)
        self.root.bind('<KeyPress>',   self._on_key_press)
        self.root.bind('<KeyRelease>', self._on_key_release)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _send_mouse(self, action, x, y, **kwargs):
        if not self.running:
            return
        payload = json.dumps({'action': action, 'x': x, 'y': y, **kwargs}).encode()
        try:
            self.sock.sendall(pack_message(MSG_MOUSE, payload))
        except Exception:
            pass

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
        if not self.running:
            return
        payload = json.dumps({'action': 'press', 'key': e.keysym}).encode()
        try:
            self.sock.sendall(pack_message(MSG_KEYBOARD, payload))
        except Exception:
            pass

    def _on_key_release(self, e):
        if not self.running:
            return
        payload = json.dumps({'action': 'release', 'key': e.keysym}).encode()
        try:
            self.sock.sendall(pack_message(MSG_KEYBOARD, payload))
        except Exception:
            pass

    # ── 파일 전송 ──────────────────────────────────────────

    def _send_file(self):
        if not self.running:
            messagebox.showwarning('경고', '연결되어 있지 않습니다.')
            return
        path = filedialog.askopenfilename(title='전송할 파일 선택')
        if path:
            threading.Thread(target=self.file_client.send_file, args=(path,), daemon=True).start()

    def _request_file(self):
        if not self.running:
            messagebox.showwarning('경고', '연결되어 있지 않습니다.')
            return
        remote_path = simpledialog.askstring('파일 받기', '호스트의 파일 경로를 입력하세요:')
        if remote_path:
            threading.Thread(target=self.file_client.request_file, args=(remote_path,), daemon=True).start()

    def _on_close(self):
        self._disconnect()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = RemoteClient()
    app.run()
