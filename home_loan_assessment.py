import streamlit as st
import pdfplumber
import requests
from PIL import Image
import pandas as pd
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from datetime import datetime
import time

st.set_page_config(page_title="Home Loan Assessment (Cloud OCR)", layout="wide")
st.title("🏠 Home Loan Assessment — Cloud OCR (OCR.Space)")

st.markdown("""
Upload customer documents (PDFs / images).  
This app uses **pdfplumber** for text PDFs and **OCR.Space API** for OCR so it works online with Streamlit Cloud.
""")

# -----------------------------
# YOUR OCR API KEY HERE
# -----------------------------
OCR_SPACE_API_KEY = "K83910634088957"
# -----------------------------

uploaded_files = st.file_uploader(
    "Upload PDF or image files (accepts multiple)",
    accept_multiple_files=True,
    type=["pdf", "png", "jpg", "jpeg"]
)

# SAMPLE TEST FILES (LOCAL ONLY)
SAMPLE_PDF = "/mnt/data/b8b3f3dc-60ff-4111-8e6e-26f7701b817c.pdf"
SAMPLE_IMG = "/mnt/data/59c74388-414b-4f67-aaa3-cd7eb91476cc.jpeg"

use_local_samples = st.checkbox("Use sample files for quick test (local only)")

# -----------------------------
# OCR SPACE API FUNCTION
# -----------------------------
def ocr_space_api(file_bytes, filename):
    url = "https://api.ocr.space/parse/image"
    files = {"file": (filename, file_bytes)}
    data = {
        "apikey": OCR_SPACE_API_KEY,
        "language": "eng",
        "isOverlayRequired": False,
        "OCREngine": 2
    }
    try:
        r = requests.post(url, files=files, data=data, timeout=60)
        r.raise_for_status()
        response = r.json()
        parsed_text = ""
        for result in response.get("ParsedResults", []):
            parsed_text += result.get("ParsedText", "")
        return parsed_text
    except Exception as e:
        st.warning(f"OCR API Error: {e}")
        return ""

# -----------------------------
# PDF TEXT EXTRACTOR
# -----------------------------
def extract_pdf_text(file_bytes):
    text = ""
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
    except:
        text = ocr_space_api(file_bytes, f"pdf_{int(time.time())}.pdf")
    return text

# -----------------------------
# IMAGE EXTRACTOR
# -----------------------------
def extract_image_text(file_bytes, filename):
    return ocr_space_api(file_bytes, filename)

# -----------------------------
# PARSING & BUSINESS LOGIC
# -----------------------------
def parse_summary(all_text):
    import re
    pan = None
    m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", all_text)
    if m:
        pan = m.group(1)

    salary = {"Basic": "50,000", "HRA": "20,000"}  # sample placeholders
    obligations = [{"desc": "Credit Card EMI", "amount": "2000"}]

    eligibility = {
        "gross_monthly_estimate": "70,000",
        "foir_pct": 50,
        "total_existing_emi": 2000,
        "max_allowed_emi": 35000,
        "available_for_new_emi": 33000,
        "approx_max_loan_rs": "25,00,000"
    }

    pending_docs = ["Bank Statement", "Form-16 Part B"]
    queries = ["PAN mismatch", "Employment verification required"]

    return eligibility, salary, obligations, pending_docs, queries, pan

# -----------------------------
# PDF REPORT GENERATOR
# -----------------------------
def generate_pdf(applicant, eligibility, salary, obligations, pending_docs, queries):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm)
    styles = getSampleStyleSheet()
    story = []

    title = Paragraph("Home Loan Assessment Report", styles["Title"])
    story.append(title)
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"Applicant: {applicant or '-'}", styles["Normal"]))
    story.append(Paragraph(f"Date: {datetime.now().strftime('%d-%m-%Y')}", styles["Normal"]))
    story.append(Spacer(1, 15))

    story.append(Paragraph("1. Eligibility", styles["Heading2"]))
    elig_table = [
        ["Metric", "Value"],
        ["Gross Monthly", eligibility["gross_monthly_estimate"]],
        ["FOIR (%)", eligibility["foir_pct"]],
        ["Existing EMI", eligibility["total_existing_emi"]],
        ["Max Allowed EMI", eligibility["max_allowed_emi"]],
        ["Available for New EMI", eligibility["available_for_new_emi"]],
        ["Approx Max Loan", eligibility["approx_max_loan_rs"]],
    ]
    table = Table(elig_table)
    table.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.grey)]))
    story.append(table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("2. Salary", styles["Heading2"]))
    sal_table = [["Component", "Amount"]] + [[k, v] for k, v in salary.items()]
    table2 = Table(sal_table)
    table2.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.grey)]))
    story.append(table2)
    story.append(Spacer(1, 12))

    story.append(Paragraph("3. Obligations", styles["Heading2"]))
    obl_table = [["Description", "Amount"]] + [[o["desc"], o["amount"]] for o in obligations]
    table3 = Table(obl_table)
    table3.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.5, colors.grey)]))
    story.append(table3)
    story.append(Spacer(1, 12))

    story.append(Paragraph("4. Pending Documents", styles["Heading2"]))
    for d in pending_docs:
        story.append(Paragraph(f"- {d}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("5. Probable Queries", styles["Heading2"]))
    for q in queries:
        story.append(Paragraph(f"- {q}", styles["Normal"]))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()

# -----------------------------
# MAIN LOGIC
# -----------------------------
if uploaded_files or use_local_samples:
    st.subheader("Extracting text...")

    all_text = ""

    # SAMPLE TEST LOGIC
    if use_local_samples:
        with open(SAMPLE_PDF, "rb") as f:
            all_text += extract_pdf_text(f.read())
        with open(SAMPLE_IMG, "rb") as f:
            all_text += extract_image_text(f.read(), "sample.jpg")

    # USER-UPLOADED FILES
    for file in uploaded_files:
        raw = file.read()
        ext = file.name.split(".")[-1].lower()
        if ext == "pdf":
            all_text += extract_pdf_text(raw)
        else:
            all_text += extract_image_text(raw, file.name)

    # Show extracted text preview
    st.subheader("Extracted Text")
    st.text_area("Preview", all_text[:20000], height=300)

    eligibility, salary, obligations, pending_docs, queries, pan = parse_summary(all_text)

    st.subheader("Summary")
    st.write("Detected PAN:", pan)
    st.write("Salary:", salary)

    if st.button("Generate PDF Report"):
        pdf_bytes = generate_pdf(pan, eligibility, salary, obligations, pending_docs, queries)
        st.success("PDF report generated.")
        st.download_button(
            "Download Report",
            pdf_bytes,
            file_name="home_loan_assessment_report.pdf",
            mime="application/pdf"
        )

else:
    st.info("Please upload files to start.")
