"""회사 PC(클라이언트)에서 실행"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client.client_main import RemoteClient

if __name__ == '__main__':
    app = RemoteClient()
    app.run()
