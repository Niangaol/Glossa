# PaperTrace 本机环境（Windows）

实测日期：2026-11-14。机器：机械革命苍龙 16x Pro，GPU RTX 5070 Ti Laptop 12GB（驱动 621.01）。系统 Python 3.13.15，无 `py` launcher，Ollama 当时未装。

> **框架阶段不要执行第 3 节（Ollama / 7B）。**
> 用户 2026-11-14 拍板：先搭框架，不安装本地模型。默认后端是 `offline`，任何要模型的地方会直接报 `LLMUnavailable`。第 3 节留在这里，等真要接对齐（M3）时再执行。

规格要求 Python 3.11。不要用系统 3.13 跑 fx / 探针。

## 0. 框架切片怎么装依赖（本机实测，2026-11-14）

本机 `python -m venv` 的 ensurepip 会失败，`pip install` 在 DSH 沙箱下会稳定报
`PermissionError: [Errno 13] ... .whl.metadata`（pip 解包临时目录被拦）。框架切片改用
仓库内 `pydeps/`：

```bat
cd /d D:\AgentPrograms\PaperTrace
python tmpinstall\fetch_deps.py pydeps wheels pytest jsonschema
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -m pytest -q
```

`fetch_deps.py` 直接查 PyPI JSON、下载 wheel、用 zipfile 解到 `pydeps/`，绕开 pip 的临时目录。
`pydeps/` 与 `wheels/` 都在 .gitignore 里。

## 1. 安装 Python 3.11 与 Ollama

在「以管理员身份」的终端执行（可复制）：

```bat
winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements
```

装完**新开**一个终端，确认：

```bat
py -3.11 --version
ollama --version
```

若 `py` 仍不可用，用 `C:\Users\niangao\AppData\Local\Programs\Python\Python311\python.exe` 代替下文的 `py -3.11`。

## 2. 项目 venv

```bat
cd /d D:\AgentPrograms\PaperTrace
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\pip install pytest jsonschema sympy einops tree-sitter tree-sitter-python lancedb fastapi uvicorn httpx numpy
```

CUDA wheel 以能装上为准：5070 Ti 走 cu128；若官方索引报错，改 cu124 再试。装完：

```bat
.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_mem//1024**2, 'MiB')"
```

## 3. 拉本地模型（默认 7B，不要默认 14B）

```bat
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
ollama list
```

14B 仅在「只做对齐、不跑 forward 探针」时可选：`ollama pull qwen2.5-coder:14b`。日常开发禁止两条同时占 GPU。

## 4. 自检

```bat
.venv\Scripts\python.exe -m pytest tests/test_env.py -v
```

`test_env.py` 在 Task 0 落地。在那之前，至少要能 `import torch` 且 Ollama `curl http://127.0.0.1:11434/api/tags` 有 7B。
