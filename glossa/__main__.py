"""python -m glossa 的入口：把退出码原样交给 shell。"""
import sys

from glossa.cli import main

if __name__ == "__main__":
    sys.exit(main())
