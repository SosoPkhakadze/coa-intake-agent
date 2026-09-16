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
ORDER = ["RELEASE", "REVIEW", "HOLD", "REJECT"]

TO_MPA = {"mpa": 1.0, "psi": 1 / 145.038, "ksi": 1000 / 145.038}
TO_MM = {"mm": 1.0, "in": 25.4, "inch": 25.4, "inches": 25.4}
TO_UM = {"um": 1.0, "µm": 1.0, "micron": 1.0, "microns": 1.0, "mil": 25.4}


class PolicyParams(BaseModel):
    min_confidence: float
    borderline_band_fraction: float
    borderline_one_sided_fraction: float
    max_certificate_age_days: int


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
    status: Literal["ok", "borderline", "out_of_spec", "missing", "pass_only", "unit_unknown", "low_confidence",
                    "unknown_vendor", "part_not_approved", "no_spec", "no_po", "expired", "bad_date"]
    severity: Literal["RELEASE", "REVIEW", "HOLD"]
    detail: str
    clause: Optional[str] = None


class Adjustment(BaseModel):
    test: str
    applies: bool
    severity: Optional[Literal["RELEASE", "REVIEW", "HOLD"]]
    clause: Optional[str]


class Adjustments(BaseModel):
    adjustments: list[Adjustment]


class Verdict(BaseModel):
    outcome: Literal["RELEASE", "REVIEW", "HOLD", "REJECT"]
    reasons: list[str]
    findings: list[Finding]
    policy_params: Optional[PolicyParams]
    spec_block: Optional[str]
    human_summary: str


_params: Optional[PolicyParams] = None


def policy_params() -> PolicyParams:
    global _params
    if _params is None:
        chunks = rag.retrieve("confidence threshold, borderline margin, tolerance band, certificate age in days", n=6)
        prompt = "Extract the numeric thresholds from these policy excerpts. Fractions as decimals (10 percent = 0.10).\n\n" + "\n".join(chunks)
        resp = client.chat.completions.parse(model=MODEL, messages=[{"role": "user", "content": prompt}], response_format=PolicyParams)
        _params = resp.choices[0].message.parsed
    return _params


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
    return rag._norm(part) in [rag._norm(p) for p in m.group(1).split(",")]


def _convert(value, unit, target):
    u, t = (unit or "").lower().strip(), target.lower()
    if u == t or (u == "" and t in ("%", "hrb", "hrc")):
        return value
    table = {"mpa": TO_MPA, "mm": TO_MM, "um": TO_UM}.get(t)
    if table and u in table:
        return value * table[u]
    return None


def _margin(p: PolicyParams, lo, hi):
    if lo is not None and hi is not None:
        return p.borderline_band_fraction * (hi - lo)
    return p.borderline_one_sided_fraction * abs(lo if lo is not None else hi)


def _header_findings(cert: Certificate, p: PolicyParams, vendor_block, spec_block) -> list[Finding]:
    out = []
    if vendor_block is None:
        out.append(Finding(test="vendor", status="unknown_vendor", severity="HOLD", detail=f"'{cert.vendor_name}' not on Approved Vendor List"))
    elif not _part_allowed(vendor_block, cert.part_number or ""):
        out.append(Finding(test="vendor", status="part_not_approved", severity="HOLD", detail=f"vendor not approved for {cert.part_number}"))
    if spec_block is None:
        out.append(Finding(test="spec", status="no_spec", severity="HOLD", detail=f"no specification on file for '{cert.part_number}'"))
    if not cert.customer_po:
        out.append(Finding(test="customer_po", status="no_po", severity="REVIEW", detail="no customer PO on certificate"))
    if cert.issue_date:
        try:
            age = (date.today() - date.fromisoformat(cert.issue_date)).days
            if age > p.max_certificate_age_days:
                out.append(Finding(test="issue_date", status="expired", severity="HOLD", detail=f"certificate is {age} days old"))
        except ValueError:
            out.append(Finding(test="issue_date", status="bad_date", severity="REVIEW", detail=f"unreadable date '{cert.issue_date}'"))
    if cert.overall_confidence < p.min_confidence:
        out.append(Finding(test="confidence", status="low_confidence", severity="REVIEW", detail=f"extraction confidence {cert.overall_confidence:.2f}"))
    return out


