import struct

MSG_SCREEN   = 0x01
MSG_MOUSE    = 0x02
MSG_KEYBOARD = 0x03
MSG_FILE     = 0x04
MSG_AUTH     = 0x05
MSG_FILE_REQ = 0x06
MSG_QUALITY  = 0x07  # 클라이언트 → 호스트: 화질 변경 요청

HEADER_SIZE = 5  # 1(type) + 4(length)


def pack_message(msg_type: int, data: bytes) -> bytes:
    """[type:1B][size:4B][data]"""
    return struct.pack('>BL', msg_type, len(data)) + data


def unpack_header(header: bytes) -> tuple:
    return struct.unpack('>BL', header)


def recv_exact(sock, n: int) -> bytes:
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("연결이 끊겼습니다")
        buf += chunk
    return buf


def recv_message(sock) -> tuple:
    """헤더 수신 후 데이터 완전 수신. (msg_type, data) 반환"""
    header = recv_exact(sock, HEADER_SIZE)
    msg_type, size = unpack_header(header)
    data = recv_exact(sock, size) if size > 0 else b''
    return msg_type, data
