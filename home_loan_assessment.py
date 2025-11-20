# app.py
import streamlit as st
import pdfplumber
import requests
from PIL import Image
import pandas as pd
import re
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from datetime import datetime
import time
import os

st.set_page_config(page_title="HOME LOAN ANALYSIS REPORT", layout="wide")
st.title("HOME LOAN ANALYSIS REPORT")

st.markdown("Upload customer documents (PDF / image). The app extracts data, analyses, and generates a professional multi-page report.")

# -------------------------
# CONFIG
# -------------------------
# OCR.Space API key (you provided earlier)
OCR_SPACE_API_KEY = "K83910634088957"

# Local sample (your uploaded sample report) - developer message required this be present
SAMPLE_REPORT_PATH = "/mnt/data/43548c67-4c6d-4fac-9a2a-717813bf56fb.pdf"

# -------------------------
# Utilities: OCR + PDF text
# -------------------------
def ocr_space_api(file_bytes, filename):
    """Send bytes to OCR.Space and return extracted text (supports images and PDFs)."""
    url = "https://api.ocr.space/parse/image"
    files = {"file": (filename, file_bytes)}
    data = {
        "apikey": OCR_SPACE_API_KEY,
        "language": "eng",
        "isOverlayRequired": False,
        "OCREngine": 2
    }
    try:
        r = requests.post(url, files=files, data=data, timeout=120)
        r.raise_for_status()
        j = r.json()
        parsed = []
        for item in j.get("ParsedResults", []):
            parsed.append(item.get("ParsedText", ""))
        return "\n".join(parsed)
    except Exception as e:
        st.warning(f"OCR API error: {e}")
        return ""

def extract_text_from_pdf_bytes(file_bytes):
    text = ""
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for p in pdf.pages:
                page_text = p.extract_text() or ""
                text += page_text + "\n"
    except Exception:
        # fallback: send the whole PDF to OCR.Space
        text = ocr_space_api(file_bytes, f"file_{int(time.time())}.pdf")
    return text

def extract_text_from_image_bytes(file_bytes, filename):
    try:
        # try simple PIL open to ensure image is valid
        Image.open(BytesIO(file_bytes))
        return ocr_space_api(file_bytes, filename)
    except Exception:
        return ""

# -------------------------
# Document detection helpers
# -------------------------
def detect_doc_types(text):
    """Return set of possible document types found in provided text."""
    types = set()
    t = text.lower()
    if re.search(r"\bpan\b|income tax permanent account number|incometaxindiaefiling", t):
        types.add("PAN")
    if re.search(r"\baadhaar\b|\baadhar\b|\buidai\b|\bunique identification", t):
        types.add("AADHAAR")
    if re.search(r"salary|salary slip|pay slip|net pay|gross salary|basic", t):
        types.add("SALARY_SLIP")
    if re.search(r"bank statement|account summary|debit|credit|available balance", t):
        types.add("BANK_STATEMENT")
    if re.search(r"form-16|form 16|income tax|tds deducted", t):
        types.add("FORM16")
    if re.search(r"cibil|credit information|credit bureau|transunion|equifax|credit score", t):
        types.add("CIBIL")
    if re.search(r"offer letter|appointment letter|employment|employer", t):
        types.add("EMPLOYMENT")
    if re.search(r"agreement|sale deed|property|valuation|registry", t):
        types.add("PROPERTY")
    return types

# -------------------------
# Parsing routines
# -------------------------
def parse_pan(text):
    """Parse PAN fields from text."""
    res = {}
    m = re.search(r"([A-Z]{5}[0-9]{4}[A-Z])", text)
    if m:
        res['pan'] = m.group(1)
    # try to get name (simple heuristics)
    # Common PAN card lines: NAME, Father name, DOB
    name_match = re.search(r"Name\s*[:\-]?\s*([A-Z][A-Z\s\.]{3,100})", text, re.IGNORECASE)
    if name_match:
        res['name'] = name_match.group(1).strip()
    dob = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if dob:
        res['dob'] = dob.group(1)
    return res

