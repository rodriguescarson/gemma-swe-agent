"""Static checks on pod scripts: each rule here is a failure that already cost a run."""
import pathlib, re
POD = pathlib.Path(__file__).parent.parent / "pod"

def test_vllm_env_pins_compatible_tokenizers():
    s = (POD / "bootstrap.sh").read_text()
    assert '"transformers==5.13.1"' in s and '"tokenizers==0.22.1"' in s   # --no-deps transformers pin needs tokenizers<=0.23.0

def test_vllm_env_has_no_adk():
    line = next(l for l in (POD / "bootstrap.sh").read_text().splitlines() if 'uv pip install -q "vllm==0.19.1"' in l)
    assert "google-adk" not in line                                          # adk and vllm's fastapi pin are unsatisfiable together

def test_eval_chains_gate_on_health():
    for p in POD.glob("chain_eval*.sh"):
        assert "pod/health.sh" in p.read_text(), p.name

def test_no_self_matching_pkill():
    for p in list(POD.glob("*.sh")):
        for line in p.read_text().splitlines():
            assert not re.search(r"pkill -f", line), (p.name, line)            # pkill -f matches the caller's own command line
            m = re.search(r'pgrep -f "([^"]+)"', line) or re.search(r"pgrep -f '([^']+)'", line)
            if m and "$pat" not in m.group(1):
                assert m.group(1).startswith("^"), (p.name, line)             # unanchored patterns self-match the ssh caller

def test_chains_self_stop():
    for p in POD.glob("chain_*.sh"):
        if p.name == "chain_boot.sh": continue
        assert "runpodctl stop pod" in p.read_text(), p.name

def test_chains_back_up_before_stopping():
    for p in POD.glob("chain_*.sh"):
        if p.name == "chain_boot.sh": continue
        lines = [l for l in p.read_text().splitlines() if "runpodctl stop pod" in l]
        assert lines and all("pod/backup.sh" in l and "&&" in l for l in lines), p.name   # stop only if backup verified

def test_backup_verifies_upload():
    s = (POD / "backup.sh").read_text()
    assert "list_repo_tree" in s and "--private" in s and "BACKUP_FAILED" in s

def test_pod_uses_the_patched_wheelhouse_vllm():
    s = (POD / "bootstrap.sh").read_text()
    assert "metric/gemma-4-developer-agent-wheelhouse" in s and "supports_lora" in s  # PyPI vllm 0.19.1 refuses Gemma4 LoRA
    assert "issubclass(" not in s                                                       # SupportsLoRA is a Protocol: issubclass raises

def test_boot_chain_is_versioned():
    s = (POD / "chain_boot.sh").read_text()             # it once lived only in /tmp, so a fresh pod never booted
    for step in ("bootstrap.sh", "harness_env.sh", "buildenv.sh", "serve2.sh", "BOOT_CHAIN_DONE"):
        assert step in s, step

def test_benchmarks_are_gated_by_preflight():
    for p in POD.glob("chain_eval*.sh"):
        if p.name in ("chain_eval1.sh", "chain_eval2.sh"): continue      # historical chains launched before the gate existed
        assert "pod/preflight.sh" in p.read_text(), p.name

def test_preflight_covers_every_gate():
    s = (POD / "preflight.sh").read_text()
    for gate in ("compileall", "pytest", "supports_lora", "validate.py", "health.sh", "--lora-modules", '"model":"main_lora"'):
        assert gate in s, gate

def test_vllm_ports_avoid_runpod_nginx():
    # RunPod's nginx listens on 8001 (-> 8000), 3000, 7860, 8080, 9090: a server there never binds, and health checks
    # silently pass through nginx to another GPU's server (one H100 sat idle for a run).
    reserved = {"8001", "3000", "7860", "8080", "9090", "8000"}
    for p in POD.glob("*.sh"):
        for port in re.findall(r"(?:--port\s+|localhost:|127\.0\.0\.1:)\$?\(?\(?(\d{4})", p.read_text()):
            assert port not in reserved, (p.name, port)

def test_preflight_never_writes_pycache_into_bundles():
    s = (POD / "preflight.sh").read_text()
    assert "PYTHONPYCACHEPREFIX" in s and "PYTHONDONTWRITEBYTECODE=1" in s   # compileall once polluted every bundle

def test_every_abort_path_stops_the_pod():
    for p in POD.glob("chain_eval*.sh"):
        if p.name in ("chain_eval1.sh", "chain_eval2.sh"): continue
        for line in p.read_text().splitlines():
            if "ABORT" in line and "exit 1" in line:
                assert "stop_pod" in line, (p.name, line)                     # an abort once left the pod idle 2 h

def test_supervisor_runs_from_boot_and_stops_idle_pods_after_backup():
    boot = (POD / "chain_boot.sh").read_text(); sv = (POD / "supervisor.sh").read_text()
    assert "supervisor.sh" in boot
    assert "IDLE_MIN" in sv and "pod/backup.sh" in sv and "runpodctl stop pod" in sv and "supervisor.hb" in sv and "MAX_HOURS" in sv

def test_full_runs_are_preceded_by_a_canary():
    s = (POD / "chain_eval3.sh").read_text()
    assert s.index("pod/canary.sh") < s.index("run_eval.sh submissions/v7 p_v7")

def test_preflight_failures_name_the_failing_tests_and_keep_the_log():
    s = (POD / "preflight.sh").read_text()
    assert "eval/preflight_tests.log" in s and "^FAILED" in s      # the failing test once lived only in /tmp and was lost
