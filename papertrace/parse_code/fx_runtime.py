"""这次追踪是怎么跑的：设备、torch 版本、dtype、实际 batch/seq_len、示例输入。

与 input_specs 无关，所以单独一个文件（fx_signature 只管「谁是权重/输入/常量」）。
不 import torch：只读传进来的张量与模块属性，没装 torch 的机器也能 import 本模块。
"""

from papertrace.parse_code.fx_graph import all_val_shapes, val_dtype, val_shape


def runtime_meta(module, torch_mod, example_inputs) -> dict:
    """把「这次追踪到底怎么跑的」记进 trace，不然结果无法复现也无法解释。"""
    shapes = []
    for item in example_inputs:
        if isinstance(item, (list, tuple)):
            shapes.extend(all_val_shapes(item))
        else:
            shape = val_shape(item)
            if shape is not None:
                shapes.append(shape)
    dtype = val_dtype(example_inputs[0]) if example_inputs else None
    return {
        "ok": True,
        "reason": None,
        "device": "cpu",
        "torch_version": str(getattr(torch_mod, "__version__", "")),
        "dtype": dtype,
        "batch": shapes[0][0] if shapes and shapes[0] else None,
        "seq_len": shapes[0][1] if shapes and len(shapes[0]) > 1 else None,
        "entry": f"{type(module).__module__}.{type(module).__name__}",
        "example_inputs": shapes,
    }
