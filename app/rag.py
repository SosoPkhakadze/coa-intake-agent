import glob
import os
import re
import chromadb
from rapidfuzz import fuzz, process, utils

KB_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge_base")
DB_DIR = os.path.join(os.path.dirname(__file__), "..", ".chroma")
PROSE_FILES = ["qa_policy.md", "vendor_agreements.md", "inspection_procedure.md"]
_col = chromadb.PersistentClient(path=DB_DIR).get_or_create_collection("qa_knowledge")

VENDORS = {}
SPECS = {}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _sections(path):
    text = open(path, encoding="utf-8").read()
    for block in re.split(r"\n(?=## )", text)[1:]:
        title = block.splitlines()[0].lstrip("# ").strip()
        yield title, block.strip()


def _paragraphs(path):
    text = open(path, encoding="utf-8").read()
    heading = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para or para.startswith("# "):
            continue
        if para.startswith("## "):
            heading = para.lstrip("# ").strip()
            continue
        for line in re.split(r"\n(?=\d+\.\s)", para):
            line = line.strip()
            if line:
                yield (f"[{heading}] " if heading else "") + line


def load_lookups():
    VENDORS.clear()
    for title, block in _sections(os.path.join(KB_DIR, "approved_vendors.md")):
        m = re.search(r"Aliases:\s*(.+)", block)
        aliases = [a.strip() for a in m.group(1).split(",")] if m else []
        VENDORS[title] = {"text": block, "names": [title] + aliases}
    SPECS.clear()
    for title, block in _sections(os.path.join(KB_DIR, "part_specs.md")):
        SPECS[_norm(title.split()[0])] = block


def find_vendor(name, threshold=85):
    if not name:
        return None
    best = None
    for vendor, data in VENDORS.items():
        match = process.extractOne(name, data["names"], scorer=fuzz.token_set_ratio, processor=utils.default_process)
        if match and (best is None or match[1] > best[1]):
            best = (vendor, match[1])
    return VENDORS[best[0]]["text"] if best and best[1] >= threshold else None


def find_spec(part):
    return SPECS.get(_norm(part))


def build_index():
    load_lookups()
    ids, docs, metas = [], [], []
    for name in PROSE_FILES:
        for i, chunk in enumerate(_paragraphs(os.path.join(KB_DIR, name))):
            ids.append(f"{name}-{i}")
            docs.append(chunk)
            metas.append({"source": name})
    _col.upsert(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def retrieve(query, n=3, source=None):
    res = _col.query(query_texts=[query], n_results=n, where={"source": source} if source else None)
    return res["documents"][0]


def policy_context(topic, n=3):
    return retrieve(topic, n, "qa_policy.md")


def vendor_clauses(vendor_name, topic, n=3):
    return retrieve(f"{vendor_name}: {topic}", n, "vendor_agreements.md")