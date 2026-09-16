import datetime
import json
import os
import uuid
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()
import rag
from extractor import extract
from decision import decide

app = FastAPI(title="CoA Intake Agent")
RUNS_DIR = os.path.join(os.path.dirname(__file__), "..", "runs")
os.makedirs(RUNS_DIR, exist_ok=True)
ACCEPTED = {"application/pdf", "image/png", "image/jpeg"}


@app.on_event("startup")
def startup():
    print("policy chunks indexed:", rag.build_index())


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/process")
async def process(file: UploadFile = File(...), sender: str = Form(""), subject: str = Form("")):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty attachment")
    run_id = uuid.uuid4().hex[:8]
    base = {"run_id": run_id, "received_at": datetime.datetime.utcnow().isoformat(),
            "sender": sender, "subject": subject, "filename": file.filename}

    if file.content_type not in ACCEPTED:
        result = {**base, "route": "reject", "error": f"unsupported attachment type {file.content_type}"}
        return _save(result)

    try:
        cert = extract(data, file.content_type)
        verdict = decide(cert)
    except Exception as e:
        result = {**base, "route": "review", "error": str(e)}
        return _save(result)

    result = {**base, "route": verdict.outcome.lower(), "extracted": cert.model_dump(), "verdict": verdict.model_dump()}
    return _save(result)


def _save(result):
    with open(os.path.join(RUNS_DIR, f"{result['run_id']}.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return JSONResponse(result)