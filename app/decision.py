import os
import re
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel
from openai import OpenAI
import rag
from schema import Certificate

client = OpenAI()
MODEL = os.getenv("REASONING_MODEL", "gpt-4.1")
MIN_CONF = 0.7
BORDERLINE_ONE_SIDED = 0.02
BORDERLINE_BAND = 0.10
ORDER = ["RELEASE", "REVIEW", "HOLD", "REJECT"]

TO_MPA = {"mpa": 1.0, "psi": 1 / 145.038, "ksi": 1000 / 145.038}
TO_MM = {"mm": 1.0, "in": 25.4, "inch": 25.4, "inches": 25.4}
TO_UM = {"um": 1.0, "µm": 1.0, "micron": 1.0, "microns": 1.0, "mil": 25.4}


class Limit(BaseModel):
    test: str
    min: Optional[float]
    max: Optional[float]
    unit: str
    required_numeric: bool


class Limits(BaseModel):
    limits: list[Limit]


class Finding(BaseModel):
    test: str
    status: Literal["ok", "borderline", "out_of_spec", "missing", "pass_only", "unit_unknown", "low_confidence"]
    detail: str


class Verdict(BaseModel):
    outcome: Literal["RELEASE", "REVIEW", "HOLD", "REJECT"]
    reasons: list[str]
    findings: list[Finding]
    vendor_block: Optional[str]
    spec_block: Optional[str]
    policy_used: list[str]
    human_summary: str


def _limits_from_spec(spec_text: str) -> list[Limit]:
    prompt = f"""Turn this specification into limits. One entry per test line.
Units must be one of MPa, mm, um, %, HRB, HRC. Use null for a missing min or max.
required_numeric is true only where the line says REQUIRED.

{spec_text}"""
    resp = client.chat.completions.parse(model=MODEL, messages=[{"role": "user", "content": prompt}], response_format=Limits)
    return resp.choices[0].message.parsed.limits


def _part_allowed(vendor_block: str, part: str) -> bool:
    m = re.search(r"Approved parts:\s*(.+)", vendor_block)
    if not m:
        return False
    allowed = [rag._norm(p) for p in m.group(1).split(",")]
    return rag._norm(part) in allowed


def _convert(value, unit, target):
    u, t = (unit or "").lower().strip(), target.lower()
    if u == t or (u == "" and t in ("%", "hrb", "hrc")):
        return value
    table = {"mpa": TO_MPA, "mm": TO_MM, "um": TO_UM}.get(t)
    if table and u in table:
        return value * table[u]
    return None


def _margin(lo, hi):
    if lo is not None and hi is not None:
        return BORDERLINE_BAND * (hi - lo)
    return BORDERLINE_ONE_SIDED * abs(lo if lo is not None else hi)


def decide(cert: Certificate) -> Verdict:
    if cert.document_type != "certificate":
        return Verdict(outcome="REJECT", reasons=["Attachment is not a certificate (policy item 7)"], findings=[],
                       vendor_block=None, spec_block=None, policy_used=[],
                       human_summary="Not a certificate. Ask the sender for the CoA or CoC.")

    outcome = "RELEASE"
    reasons, findings = [], []

    def bump(to):
        nonlocal outcome
        if ORDER.index(to) > ORDER.index(outcome):
            outcome = to

    vendor_block = rag.find_vendor(cert.vendor_name)
    if vendor_block is None:
        reasons.append(f"Vendor '{cert.vendor_name}' is not on the Approved Vendor List (policy item 1)")
        bump("HOLD")
    elif not _part_allowed(vendor_block, cert.part_number or ""):
        reasons.append(f"Vendor is approved but not for part {cert.part_number} (policy item 1)")
        bump("HOLD")

    spec_block = rag.find_spec(cert.part_number)
    if spec_block is None:
        reasons.append(f"No specification on file for part '{cert.part_number}'")
        bump("HOLD")

    if not cert.customer_po:
        reasons.append("No customer PO on certificate (policy item 5)")
        bump("REVIEW")
    if cert.issue_date:
        try:
            if (date.today() - date.fromisoformat(cert.issue_date)).days > 90:
                reasons.append("Certificate older than 90 days (policy item 6)")
                bump("HOLD")
        except ValueError:
            reasons.append(f"Unreadable issue date '{cert.issue_date}'")
            bump("REVIEW")
    if cert.overall_confidence < MIN_CONF:
        reasons.append(f"Extraction confidence {cert.overall_confidence:.2f} below {MIN_CONF} (policy item 8)")
        bump("REVIEW")

    limits = _limits_from_spec(spec_block) if spec_block else []
    by_name = {t.name: t for t in cert.tests}
    for lim in limits:
        t = by_name.get(lim.test)
        if t is None:
            findings.append(Finding(test=lim.test, status="missing", detail="not on certificate"))
            bump("HOLD" if lim.required_numeric else "REVIEW")
            continue
        if t.pass_only or t.value is None:
            findings.append(Finding(test=lim.test, status="pass_only", detail=f"'{t.raw_text}' has no numeric value"))
            bump("HOLD" if lim.required_numeric else "REVIEW")
            continue
        if t.confidence < MIN_CONF:
            findings.append(Finding(test=lim.test, status="low_confidence", detail=f"confidence {t.confidence:.2f} on '{t.raw_text}'"))
            bump("REVIEW")
        v = _convert(t.value, t.unit, lim.unit)
        if v is None:
            findings.append(Finding(test=lim.test, status="unit_unknown", detail=f"cannot convert '{t.unit}' to {lim.unit}"))
            bump("REVIEW")
            continue
        converted = (t.unit or "").lower() != lim.unit.lower()
        shown = f"{t.value:g} {t.unit} = {v:.2f} {lim.unit}" if converted else f"{v:g} {lim.unit}"
        lo, hi = lim.min, lim.max
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            findings.append(Finding(test=lim.test, status="out_of_spec", detail=f"{shown}, spec {lo}..{hi}"))
            bump("HOLD")
            continue
        margin = _margin(lo, hi)
        near_lo = lo is not None and abs(v - lo) <= margin
        near_hi = hi is not None and abs(v - hi) <= margin
        if near_lo or near_hi:
            findings.append(Finding(test=lim.test, status="borderline", detail=f"{shown}, within {margin:g} {lim.unit} of limit (policy item 3)"))
            bump("REVIEW")
            continue
        findings.append(Finding(test=lim.test, status="ok", detail=f"{shown}, spec {lo}..{hi}"))

    reasons += [f"{f.test}: {f.status} ({f.detail})" for f in findings if f.status != "ok"]
    if not reasons:
        reasons.append("Approved vendor and part, all tests present, numeric and in spec")

    policy_used = rag.policy_context(" ".join(reasons), n=3)
    summary = _summary(cert, outcome, reasons, findings, policy_used, spec_block)
    return Verdict(outcome=outcome, reasons=reasons, findings=findings, vendor_block=vendor_block,
                   spec_block=spec_block, policy_used=policy_used, human_summary=summary)


def _summary(cert, outcome, reasons, findings, policy_used, spec_block):
    prompt = f"""Write 3 to 5 plain sentences for a QA engineer. No bullets, no markdown.
Outcome: {outcome}
Certificate: vendor={cert.vendor_name}, part={cert.part_number}, lot={cert.lot_number}
Reasons: {reasons}
Findings: {[f.model_dump() for f in findings]}
Quote the exact policy or spec line that drove the decision from these:
Policy: {policy_used}
Spec: {spec_block}"""
    resp = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content.strip()