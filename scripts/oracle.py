"""Oracle run: replace the agent with each task's reference patch, verify exactly as the harness does.
Usage: python scripts/oracle.py eval --tasks ... (same args as `swegemma eval`)"""
import sys
from adk_eval_core.tracing import SessionTrace
import swegemma.evaluate as ev
async def _oracle(self, task, snapshot_path, task_index, total_tasks, **kw):
    return task.patch, None, SessionTrace()
ev.Evaluator._run_agent_sandbox = _oracle
from swegemma.cli import main
sys.exit(main())
