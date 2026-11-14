"""置信度：三个信号加权后过 sigmoid。权重写死在 constants 里，不让模型自评。

为什么不是直接的 `sigmoid(w·s)`：
规格书第 8 章给的权重 (0.30/0.50/0.20) 之和为 1，三个信号都在 [0,1]，
所以 `w·s ∈ [0,1]`，而 `sigmoid(1.0)=0.731`——**小于 0.75 的绿线门槛**。
照那个公式实现，任何一对都不可能被画成绿实线，产品最核心的那条视觉语义直接失效。

取舍：门槛（0.75 绿 / 0.45 黄）是用户看得见的产品行为，公式是实现细节。
保留门槛，把加权和居中到 0.5 再加增益：
    a = 0.30·s_retr + 0.50·s_judge + 0.20·s_struct
    c = sigmoid(4·(a - 0.5))
于是 a=1 → 0.88（绿），a=0.5 → 0.50（黄），a=0.2 → 0.23（不连线）。
"""

from __future__ import annotations

import math

from papertrace.constants import (
    SIGMOID_CENTER,
    SIGMOID_GAIN,
    W_JUDGE,
    W_RETR,
    W_STRUCT,
)


def weighted_signal(s_retr: float, s_judge: float, s_struct: float) -> float:
    """三个信号的加权和，落在 [0,1]。"""
    return W_RETR * s_retr + W_JUDGE * s_judge + W_STRUCT * s_struct


def confidence(s_retr: float, s_judge: float, s_struct: float) -> float:
    """三个信号都在 [0,1]，输出也在 (0,1)。"""
    for name, value in (
        ("s_retr", s_retr),
        ("s_judge", s_judge),
        ("s_struct", s_struct),
    ):
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} 必须在 [0,1]，收到 {value!r}")
    a = weighted_signal(s_retr, s_judge, s_struct)
    return 1.0 / (1.0 + math.exp(-SIGMOID_GAIN * (a - SIGMOID_CENTER)))
