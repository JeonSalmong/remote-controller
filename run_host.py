"""집 PC(호스트)에서 실행"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    import argparse
    from host.host_main import RemoteHost

    parser = argparse.ArgumentParser(description='원격 데스크톱 호스트')
    parser.add_argument('--port',    type=int,   default=9999,  help='리스닝 포트 (기본: 9999)')
    parser.add_argument('--quality', type=int,   default=80,    help='JPEG 품질 1-100 (기본: 80)')
    parser.add_argument('--scale',   type=float, default=1.0,   help='화면 스케일 0.1-1.0 (기본: 1.0)')
    parser.add_argument('--fps',     type=int,   default=30,    help='목표 FPS (기본: 30)')
    parser.add_argument('--pin',     type=str,   default='',    help='고정 PIN (미지정 시 랜덤 생성)')
    args = parser.parse_args()

    host = RemoteHost(port=args.port, quality=args.quality,
                      scale=args.scale, fps=args.fps, pin=args.pin)
    host.start()
