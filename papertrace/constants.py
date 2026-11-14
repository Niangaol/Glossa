"""写死的常量。这些数字不是配置项——改它们就是改产品语义，必须走评审。"""

from __future__ import annotations

# 置信度权重（规格书 §8.3）。三者之和必须为 1。
W_RETR = 0.30
W_JUDGE = 0.50
W_STRUCT = 0.20

# 置信度分档：绿实线 / 黄虚线 + 备选 / 不连线进 unresolved。
CONF_GREEN = 0.75
CONF_YELLOW = 0.45

# U1 绿线门（年糕 m03751 拍板）：绿实线除了 confidence >= CONF_GREEN，
# 还要求结构信号 s_struct >= 0.5——词面/判断再像，结构对不上就不算对上账。
# 门只降不升：s_struct 不够只把 green 降成 yellow，绝不把 yellow 降成 none，
# 也不会把任何档往上升。门长在生成侧的 papertrace/align/tier.py：
# HTML 渲染时只有一个 confidence 数字，执行不了这条判据。
GREEN_STRUCT_MIN = 0.5

# 直接对加权和取 sigmoid 时，三个信号全满分也只有 sigmoid(1.0)=0.731 < 0.75，
# 即**永远连不出绿线**。规格书第 8 章同时给了这个公式和 0.75 的门槛，两者自相矛盾。
# 取舍：门槛是用户看得见的产品行为，公式是实现细节，所以保留门槛、给 sigmoid 加增益，
# 并把加权和居中到 0.5（"证据刚好一半"= 0.5 置信度）。
SIGMOID_GAIN = 4.0
SIGMOID_CENTER = 0.5

# 判断题依据的最大长度（schema 限制 80 字符含标点）。
EVIDENCE_MAX_CHARS = 40
EVIDENCE_SCHEMA_MAX = 80

# 单文件 HTML 体积上限（字节）。
HTML_MAX_BYTES = 8_000_000
