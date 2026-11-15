"""程序入口。不带参数 = 启动器；带 --overlay = 翻译进程（启动器点「启动」时起的就是它）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run():
    if "--overlay" in sys.argv:
        import app
        app.main()
    else:
        import launcher
        launcher.main()


if __name__ == "__main__":
    run()
