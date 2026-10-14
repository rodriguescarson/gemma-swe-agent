"""Agent replies whose message text carries a Gemma-native tool call (`call:name{`, `<tool_call|>`, `<|tool_call>`) instead
of a parsed tool call, per run: how many, in which tasks, at which agent reply (0 = first), and whether that reply also had
a parsed call. Reads only committed traces.

    python scripts/forty_two/text_call_leaks.py eval/a6000/results/p4_b1024 eval/a6000/results/p4_v0t2 ..."""
import glob, json, os, re, sys

PAT = re.compile(r"call:\w+\{|<tool_call\|>|<\|tool_call>")


def leaks(run):
    out, n_replies = {}, 0
    for f in sorted(glob.glob(os.path.join(run, "results", "traces", "trace_*.json"))):
        d = json.load(open(f))
        tid = os.path.basename(f)[len("trace_"):-len(".json")]
        for i, s in enumerate(x for x in d["steps"] if x["source"] == "agent"):
            n_replies += 1
            if PAT.search(s.get("message") or ""):
                out.setdefault(tid, []).append((i, bool(s.get("tool_calls"))))
    return n_replies, out


def main():
    for run in sys.argv[1:]:
        n, out = leaks(run)
        print(f"{run}: {sum(len(v) for v in out.values())} leaked replies of {n} agent replies, in {len(out)} tasks")
        for tid, v in out.items():
            print(f"    {tid}: reply index {[i for i, _ in v]}, parsed call in the same reply {[c for _, c in v]}")


if __name__ == "__main__":
    main()
