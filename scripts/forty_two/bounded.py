"""Run a command with a memory ceiling (summed RSS of its whole process group) and a wall-time ceiling; for test runs on the
16 GB Mac (2026-10-14: rich_3480's pytest reached 4.3 GB RSS). Exit codes: the command's own, 137 when killed for memory,
124 on the time limit.

    python scripts/forty_two/bounded.py --mb 1500 --secs 120 -- python -m pytest tests/test_x.py -x -q"""
import argparse, os, signal, subprocess, sys, time


def group_rss_mb(pgid):
    out = subprocess.run(["ps", "-axo", "pgid=,rss="], capture_output=True, text=True).stdout
    return sum(int(r) for g, r in (l.split() for l in out.splitlines() if l.strip()) if int(g) == pgid) / 1024


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--mb", type=float, default=1500); ap.add_argument("--secs", type=float, default=300)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args(); cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    p = subprocess.Popen(cmd, start_new_session=True)            # its own process group: grandchildren are counted and killed
    t0 = time.time()
    while p.poll() is None:
        rss = group_rss_mb(p.pid)
        if rss > a.mb or time.time() - t0 > a.secs:
            os.killpg(p.pid, signal.SIGKILL); p.wait()
            if rss > a.mb:
                print(f"bounded: killed, RSS {rss:.0f} MB > {a.mb:.0f} MB after {time.time() - t0:.0f} s", file=sys.stderr); sys.exit(137)
            print(f"bounded: timed out after {a.secs:.0f} s", file=sys.stderr); sys.exit(124)
        time.sleep(0.25)
    sys.exit(p.returncode)


if __name__ == "__main__":
    main()
