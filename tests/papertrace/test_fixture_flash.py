"""夹具守卫：黄金主路径必须能看见未融合的 Attention 算子。

nanoGPT 在 PyTorch 2+ 上默认 `self.flash = hasattr(F, "scaled_dot_product_attention")`，
也就是 True；一旦走 SDPA，QKᵀ / scale / mask / softmax 会被融成一个算子，
算子级对账就无从谈起。所以夹具必须离线可验证地把它关掉。
"""
from tests.common import FIXTURES

from pathlib import Path

import pytest

NANOGPT_MODEL = FIXTURES / "nanogpt" / "model.py"
ATTENTION_TEX = FIXTURES / "papers" / "vaswani2017" / "attention.tex"


def test_nanogpt_fixture_exists():
    assert NANOGPT_MODEL.is_file(), "缺少 nanoGPT 夹具"
    assert ATTENTION_TEX.is_file(), "缺少 Vaswani Attention 夹具"


def _init_body() -> str:
    """只取 CausalSelfAttention.__init__ 的方法体。

    早期版本在整份源码里找 "self.flash = False"，结果 docstring 里那句说明
    就能让断言通过——守卫被打穿。这里限定到 __init__ 之后、def forward 之前。
    """
    text = NANOGPT_MODEL.read_text(encoding="utf-8")
    start = text.index("class CausalSelfAttention")
    init = text.index("def __init__", start)
    end = text.index("def forward", init)
    return text[init:end]


def test_fixture_disables_flash_at_source_level():
    """不装 torch 也要能守住这条——所以查源码字面量。"""
    body = _init_body()
    # 只看赋值本身：上游的自动探测写法 by_name 各种引号都要挡住。
    assert "self.flash = False" in body
    assert "self.flash = hasattr" not in body
    assert "self.flash = True" not in body
    assert "getattr(F," not in body


def test_attention_tex_has_four_splittable_terms():
    text = ATTENTION_TEX.read_text(encoding="utf-8")
    assert "papertrace-id" in text
    assert "\\mathrm{softmax}" in text
    assert "QK" in text
    assert "sqrt{d_k}" in text or "sqrt{d_{k}}" in text


def test_flash_flag_is_false_on_real_module():
    torch = pytest.importorskip("torch")
    from tests.fixtures.nanogpt.model import CausalSelfAttention, GPTConfig

    cfg = GPTConfig(
        n_embd=32,
        n_head=4,
        n_layer=1,
        block_size=8,
        vocab_size=64,
        dropout=0.0,
        bias=False,
    )
    assert CausalSelfAttention(cfg).flash is False


def test_tiny_gpt_forward_shape_when_torch_available():
    torch = pytest.importorskip("torch")
    from tests.fixtures.nanogpt.model import GPT, GPTConfig

    cfg = GPTConfig(
        n_embd=32,
        n_head=4,
        n_layer=1,
        block_size=8,
        vocab_size=64,
        dropout=0.0,
        bias=False,
    )
    model = GPT(cfg).eval()
    idx = torch.randint(0, 64, (1, 8))
    with torch.no_grad():
        logits, loss = model(idx)
    assert logits.shape == (1, 8, 64)
    assert loss is None
