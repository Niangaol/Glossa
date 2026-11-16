"""python -m glossa.mcp：在 stdio 上起 server（R327：stdout 只写 JSON-RPC，日志走 stderr）。"""

from __future__ import annotations

import sys

from glossa.mcp.server import serve


def main():
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
