import base64
import io
import os
from collections import Counter
from dotenv import load_dotenv
from openai import OpenAI
from PIL import ImageOps, ImageFilter
import pypdfium2 as pdfium
from schema import Certificate

load_dotenv()
client = OpenAI()
MODEL = os.getenv("EXTRACTION_MODEL", "gpt-4.1")
VERIFY_MODEL = os.getenv("VERIFY_MODEL", "gpt-4o")
MAX_PAGES = 3
SCAN_CONFIDENCE_CAP = 0.85
KEY_FIELDS = ("part_number", "lot_number", "customer_po", "issue_date", "vendor_name")

SYSTEM = """You are a QA data-entry assistant for a bicycle manufacturer.
You receive page images of one supplier document and fill the given schema.
Rules:
- If it is not a certificate of analysis / conformance / test report, set document_type to not_a_certificate and null everything else.
- Copy values character by character. Keep units exactly as printed. Never convert. Never invent values.
- PASS / ACCEPT / OK with no number: value null, pass_only true.
- Two-digit years are 20xx. 9/11/26 is 2026-09-11.
- Confidence must be honest: 1.0 only for crisp printed text you are certain of. Use 0.5 to 0.8 for anything scanned, tilted, faint or where two characters could be confused (0/O, 1/I, 5/S). Put every such doubt in extraction_notes."""


def _enhance(img):
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img, cutoff=1)
    return img.filter(ImageFilter.SHARPEN)


def _page_images(file_bytes: bytes, media_type: str):
    if media_type != "application/pdf":
        return [file_bytes], True
    pdf = pdfium.PdfDocument(file_bytes)
    images, has_text = [], False
    for i in range(min(len(pdf), MAX_PAGES)):
        page = pdf[i]
        if page.get_textpage().get_text_range().strip():
            has_text = True
        buf = io.BytesIO()
        _enhance(page.render(scale=3).to_pil()).save(buf, "PNG")
        images.append(buf.getvalue())
    pdf.close()
    return images, not has_text


def _read(content, model) -> Certificate:
    resp = client.chat.completions.parse(
        model=model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
        response_format=Certificate,
    )
    return resp.choices[0].message.parsed


def _majority(values):
    top, count = Counter(values).most_common(1)[0]
    return top, count


def extract(file_bytes: bytes, media_type: str = "application/pdf") -> Certificate:
    images, is_scan = _page_images(file_bytes, media_type)
    content = [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(i).decode()}", "detail": "high"}} for i in images]
    content.append({"type": "text", "text": "Extract this document."})

    reads = [_read(content, MODEL), _read(content, VERIFY_MODEL)]
    result = reads[0]
    if result.document_type != "certificate":
        return result

    def disagree(field_get):
        return len({field_get(r) for r in reads}) > 1

    if any(disagree(lambda r, f=f: getattr(r, f)) for f in KEY_FIELDS) or \
       any(disagree(lambda r, n=t.name: next(((x.value, x.pass_only) for x in r.tests if x.name == n), None)) for t in result.tests):
        reads.append(_read(content, VERIFY_MODEL))

    for f in KEY_FIELDS:
        value, votes = _majority([getattr(r, f) for r in reads])
        setattr(result, f, value)
        if votes < len(reads):
            result.overall_confidence = min(result.overall_confidence, 0.5 if votes == 1 else 0.7)
            result.extraction_notes.append(f"{f}: reads disagree, kept '{value}' ({votes}/{len(reads)})")

    for t in result.tests:
        seen = [next(((x.value, x.pass_only) for x in r.tests if x.name == t.name), None) for r in reads]
        (value, pass_only), votes = _majority(seen) if all(s is not None for s in seen) else ((t.value, t.pass_only), 1)
        t.value, t.pass_only = value, pass_only
        if votes < len(reads):
            t.confidence = min(t.confidence, 0.5 if votes == 1 else 0.7)
            result.extraction_notes.append(f"{t.name}: reads disagree, kept {value} ({votes}/{len(reads)})")

    if is_scan:
        result.overall_confidence = min(result.overall_confidence, SCAN_CONFIDENCE_CAP)
        for t in result.tests:
            t.confidence = min(t.confidence, SCAN_CONFIDENCE_CAP)
        result.extraction_notes.append("Image-only PDF (no text layer), confidence capped")

    if result.tests:
        result.overall_confidence = min(result.overall_confidence, min(t.confidence for t in result.tests))
    return result