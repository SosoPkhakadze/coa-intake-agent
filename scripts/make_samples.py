import os
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
import pypdfium2 as pdfium

OUT = os.path.join(os.path.dirname(__file__), "..", "samples")
os.makedirs(OUT, exist_ok=True)
COMPANY = "Northgate Cycles Ltd"


def clean():
    path = os.path.join(OUT, "coa_01_clean.pdf")
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 25 * mm, "TAIWAN PRECISION ALLOYS CO., LTD")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 31 * mm, "No. 88 Gongye Rd, Taichung, Taiwan  |  quality@tpa-alloys.example")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h - 45 * mm, "CERTIFICATE OF ANALYSIS")
    c.setFont("Helvetica", 10)
    y = h - 58 * mm
    for k, v in [
        ("Certificate No.", "TPA-COA-2026-04471"),
        ("Customer", COMPANY),
        ("Customer PO", "PO-8823"),
        ("Part Number", "NG-HT-7005-STEM"),
        ("Part Description", "Alloy stem, 7005-T6, 90mm"),
        ("Lot / Batch No.", "L26-0917-A"),
        ("Quantity", "1,200 pcs"),
        ("Date of Issue", "2026-09-10"),
    ]:
        c.drawString(20 * mm, y, k)
        c.drawString(75 * mm, y, v)
        y -= 6 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    for x, t in [(20, "Test"), (85, "Method"), (125, "Spec"), (160, "Result")]:
        c.drawString(x * mm, y, t)
    y -= 2 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for row in [
        ("Tensile strength", "ASTM E8", ">= 350 MPa", "372 MPa"),
        ("Yield strength", "ASTM E8", ">= 290 MPa", "311 MPa"),
        ("Hardness", "ASTM E18", "85-100 HRB", "91 HRB"),
        ("Anodize thickness", "ISO 2360", "10-25 um", "17 um"),
        ("Bore diameter", "CMM", "31.80 +/- 0.05 mm", "31.82 mm"),
    ]:
        for x, t in zip((20, 85, 125, 160), row):
            c.drawString(x * mm, y, t)
        y -= 6 * mm
    y -= 8 * mm
    c.drawString(20 * mm, y, "We certify that the above material conforms to the customer specification.")
    y -= 14 * mm
    c.drawString(20 * mm, y, "Signed: Mei-Lin Chang, QA Manager")
    c.drawString(120 * mm, y, "Date: 2026-09-10")
    c.save()
    return path


def messy():
    tmp = os.path.join(OUT, "_messy_vector.pdf")
    c = canvas.Canvas(tmp, pagesize=letter)
    w, h = letter
    c.setFont("Courier-Bold", 13)
    c.drawString(50, h - 60, "MIDWEST FORGE & FASTENER INC.")
    c.setFont("Courier", 9)
    c.drawString(50, h - 74, "Dayton, OH 45402   Ph 937-555-0119")
    c.setFont("Courier-Bold", 12)
    c.drawString(50, h - 100, "CERT OF CONFORMANCE / TEST REPORT")
    c.setFont("Courier", 10)
    y = h - 130
    for ln in [
        f"SOLD TO: {COMPANY.upper()}        P.O.# 8831",
        "PART: NG-HT-CR-M10  (chromoly axle bolt M10x1.25)",
        "HEAT/LOT: H-77410      QTY SHIPPED: 5000 EA",
        "REPORT#: MFF-9921      DATE: 9/11/26",
        "",
        "MECHANICAL PROPERTIES (per ASTM E8):",
        "   TENSILE ......... 116,000 PSI",
        "   YIELD ........... 97,500 PSI",
        "   ELONGATION ...... 12 %",
        "   HARDNESS ........ 33 HRC",
        "",
        "PLATING (ZN, ASTM B633): PASS",
        "THREAD GAUGE: GO/NO-GO  ......  ACCEPT",
        "",
        "MATERIAL CERTIFIED TO CONFORM TO CUSTOMER DWG REV C.",
        "",
        "                    QC: R. Alvarez  (signature on file)",
    ]:
        c.drawString(50, y, ln)
        y -= 15
    c.save()

    pdf = pdfium.PdfDocument(tmp)
    img = pdf[0].render(scale=110 / 72).to_pil().convert("L")
    pdf.close()
    img = img.rotate(-1.4, expand=False, fillcolor=235)
    path = os.path.join(OUT, "coa_02_messy_scan.pdf")
    img.save(path, "PDF", resolution=110)
    os.remove(tmp)
    return path


def unknown():
    path = os.path.join(OUT, "coa_03_unknown_vendor.pdf")
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 25 * mm, "SHENZHEN BRIGHTMETAL PARTS")
    c.setFont("Helvetica", 12)
    c.drawString(20 * mm, h - 40 * mm, "Quality Certificate")
    c.setFont("Helvetica", 10)
    y = h - 55 * mm
    for ln in [
        f"To: {COMPANY}",
        "Order ref: 8840",
        "Item: NG-HT-7005-STEM   Alloy stem 90mm",
        "Batch: BM-2026-118      Qty: 800",
        "Issued: 12 Sept 2026",
        "",
        "Tensile strength: 358 MPa",
        "Yield strength: 292 MPa",
        "Hardness: 88 HRB",
        "Bore diameter: 31.79 mm",
        "",
        "All items inspected and approved for shipment.",
        "",
        "Inspector: Li Wei",
    ]:
        c.drawString(20 * mm, y, ln)
        y -= 6.5 * mm
    c.save()
    return path


if __name__ == "__main__":
    for f in (clean, messy, unknown):
        print("wrote", f())