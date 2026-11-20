"""退出码常量。

退出码常量集中在这里，cli 与 render/dump 共用：cli 负责把参数变成调用、把结果
变成退出码，而「2 / 4 / 5 分别是什么」只在这一处定义，避免两边各写一份而漂移。
"""

from __future__ import annotations

UNIMPLEMENTED = 2
#: 缺运行时要件（典型：没装 torch）。不许降级成空 trace。
MISSING_RUNTIME = 4
#: 模型能加载但追不动（export 失败，或导出图无法真实再执行）。
UNTRACEABLE = 5
