"""Connection topology of a .nk file, read the way Nuke reads it (no Nuke needed).

    python tests/nk_topology.py <file.nk>

Nuke serialises the node graph as a stack program: every node pops its `inputs` from the
stack -- the TOP of the stack is input 0, the next one input 1, ... -- and then pushes
itself; `set <var> [stack N]` names the stack entry N below the top, `push $<var>` pushes a
named entry again, `push 0` pushes an empty input.  Node positions (xpos / ypos) play no part.
Returns {node name: [input 0 name, input 1 name, ...]} (None = not connected).
"""
import json
import re
import sys

NO_INPUT_DEFAULT = {"Read", "BackdropNode", "StickyNote", "Constant", "CheckerBoard2", "ColorBars"}


def _blocks(text):
    """top-level statements: ('node', class, body lines) | ('set', var, depth) | ('push', var) | other"""
    lines = text.replace("\r\n", "\n").split("\n")
    i, out = 0, []
    while i < len(lines):
        ln = lines[i].strip()
        m = re.match(r"^([A-Za-z_][\w.]*)\s*\{\s*$", ln)
        if m:
            depth, body, i = 1, [], i + 1
            while i < len(lines) and depth:
                esc = False
                for ch in lines[i]:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                if depth:
                    body.append(lines[i])
                i += 1
            out.append(("node", m.group(1), body))
            continue
        m = re.match(r"^set\s+(\S+)\s+\[stack\s+(\d+)\]$", ln)
        if m:
            out.append(("set", m.group(1), int(m.group(2))))
        m2 = re.match(r"^push\s+(\S+)$", ln)
        if m2:
            out.append(("push", m2.group(1)))
        i += 1
    return out


def topology(path):
    stack, named, graph = [], {}, {}
    for b in _blocks(open(path, encoding="utf-8").read()):
        if b[0] == "set":   # copy-paste files start with "set cut_paste_input [stack 0]" on an empty stack
            named[b[1]] = stack[-1 - b[2]] if len(stack) > b[2] else None
        elif b[0] == "push":
            stack.append(None if b[1] == "0" else named[b[1].lstrip("$")])
        elif b[0] == "node":
            cls, body = b[1], b[2]
            if cls == "Root" or cls.startswith("define_"):
                continue
            knobs = {}
            for ln in body:
                m = re.match(r"^\s(\w+)\s+(.*)$", ln)
                if m and m.group(1) not in knobs:
                    knobs[m.group(1)] = m.group(2).strip()
            n_in = int(re.match(r"\d+", knobs["inputs"]).group(0)) if "inputs" in knobs else (0 if cls in NO_INPUT_DEFAULT else 1)
            name = knobs.get("name", cls).strip('"')
            ins = [stack.pop() if stack else None for _ in range(n_in)]   # top of stack = input 0
            graph[name] = {"class": cls, "inputs": ins}
            stack.append(name)
    return graph


def layout(path, strip_suffix=False):
    """{node name: {xpos, ypos[, bdwidth, bdheight]}} of every node; strip_suffix removes the trailing
    digits Nuke appends to pasted copies (BD_SOURCE1 -> BD_SOURCE)."""
    out = {}
    for b in _blocks(open(path, encoding="utf-8").read()):
        if b[0] != "node" or b[1] == "Root" or b[1].startswith("define_"):
            continue
        knobs = {}
        for ln in b[2]:
            m = re.match(r"^\s(\w+)\s+(.*)$", ln)
            if m and m.group(1) not in knobs:
                knobs[m.group(1)] = m.group(2).strip()
        name = knobs.get("name", b[1]).strip('"')
        if strip_suffix:
            name = re.sub(r"\d+$", "", name)
        out[name] = {k: int(knobs[k]) for k in ("xpos", "ypos", "bdwidth", "bdheight") if k in knobs}
    return out


def sticky_label(path, name="LENS_INFO"):
    """the StickyNote label as Nuke reads it (\\n -> newline, quotes removed)"""
    for b in _blocks(open(path, encoding="utf-8").read()):
        if b[0] == "node" and b[1] == "StickyNote":
            for ln in b[2]:
                m = re.match(r'^\slabel\s+"(.*)"\s*$', ln)
                if m and any(re.match(rf"^\sname\s+{name}\d*$", x) for x in b[2]):
                    return m.group(1).replace("\\n", "\n").replace('\\"', '"')
    return None


def connections(path, classes=("STMap", "Crop", "Read", "Viewer")):
    return {k: v["inputs"] for k, v in topology(path).items() if v["class"] in classes}


if __name__ == "__main__":
    print(json.dumps(connections(sys.argv[1]), indent=1))
