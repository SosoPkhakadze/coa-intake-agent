from typing import Literal, Optional
from pydantic import BaseModel, Field


class TestResult(BaseModel):
    name: str = Field(description="snake_case: tensile_strength, yield_strength, elongation, hardness, anodize_thickness, plating_thickness, bore_diameter, thread_gauge")
    value: Optional[float] = Field(description="Numeric result exactly as printed. null if only PASS/OK/ACCEPT was written")
    unit: Optional[str] = Field(description="Unit as printed: MPa, psi, HRB, HRC, um, mm, %. null if none")
    raw_text: str = Field(description="Exact text on the document this came from")
    pass_only: bool = Field(description="true if PASS/ACCEPT/OK with no number")
    confidence: float = Field(description="0 to 1, lower for blurry, handwritten or ambiguous text")


class Certificate(BaseModel):
    document_type: Literal["certificate", "not_a_certificate"]
    vendor_name: Optional[str]
    certificate_number: Optional[str]
    customer_name: Optional[str]
    customer_po: Optional[str]
    part_number: Optional[str]
    part_description: Optional[str]
    lot_number: Optional[str]
    quantity: Optional[int]
    issue_date: Optional[str] = Field(description="ISO YYYY-MM-DD. US vendors write m/d/yy")
    signed_by: Optional[str]
    tests: list[TestResult]
    overall_confidence: float
    extraction_notes: list[str] = Field(description="Anything unreadable, assumed or ambiguous")