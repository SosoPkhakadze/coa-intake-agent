import glob
import os
import re
import chromadb
from rapidfuzz import fuzz, process, utils

KB_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge_base")
DB_DIR = os.path.join(os.path.dirname(__file__), "..", ".chroma")
_col = chromadb.PersistentClient(path=DB_DIR).get_or_create_collection("qa_policy")

VENDORS = {}
SPECS = {}


def _sections(path):
    text = open(path, encoding="utf-8").read()
    for block in re.split(r"\n(?=## )", text)[1:]:
        title = block.splitlines()[0].lstrip("# ").strip()
        yield title, block.strip()


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_lookups():
    VENDORS.clear()
    for title, block in _sections(os.path.join(KB_DIR, "approved_vendors.md")):
        m = re.search(r"Aliases:\s*(.+)", block)
        aliases = [a.strip() for a in m.group(1).split(",")] if m else []
        VENDORS[title] = {"text": block, "names": [title] + aliases}
    SPECS.clear()
    for title, block in _sections(os.path.join(KB_DIR, "part_specs.md")):
        SPECS[_norm(title.split()[0])] = {"part": title.split()[0], "text": block}


def find_vendor(name, threshold=85):
    if not name:
        return None
    best = None
    for vendor, data in VENDORS.items():
        match = process.extractOne(name, data["names"], scorer=fuzz.token_set_ratio, processor=utils.default_process)
        if match and (best is None or match[1] > best[1]):
            best = (vendor, match[1])
    if best and best[1] >= threshold:
        return VENDORS[best[0]]["text"]
    return None


def find_spec(part):
    hit = SPECS.get(_norm(part))
    return hit["text"] if hit else None


def build_policy_index():
    lines = [l.strip() for l in open(os.path.join(KB_DIR, "qa_policy.md"), encoding="utf-8") if re.match(r"^\d+\.", l)]
    _col.upsert(ids=[f"policy-{i}" for i in range(len(lines))], documents=lines)
    return len(lines)


def policy_context(topic, n=3):
    res = _col.query(query_texts=[topic], n_results=n)
    return res["documents"][0]


def build_index():
    load_lookups()
    return build_policy_index()