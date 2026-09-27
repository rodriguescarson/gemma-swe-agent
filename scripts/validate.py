"""Compile a submission dir with the organisers' own compiler, exactly as agent_runner does (tools bound to a mock ctx).
Usage: python scripts/validate.py submissions/v0"""
import sys, os
from unittest.mock import MagicMock
from adk_submission import compile_submission, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS
from swegemma.tools import create_tools
from swegemma.models import setup_gemma_model_registry
from swegemma.models.discovery import validate_single_declared_model
from swegemma.config import build_submission_limits

d = sys.argv[1]
model = validate_single_declared_model(d)
assert model.split('/')[-1] == "gemma-4-31b-it-qat-w4a16-ct", model
limits, gen = build_submission_limits()
adapters = discover_adapters(d, adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
agent = compile_submission(submission_dir=d, adapter_manifest=adapters, tool_registry=create_tools(MagicMock()),
                           model_registry=setup_gemma_model_registry(), limits=limits, generation_constraints=gen)
def show(a, depth=0):
    tools = [getattr(t, 'name', getattr(t, '__name__', type(t).__name__)) for t in getattr(a, 'tools', [])]
    gcc = getattr(a, 'generate_content_config', None)
    print('  '*depth + f"{type(a).__name__} {a.name} model={getattr(getattr(a,'model',None),'model',getattr(a,'model',None))} tools={tools}")
    if gcc is not None and depth == 0: print('  '*depth + f"  gen: {gcc.model_dump(exclude_none=True)}")
    for s in getattr(a, 'sub_agents', []) or []: show(s, depth+1)
show(agent)
size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs)
print(f"OK model={model} unpacked={size/1e6:.2f} MB")