def _test_findings(cert: Certificate, p: PolicyParams, limits: list[Limit]) -> list[Finding]:
    out = []
    by_name = {t.name: t for t in cert.tests}
    for lim in limits:
        t = by_name.get(lim.test)
        if t is None:
            out.append(Finding(test=lim.test, status="missing", severity="HOLD" if lim.required_numeric else "REVIEW", detail="not on certificate"))
            continue
        if t.pass_only or t.value is None:
            if lim.min is None and lim.max is None and not lim.required_numeric:
                out.append(Finding(test=lim.test, status="ok", severity="RELEASE", detail=f"'{t.raw_text}' pass/fail test"))
            else:
                out.append(Finding(test=lim.test, status="pass_only", severity="HOLD" if lim.required_numeric else "REVIEW", detail=f"'{t.raw_text}' has no numeric value"))
            continue
        if t.confidence < p.min_confidence:
            out.append(Finding(test=lim.test, status="low_confidence", severity="REVIEW", detail=f"confidence {t.confidence:.2f} on '{t.raw_text}'"))
        v = _convert(t.value, t.unit, lim.unit)
        if v is None:
            out.append(Finding(test=lim.test, status="unit_unknown", severity="REVIEW", detail=f"cannot convert '{t.unit}' to {lim.unit}"))
            continue
        converted = (t.unit or "").lower() != lim.unit.lower()
        shown = f"{t.value:g} {t.unit} = {v:.2f} {lim.unit}" if converted else f"{v:g} {lim.unit}"
        lo, hi = lim.min, lim.max
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            out.append(Finding(test=lim.test, status="out_of_spec", severity="HOLD", detail=f"{shown}, spec {lo}..{hi}"))
            continue
        margin = _margin(p, lo, hi)
        if (lo is not None and abs(v - lo) <= margin) or (hi is not None and abs(v - hi) <= margin):
            out.append(Finding(test=lim.test, status="borderline", severity="REVIEW", detail=f"{shown}, within {margin:g} {lim.unit} of limit"))
            continue
        out.append(Finding(test=lim.test, status="ok", severity="RELEASE", detail=f"{shown}, spec {lo}..{hi}"))
    return out


def _apply_vendor_clauses(cert: Certificate, findings: list[Finding]) -> list[Finding]:
    open_findings = [f for f in findings if f.status != "ok"]
    if not open_findings or not cert.vendor_name:
        return findings
    clauses = set()
    for f in open_findings:
        clauses.update(rag.vendor_clauses(cert.vendor_name, f"{f.test} {f.status} {f.detail}"))
    prompt = f"""Vendor: {cert.vendor_name}
Certificate number: {cert.certificate_number}

Findings:
{[f.model_dump() for f in open_findings]}

Vendor agreement clauses:
{chr(10).join(clauses)}

For each finding, decide whether a clause for THIS vendor changes its severity. Only apply a clause that names this vendor and clearly covers the finding. If it applies, give the new severity and quote the clause verbatim. Otherwise applies=false."""
    resp = client.chat.completions.parse(model=MODEL, messages=[{"role": "user", "content": prompt}], response_format=Adjustments)
    by_test = {a.test: a for a in resp.choices[0].message.parsed.adjustments if a.applies and a.severity}
    for f in findings:
        a = by_test.get(f.test)
        if a:
            f.severity, f.clause = a.severity, a.clause
    return findings


def decide(cert: Certificate) -> Verdict:
    if cert.document_type != "certificate":
        return Verdict(outcome="REJECT", reasons=["Attachment is not a certificate"], findings=[], policy_params=None,
                       spec_block=None, human_summary="Not a certificate. Ask the sender for the CoA or CoC.")

    p = policy_params()
    vendor_block = rag.find_vendor(cert.vendor_name)
    spec_block = rag.find_spec(cert.part_number)
    limits = _limits_from_spec(spec_block) if spec_block else []

    findings = _header_findings(cert, p, vendor_block, spec_block) + _test_findings(cert, p, limits)
    findings = _apply_vendor_clauses(cert, findings)

    outcome = max((f.severity for f in findings), key=ORDER.index, default="RELEASE")
    reasons = [f"{f.test}: {f.status} ({f.detail})" + (f" [clause: {f.clause}]" if f.clause else "") for f in findings if f.severity != "RELEASE"]
    if not reasons:
        reasons.append("Approved vendor and part, all tests present, numeric and in spec")

    policy_used = rag.policy_context(" ".join(reasons), n=3)
    summary = _summary(cert, outcome, findings, policy_used, spec_block)
    return Verdict(outcome=outcome, reasons=reasons, findings=findings, policy_params=p, spec_block=spec_block, human_summary=summary)


def _summary(cert, outcome, findings, policy_used, spec_block):
    prompt = f"""Write 3 to 5 plain sentences for a QA engineer. No bullets, no markdown.
Outcome: {outcome}
Certificate: vendor={cert.vendor_name}, part={cert.part_number}, lot={cert.lot_number}
Findings: {[f.model_dump() for f in findings]}
Quote the exact policy line, spec line or vendor clause that drove the decision, from these:
Policy: {policy_used}
Spec: {spec_block}"""
    resp = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content.strip()