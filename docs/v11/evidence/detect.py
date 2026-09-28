"""Run vLLM 0.19.1's own chat-template content-format detection (vllm/renderers/hf.py, fetched from
https://raw.githubusercontent.com/vllm-project/vllm/v0.19.1/vllm/renderers/hf.py into VLLM_HF_PY) on the June template.
Result 2026-09-28: 'openai' (string contents are wrapped as [{"type":"text",...}] before the template runs)."""
import logging, os
from collections import deque
from functools import lru_cache
import jinja2, jinja2.nodes
src = open(os.environ.get("VLLM_HF_PY", "vllm_renderers_hf.py")).read()
start = src.index("def _is_var_access"); end = src.index("def _resolve_chat_template_content_format")
ns = {"jinja2": jinja2, "deque": deque, "lru_cache": lru_cache, "logger": logging.getLogger("x"), "ChatTemplateContentFormat": str}
exec(src[start:end], ns)
t = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_template_kaggle_v2_june.jinja")).read()
print("chat_template_kaggle_v2_june.jinja ->", ns["_detect_content_format"](t, default="string"))