def parse_aadhaar(text):
    res = {}
    m = re.search(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", text)
    if m:
        res['aadhaar'] = m.group(1).replace(" ", "")
    # address heuristics: lines after "Address"
    m_add = re.search(r"address[:\s\-]*(.+?)(?=\n[A-Z]{2,}|$)", text, re.IGNORECASE|re.DOTALL)
    if m_add:
        res['address'] = m_add.group(1).strip().split("\n")[0]
    return res

def parse_form16(text):
    res = {}
    # look for gross/total salary patterns
    m = re.search(r"Total\s+Salary\s*[:\-\s]*Rs\.?\s*([0-9,]+)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"Total\s+([\d,]{5,})", text)
    if m:
        res['total_salary'] = int(re.sub(r"[^\d]", "", m.group(1)))
    # taxable income
    mt = re.search(r"Income chargeable under the head.*?([\d,]{4,})", text, re.IGNORECASE|re.DOTALL)
    if mt:
        res['taxable_income'] = int(re.sub(r"[^\d]", "", mt.group(1)))
    return res

def parse_salary_slip(text):
    """Return monthly salary component dict from one slip text."""
    comps = {}
    # Find common components
    patterns = {
        'Basic': r"Basic\s*[:\-]?\s*Rs\.?\s*([0-9,]+)",
        'HRA': r"HRA\s*[:\-]?\s*Rs\.?\s*([0-9,]+)",
        'Special Allowance': r"(Special Allowance|Spl\.? Allowance)\s*[:\-]?\s*Rs\.?\s*([0-9,]+)",
        'Gross': r"Gross(?: Salary)?\s*[:\-]?\s*Rs\.?\s*([0-9,]+)",
        'Net Pay': r"Net(?: Pay| Salary)\s*[:\-]?\s*Rs\.?\s*([0-9,]+)",
        'PF': r"(Provident Fund|PF)\s*[:\-]?\s*Rs\.?\s*([0-9,]+)"
    }
    for k, p in patterns.items():
        m = re.search(p, text, re.IGNORECASE)
        if m:
            # amount may be group 1 or 2 due to alternation
            amt = m.group(len(m.groups()))
            if amt:
                comps[k] = int(re.sub(r"[^\d]", "", amt))
    # fallback: capture any Rs numbers in the bottom summary
    nums = re.findall(r"Rs\.?\s*([0-9,]{3,})", text)
    if 'Net Pay' not in comps and nums:
        comps['Net Pay'] = int(re.sub(r"[^\d]", "", nums[-1]))
    return comps

def parse_bank_statement(text):
    """Extract obligations (EMIs), salary credits, avg balance heuristics."""
    obligations = []
    salary_credits = []
    # amounts: find lines with EMI or installment
    for line in text.splitlines():
        if re.search(r"\b(EMI|EMI Debit|instalment|installment|loan)\b", line, re.IGNORECASE):
            am = re.search(r"Rs\.?\s*([0-9,]+)", line)
            obligations.append({'line': line.strip(), 'amount': int(re.sub(r"[^\d]", "", am.group(1))) if am else None})
        # salary credit heuristics
        if re.search(r"\bSalary\b|\bCredit Salary\b|\bSALARY CREDIT\b", line, re.IGNORECASE):
            am = re.search(r"Rs\.?\s*([0-9,]+)", line)
            if am:
                salary_credits.append(int(re.sub(r"[^\d]", "", am.group(1))))
    # average balance: try to find "Average balance" line
    avg_balance = None
    m = re.search(r"Average\s+Balance\s*[:\-]?\s*Rs\.?\s*([0-9,]+)", text, re.IGNORECASE)
    if m:
        avg_balance = int(re.sub(r"[^\d]", "", m.group(1)))
    return {'obligations': obligations, 'salary_credits': salary_credits, 'avg_balance': avg_balance}

def parse_cibil(text):
    res = {}
    m = re.search(r"(?:CIBIL|Credit Score)\s*[:\-]?\s*([0-9]{3})", text, re.IGNORECASE)
    if m:
        res['score'] = int(m.group(1))
    # loan history lines: find "enquiry", "loan", "outstanding"
    loans = []
    for line in text.splitlines():
        if re.search(r"\b(loan|outstanding|emI|emi)\b", line, re.IGNORECASE):
            loans.append(line.strip())
    res['loans'] = loans
    return res

# -------------------------
# Aggregation & analysis
# -------------------------
def compute_foir_and_eligibility(gross_monthly, total_existing_emi, foir_pct=60, rate_pct=8.5, tenure_years=20):
    """Compute allowed EMI and approximate loan amount (naive EMI->loan mapping)."""
    if not gross_monthly:
        return {}
    max_allowed_emi = int(gross_monthly * foir_pct / 100)
    available_for_new = max_allowed_emi - (total_existing_emi or 0)
    # approximate EMI per 1 lakh for given rate & tenure (Formula EMI = P*r*(1+r)^n / ((1+r)^n -1))
    r = rate_pct/100/12
    n = tenure_years*12
    if r <= 0:
        emi_per_lakh = available_for_new and 0 or 0
    else:
        emi_per_lakh = (100000 * r * (1+r)**n) / ((1+r)**n - 1)
    approx_loan = int(max(0, available_for_new) * 100000 / emi_per_lakh) if emi_per_lakh else 0
    return {
        'foir_pct': foir_pct,
        'max_allowed_emi': max_allowed_emi,
        'available_for_new_emi': available_for_new,
        'approx_max_loan_rs': approx_loan
    }

# -------------------------
# Report PDF builder (match sample layout)
# -------------------------
def build_report_pdf(applicant_info, eligibility, salary_3m, obligations, banking_summary, doc_status, probable_queries, final_recommendation):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(name="Title", parent=styles['Title'], fontSize=18, leading=22, alignment=1)
    section = ParagraphStyle(name="Section", parent=styles['Heading2'], fontSize=12, leading=14)
    normal = styles['Normal']

    story = []
    # Cover page
    story.append(Paragraph("HOME LOAN ANALYSIS REPORT", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Confidential Credit Assessment", normal))
    story.append(Spacer(1, 12))
    # Applicant summary table
    app_rows = [["Field", "Value"]]
    for k in ["Name","Father/Husband Name","DOB","PAN","Aadhaar","Mobile","Email","Address","Employer","Designation","DOJ"]:
        app_rows.append([k, applicant_info.get(k,"")])
    t = Table(app_rows, colWidths=[60*mm, 100*mm])
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#F0F4FF"))]))
    story.append(t)
    story.append(PageBreak())

    # Section: Employment & Income Analysis
    story.append(Paragraph("EMPLOYMENT & INCOME ANALYSIS", section))
    story.append(Spacer(1,6))
    story.append(Paragraph("Employment stability and income details extracted from provided documents.", normal))
    story.append(Spacer(1,8))

    # Section: Salary Breakdown (3 months)
    story.append(Paragraph("SALARY BREAKDOWN (Last 3 months)", section))
    sal_rows = [["Component"] + [m for m in ["Month1","Month2","Month3"]]]
    for comp in sorted({k for row in salary_3m for k in row.keys()}):
        if comp == 'Month': continue
        row = [comp]
        for m in salary_3m:
            row.append(str(m.get(comp,"")))
        sal_rows.append(row)
    stbl = Table(sal_rows, colWidths=[70*mm,40*mm,40*mm,40*mm])
    stbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#F7F7F7"))]))
    story.append(stbl)
    story.append(Spacer(1,10))

    # Section: Existing Obligations
    story.append(Paragraph("EXISTING OBLIGATIONS", section))
    ob_rows = [["Loan Type","Bank/Entity","EMI (Rs)","Tenure/Balance"]]
    for o in obligations:
        ob_rows.append([o.get('type','Loan'), o.get('bank',''), str(o.get('amount','')), o.get('tenure','')])
    obt = Table(ob_rows, colWidths=[50*mm,60*mm,40*mm,40*mm])
    obt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#F7F7F7"))]))
    story.append(obt)
    story.append(Spacer(1,10))

    # Section: FOIR & Eligibility
    story.append(Paragraph("FOIR & LOAN ELIGIBILITY", section))
    elig_rows = [["Parameter","Value"],
                 ["Gross Monthly (est.)", str(eligibility.get("gross_monthly_estimate",""))],
                 ["FOIR (%)", str(eligibility.get("foir_pct",""))],
                 ["Total Existing EMI (Rs)", str(eligibility.get("total_existing_emi",""))],
                 ["Max Allowed EMI (Rs)", str(eligibility.get("max_allowed_emi",""))],
                 ["Available for New EMI (Rs)", str(eligibility.get("available_for_new_emi",""))],
                 ["Approx. Max Loan (Rs)", str(eligibility.get("approx_max_loan_rs",""))]]
    t2 = Table(elig_rows, colWidths=[80*mm,80*mm])
    t2.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#F0F4FF"))]))
    story.append(t2)
    story.append(Spacer(1,10))

    # Banking behavior
    story.append(Paragraph("BANKING BEHAVIOUR SUMMARY", section))
    story.append(Spacer(1,6))
    if banking_summary:
        for k,v in banking_summary.items():
            story.append(Paragraph(f"<b>{k}:</b> {v}", normal))
    else:
        story.append(Paragraph("No banking summary detected.", normal))
    story.append(Spacer(1,10))

    # Documents status
    story.append(Paragraph("DOCUMENT STATUS", section))
    doc_rows = [["Document","Status"]]
    for d,s in doc_status.items():
        doc_rows.append([d,s])
    dt = Table(doc_rows, colWidths=[100*mm,60*mm])
    dt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#F7F7F7"))]))
    story.append(dt)
    story.append(Spacer(1,10))

    # Probable queries
    story.append(Paragraph("PROBABLE QUERIES", section))
    for q in probable_queries:
        story.append(Paragraph("• " + q, normal))
    story.append(Spacer(1,10))

    # Final recommendation
    story.append(Paragraph("FINAL RECOMMENDATION", section))
    story.append(Paragraph(final_recommendation or "No recommendation generated.", normal))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()

# -------------------------
# UI: Upload + processing
# -------------------------
uploaded = st.file_uploader("Upload customer documents (PDF/images). Accepts multiple.", accept_multiple_files=True, type=['pdf','jpg','jpeg','png'])
if st.button("Use sample report (developer test)"):
    # quick test load of your sample report text to demonstrate template mapping
    if os.path.exists(SAMPLE_REPORT_PATH):
        with open(SAMPLE_REPORT_PATH, "rb") as f:
            sample_bytes = f.read()
        sample_text = extract_text_from_pdf_bytes(sample_bytes)
        st.info("Loaded sample report text (developer test)")
        st.text_area("Sample report text (first 3000 chars)", sample_text[:3000], height=300)
    else:
        st.warning("Sample path not found on this machine.")

if uploaded:
    st.info("Extraction started — this may take a minute for multiple files.")
    combined_text = ""
    parsed_docs = {"PAN": None, "AADHAAR": None, "FORM16": None, "SALARY_SLIPS": [], "BANK": [], "CIBIL": None, "EMPLOYMENT": None, "PROPERTY": None}
    uploaded_names = [f.name for f in uploaded]

    for file in uploaded:
        raw = file.read()
        name = file.name
        ext = name.split(".")[-1].lower()
        # Prefer pdfplumber for text PDFs; if no text, fallback to OCR API
        if ext == 'pdf':
            txt = extract_text_from_pdf_bytes(raw)
            if not txt.strip():
                txt = ocr_space_api(raw, name)
        else:
            txt = extract_text_from_image_bytes(raw, name)
        combined_text += "\n\n" + txt

        # detect doc types from this file's text and parse accordingly
        types = detect_doc_types(txt)
        if "PAN" in types:
            parsed_docs["PAN"] = parse_pan(txt)
        if "AADHAAR" in types:
            parsed_docs["AADHAAR"] = parse_aadhaar(txt)
        if "FORM16" in types or "FORM-16" in types or "form-16" in name.lower():
            parsed_docs["FORM16"] = parse_form16(txt)
        if "SALARY_SLIP" in types or "salary" in name.lower():
            parsed_docs["SALARY_SLIPS"].append(parse_salary_slip(txt))
        if "BANK_STATEMENT" in types or "statement" in name.lower():
            parsed_docs["BANK"].append(parse_bank_statement(txt))
        if "CIBIL" in types or "cibil" in name.lower():
            parsed_docs["CIBIL"] = parse_cibil(txt)
        if "EMPLOYMENT" in types or "offer" in name.lower() or "appointment" in name.lower():
            parsed_docs["EMPLOYMENT"] = txt
        if "PROPERTY" in types or "sale deed" in txt.lower():
            parsed_docs["PROPERTY"] = txt

    st.subheader("Extraction preview")
    st.write("Files uploaded:", uploaded_names)
    st.text_area("Combined extracted text (preview)", combined_text[:30000], height=300)

    # Build applicant info from parsed docs
    applicant = {}
    # prefer PAN name
    if parsed_docs["PAN"]:
        applicant["Name"] = parsed_docs["PAN"].get("name","")
        applicant["PAN"] = parsed_docs["PAN"].get("pan","")
        applicant["DOB"] = parsed_docs["PAN"].get("dob","")
    if parsed_docs["AADHAAR"]:
        applicant["Aadhaar"] = parsed_docs["AADHAAR"].get("aadhaar","")
        if "address" in parsed_docs["AADHAAR"]:
            applicant["Address"] = parsed_docs["AADHAAR"]["address"]
    if parsed_docs["EMPLOYMENT"]:
        # try to extract employer, designation, doj heuristically
        m = re.search(r"Employer\s*[:\-]?\s*(.+)", parsed_docs["EMPLOYMENT"], re.IGNORECASE)
        if m:
            applicant["Employer"] = m.group(1).strip()
    # fill placeholders if missing
    for k in ["Name","Father/Husband Name","DOB","PAN","Aadhaar","Mobile","Email","Address","Employer","Designation","DOJ"]:
        if k not in applicant:
            applicant[k] = ""

    # Salary 3 months: use salary_slips parsed; if fewer than 3, fill blanks
    salary_3m = parsed_docs["SALARY_SLIPS"][:3]
    while len(salary_3m) < 3:
        salary_3m.append({})  # empty

    # Obligations: aggregate from bank statements
    obligations = []
    total_existing_emi = 0
    banking_summary = {}
    for b in parsed_docs["BANK"]:
        obligations += b.get('obligations', [])
        salary_credits = b.get('salary_credits', [])
        if salary_credits:
            banking_summary.setdefault("Salary credits (sample)", str(salary_credits[:3]))
        if b.get('avg_balance'):
            banking_summary["Average balance"] = str(b.get('avg_balance'))
    for o in obligations:
        if o.get('amount'):
            try:
                total_existing_emi += int(o['amount'])
            except:
                pass

    # derive gross monthly from Form16 or salary slips
    gross_monthly = None
    if parsed_docs["FORM16"] and parsed_docs["FORM16"].get("total_salary"):
        gross_monthly = int(parsed_docs["FORM16"]["total_salary"]) // 12
    elif salary_3m and salary_3m[0].get("Net Pay"):
        gross_monthly = salary_3m[0].get("Net Pay")
    else:
        # try to find large number in combined_text
        m = re.search(r"Total\s+Income\s*[:\-]?\s*Rs\.?\s*([0-9,]+)", combined_text, re.IGNORECASE)
        if m:
            gross_monthly = int(re.sub(r"[^\d]","",m.group(1)))//12

    elig_calc = compute_foir_and_eligibility(gross_monthly, total_existing_emi, foir_pct=60, rate_pct=8.5, tenure_years=20)
    eligibility = {
        "gross_monthly_estimate": gross_monthly,
        "foir_pct": elig_calc.get("foir_pct"),
        "total_existing_emi": total_existing_emi,
        "max_allowed_emi": elig_calc.get("max_allowed_emi"),
        "available_for_new_emi": elig_calc.get("available_for_new_emi"),
        "approx_max_loan_rs": elig_calc.get("approx_max_loan_rs")
    }

    # Document status: detect presence
    doc_status = {}
    doc_status["PAN"] = "Received" if parsed_docs["PAN"] else "Pending"
    doc_status["Aadhaar"] = "Received" if parsed_docs["AADHAAR"] else "Pending"
    doc_status["Form-16"] = "Received" if parsed_docs["FORM16"] else "Pending"
    doc_status["Salary Slips (3 months)"] = "Received" if any(parsed_docs["SALARY_SLIPS"]) else "Pending"
    doc_status["Bank Statement"] = "Received" if parsed_docs["BANK"] else "Pending"
    doc_status["CIBIL"] = "Received" if parsed_docs["CIBIL"] else "Pending"
    doc_status["Employment Proof"] = "Received" if parsed_docs["EMPLOYMENT"] else "Pending"
    doc_status["Property Documents"] = "Received" if parsed_docs["PROPERTY"] else "Pending"

    # Probable queries heuristics
    probable_queries = []
    if not parsed_docs["PAN"]:
        probable_queries.append("PAN copy missing — request PAN card.")
    if not parsed_docs["AADHAAR"]:
        probable_queries.append("Aadhaar missing — request Aadhaar.")
    if not parsed_docs["FORM16"] and not parsed_docs["SALARY_SLIPS"]:
        probable_queries.append("Salary proof not available — request Form-16 or 3 months salary slips.")
    if total_existing_emi > 0:
        probable_queries.append("Provide loan statements for existing EMIs detected.")
    probable_queries.append("Provide last 3 months bank statements with salary credits highlighted.")
    probable_queries.append("Provide employer letter / offer letter for verification if requested.")

    # Final recommendation (simple rule-based)
    final_recommendation = ""
    if eligibility.get('approx_max_loan_rs',0) and eligibility['approx_max_loan_rs'] > 0:
        final_recommendation = f"Applicant appears eligible for an approximate loan of Rs. {eligibility['approx_max_loan_rs']:,}. Recommend further verification of KYC and bank statements."
    else:
        final_recommendation = "Insufficient data to compute loan eligibility. Request additional documents."

    # Show parsed summary in UI
    st.subheader("Parsed Summary")
    st.write("Applicant:", applicant.get("Name","(Not found)"))
    st.write("PAN:", parsed_docs["PAN"])
    st.write("Aadhaar:", parsed_docs["AADHAAR"])
    st.write("Form-16:", parsed_docs["FORM16"])
    st.write("Salary 3 months (sample):", salary_3m)
    st.write("Obligations (sample):", obligations)
    st.write("Eligibility:", eligibility)
    st.write("Document status:", doc_status)

    # Generate PDF button
    if st.button("Generate HOME LOAN ANALYSIS REPORT"):
        pdf_bytes = build_report_pdf(applicant, eligibility, salary_3m, obligations, banking_summary, doc_status, probable_queries, final_recommendation)
        st.success("Report generated.")
        st.download_button("Download HOME LOAN ANALYSIS REPORT (PDF)", data=pdf_bytes, file_name="home_loan_analysis_report.pdf", mime="application/pdf")

else:
    st.info("Upload one or more documents to begin automated extraction and report generation.")
