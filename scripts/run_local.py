import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from dotenv import load_dotenv
load_dotenv()
import rag
from extractor import extract
from decision import decide

rag.build_index()
cert = extract(open(sys.argv[1], "rb").read())
print("EXTRACTED")
print(json.dumps(cert.model_dump(), indent=2))
verdict = decide(cert)
print("\nVERDICT:", verdict.outcome)
for r in verdict.reasons:
    print(" -", r)
print()
print(verdict.human_summary)