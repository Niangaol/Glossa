"""测试公共常量：仓库根只在这里定义一次。

以前 39 处 `Path(__file__).resolve().parents[1]` 散在各个测试里，测试文件一挪目录就
静默指错地方。所有路径都从这里取。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
