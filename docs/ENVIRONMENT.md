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

### 0.1 装 torch（M1a 真实算子追踪需要）

```bat
cd /d D:\AgentPrograms\PaperTrace
python tmpinstall\fetch_deps.py pydeps wheels torch
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -c "import torch; print(torch.__version__)"
```

实测结果：`torch-2.15.0+cpu`，Windows PyPI 轮子就是 CPU 版，正好合「探针默认 CPU」。
下载断过线：`fetch_deps.py` 带 Range 断点续传（最多 8 次重试、按 PyPI JSON 的 size 校验、BadZipFile 重下），
重新执行同一条命令会从断点接着下，不会从头来。

**坑：机器级 `TORCHINDUCTOR_CACHE_DIR`。** 本机装过 Unsloth Studio，把该变量设成了
`C:\Users\niangao\.unsloth\studio\cache\torchinductor`。这个目录在沙箱里不可写，
而 `torch.export` / `make_fx` 都会拉起 inductor，于是 `import torch._dynamo` 会抛
`PermissionError: [WinError 5] 拒绝访问`。

`papertrace/parse_code/fx_trace.py` 的 `_ensure_export_cache()` 处理了这件事：先探测那个目录能不能写
（写一个 `.papertrace-write-probe`），能写就尊重用户配置；不能写才退到 `%TEMP%\papertrace-torch-cache`
或当前目录下的 `papertrace-torch-cache`。**不覆盖**用户的环境变量。

### 0.2 已装版本清单（`pydeps/` 实测，2026-11-19）

`wheels/`（134MB 的 .whl 下载缓存，其中 torch 一个 126MB）已于 2026-11-19 删除。
`fetch_deps.py` 按包名取 PyPI **最新版**，所以重装时要按下表钉版本，否则版本会漂：

```
attrs==26.1.0                 colorama==0.4.6            exceptiongroup==1.3.1
filelock==4.2.10              fsspec==2026.9.0           iniconfig==2.3.1
jinja2==3.1.6                 jsonschema==4.26.0         jsonschema-specifications==2025.9.1
markupsafe==3.0.4             mpmath==1.4.1              networkx==3.7
packaging==26.3               pluggy==1.7.0              pygments==2.21.0
pytest==9.2.0                 referencing==0.37.0        rpds-py==2026.9.1
setuptools==84.2.1            sympy==1.14.0              tomli==2.5.0
torch==2.15.0                 typing-extensions==4.16.0
```

注意 `tmpinstall/requirements-framework.txt` 里记的 pluggy/packaging/pygments/attrs/rpds-py
是 2026-11-14 的旧观测，实际解到 `pydeps/` 的版本以上表为准（PyPI 已更新）。

## 1. 安装 Python 3.11（可选）

**框架切片不需要这一步**，系统 3.13.15 就能跑测试。等你真要跑 fx / 探针时再装。

在「以管理员身份」的终端执行（可复制）：

```bat
winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
```

装完**新开**一个终端，确认：

```bat
py -3.11 --version
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

## 3. 拉本地模型（**框架阶段不要做**；等 M3 接对齐时再回来）

先装 Ollama：`winget install Ollama.Ollama`。默认 7B，不要默认 14B。

```bat
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
ollama list
```

14B 仅在「只做对齐、不跑 forward 探针」时可选：`ollama pull qwen2.5-coder:14b`。日常开发禁止两条同时占 GPU。

## 4. 自检

框架切片（不需要 venv、不需要 Ollama、不需要 torch）：

```bat
cd /d D:\AgentPrograms\PaperTrace
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -m pytest -q
```

预期全绿（当前 93 passed、2 skipped；skip 的两条要 torch，装了就自动跑）。装上 torch 后：

```bat
.venv\Scripts\python.exe -c "import torch; print(torch.__version__)"
.venv\Scripts\python.exe -m pytest -q
```

Ollama 的 `curl http://127.0.0.1:11434/api/tags` **不再是自检项**（S13：默认 backend=offline）。
