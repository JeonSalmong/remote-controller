"""집 PC(호스트)에서 실행"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from host.host_main import RemoteHost

if __name__ == '__main__':
    host = RemoteHost()
    host.start()
