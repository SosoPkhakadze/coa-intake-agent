# Incoming Quality Policy QP-07 (Certificate acceptance)

1. A certificate may only be auto-released if the vendor is on the Approved Vendor List AND the part number is on that vendor's approved parts list.
2. Every test in the part specification must appear on the certificate. Tests marked REQUIRED must have a numeric result; PASS, OK or Conforms without a number is not sufficient.
3. A result is BORDERLINE and must be reviewed by a QA engineer if it is within 10 percent of the tolerance band from either limit, or within 2 percent of a one-sided limit.
4. Any result outside the specification limits places the lot on HOLD. Notify the buyer and the vendor.
5. Certificates must reference a customer PO number. A missing PO is a review item, not a rejection.
6. Certificates older than 90 days at the time of receipt must be re-issued by the vendor.
7. Any attachment that is not a certificate of analysis or conformance (catalogues, invoices, drawings) must be rejected with a reply asking for the correct document.
8. When extraction confidence for any value is below 0.7 the lot goes to human review regardless of the values.