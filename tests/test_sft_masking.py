"""Span masking for Gemma 4's chat format: prefix-diff masking supervised only 0.6% of tokens because the template merges
assistant messages into one model turn and inlines tool responses."""
import ast, pathlib
src = (pathlib.Path(__file__).parent.parent / "train/sft.py").read_text()
mod = ast.parse(src); ns = {}
for node in mod.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "MODEL_OPEN" for t in getattr(node.targets[0], "elts", [])) or \
       isinstance(node, ast.FunctionDef) and node.name == "supervised_char_spans":
        exec(compile(ast.Module([node], []), "sft", "exec"), ns)
spans_of = ns["supervised_char_spans"]

def picked(text): return "".join(text[a:b] for a, b in spans_of(text))

TXT = ("<|turn>system\nSYS<turn|>\n<|turn>user\nFIX IT<turn|>\n<|turn>model\nThinking. <|tool_call>call:read_file{}<tool_call|>"
       "<|tool_response>response:read_file{SECRET FILE}<tool_response|>Now edit.<|tool_call>call:submit_patch{}<tool_call|><turn|>\n")

def test_supervises_model_text_and_calls():
    p = picked(TXT)
    assert "Thinking." in p and "call:read_file" in p and "Now edit." in p and "call:submit_patch" in p

def test_never_supervises_tool_output_system_or_user():
    p = picked(TXT)
    assert "SECRET FILE" not in p and "SYS" not in p and "FIX IT" not in p

def test_supervises_turn_close_so_the_model_learns_to_stop():
    assert picked(TXT).endswith("<turn|>")

def test_multiple_model_turns():
    t = TXT + "<|turn>user\nagain<turn|>\n<|turn>model\nSecond answer<turn|>\n"
    p = picked(t)
    assert "Second answer" in p and "again" not in p

def test_sft_refuses_empty_data_and_never_divides_by_zero_steps():
    assert "NO TRAINABLE EXAMPLES" in src                  # smoke run once crashed with ZeroDivisionError on 0 examples
    assert "steps = max(1," in src

def test_smoke_selection_cannot_be_empty():
    chain = (pathlib.Path(__file__).parent.parent / "pod/chain_train1.sh").read_text()
    assert "sorted(rows" in chain and "assert len(short) >= 30" in chain   # a 45k-char cutoff selected 0 of 6,395
