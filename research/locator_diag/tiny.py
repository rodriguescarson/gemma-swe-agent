import sys, re
for f in sys.argv[1:]:
    s = open(f).read()
    head, _, rest = s.partition("----- LOCATOR TOOL USES")
    uses, _, reply = rest.partition("----- REPLY:")
    hl = head.split("\n")
    print("\n".join(hl[:4]))
    m = re.search(r"ISSUE \((\d+) chars\):\n(.*)", head, re.S)
    print("ISSUE:", m.group(2)[:350].replace("\n", " | ") if m else "")
    for ln in uses.split("\n"):
        if re.match(r"^\[\d+\]", ln):
            print("  " + ln[:210])
        elif re.match(r"^    OUT: (\d+\. |REPRO|GREP|LOCATE: |no matches|exit=)", ln) or re.match(r"^    (LOCATOR|EDIT NOW|CONTEXT|NOTE)", ln) or re.match(r"^    [123]\. ", ln):
            print("      " + ln.strip()[:170])
    print("REPLY:", reply.strip()[:700].replace("\n", " | "))
    print()
