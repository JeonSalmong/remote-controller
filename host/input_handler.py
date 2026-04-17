import json
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# tkinter keysym → pyautogui 키 이름 매핑
KEYSYM_MAP = {
    'Return': 'enter', 'BackSpace': 'backspace', 'Tab': 'tab',
    'Escape': 'esc', 'Delete': 'delete', 'Insert': 'insert',
    'Home': 'home', 'End': 'end', 'Prior': 'pageup', 'Next': 'pagedown',
    'Up': 'up', 'Down': 'down', 'Left': 'left', 'Right': 'right',
    'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4',
    'F5': 'f5', 'F6': 'f6', 'F7': 'f7', 'F8': 'f8',
    'F9': 'f9', 'F10': 'f10', 'F11': 'f11', 'F12': 'f12',
    'Control_L': 'ctrl', 'Control_R': 'ctrl',
    'Alt_L': 'alt', 'Alt_R': 'alt',
    'Shift_L': 'shift', 'Shift_R': 'shift',
    'Super_L': 'win', 'Super_R': 'win',
    'space': 'space', 'minus': '-', 'equal': '=',
    'bracketleft': '[', 'bracketright': ']', 'backslash': '\\',
    'semicolon': ';', 'apostrophe': "'", 'grave': '`',
    'comma': ',', 'period': '.', 'slash': '/',
    'KP_Enter': 'enter', 'KP_Delete': 'delete',
    'KP_0': '0', 'KP_1': '1', 'KP_2': '2', 'KP_3': '3', 'KP_4': '4',
    'KP_5': '5', 'KP_6': '6', 'KP_7': '7', 'KP_8': '8', 'KP_9': '9',
    'Print': 'printscreen', 'Scroll_Lock': 'scrolllock', 'Pause': 'pause',
    'Caps_Lock': 'capslock', 'Num_Lock': 'numlock',
}


def _map_key(keysym: str) -> str:
    if keysym in KEYSYM_MAP:
        return KEYSYM_MAP[keysym]
    if len(keysym) == 1:
        return keysym.lower()
    return keysym.lower()


class InputHandler:
    def __init__(self, scale: float = 0.75):
        # 클라이언트 좌표는 캡처된 축소 이미지 기준이므로 역스케일로 원본 해상도 복원
        self.inv_scale = 1.0 / scale

    def handle(self, msg_type: int, data: bytes):
        try:
            payload = json.loads(data.decode())
            if msg_type == 0x02:
                self._handle_mouse(payload)
            elif msg_type == 0x03:
                self._handle_keyboard(payload)
        except Exception as e:
            print(f"입력 처리 오류: {e}")

    def _handle_mouse(self, p):
        action = p.get('action')
        x = int(p.get('x', 0) * self.inv_scale)
        y = int(p.get('y', 0) * self.inv_scale)

        if action == 'move':
            pyautogui.moveTo(x, y)
        elif action == 'click':
            pyautogui.click(x, y, button=p.get('button', 'left'))
        elif action == 'dblclick':
            pyautogui.doubleClick(x, y, button=p.get('button', 'left'))
        elif action == 'mousedown':
            pyautogui.mouseDown(x, y, button=p.get('button', 'left'))
        elif action == 'mouseup':
            pyautogui.mouseUp(x, y, button=p.get('button', 'left'))
        elif action == 'scroll':
            delta = p.get('delta', 0)
            clicks = 3 if delta > 0 else -3
            pyautogui.scroll(clicks, x=x, y=y)
        elif action == 'drag':
            pyautogui.dragTo(x, y, duration=0.05)

    def _handle_keyboard(self, p):
        action = p.get('action')
        key = _map_key(p.get('key', ''))

        if not key:
            return
        if action == 'press':
            pyautogui.keyDown(key)
        elif action == 'release':
            pyautogui.keyUp(key)
        elif action == 'hotkey':
            keys = [_map_key(k) for k in p.get('keys', [])]
            pyautogui.hotkey(*keys)
