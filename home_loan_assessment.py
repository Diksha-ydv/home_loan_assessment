import streamlit as st
import pdfplumber
import pytesseract
from PIL import Image
import pandas as pd
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

st.set_page_config(page_title="Home Loan Assessment", layout="wide")

st.title("Home Loan Assessment — Offline (OCR + Heuristics)")

st.write("""
Upload customer documents (PDFs / images).  
This offline app uses **pdfplumber** for text PDFs and **Tesseract OCR** for images/scanned PDFs.
""")

st.write("### Upload PDF or image files (accepts multiple)")
uploaded_files = st.file_uploader(
    "Drag and drop files here",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True
)

def extract_text_from_pdf(file_bytes):
    text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def extract_text_from_image(file_bytes):
    img = Image.open(io.BytesIO(file_bytes))
    return pytesseract.image_to_string(img)

def generate_report(eligibility, salary_table, obligations, pending_docs, pending_forms, queries):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setFont("Helvetica", 11)

    y = 750
    pdf.drawString(30, y, "Home Loan Assessment Report")
    y -= 20
    pdf.drawString(30, y, f"Eligibility: {eligibility}")
    y -= 30

    pdf.drawString(30, y, "Salary Breakdown:")
    y -= 15
    for row in salary_table:
        pdf.drawString(40, y, str(row))
        y -= 15

    y -= 10
    pdf.drawString(30, y, "Obligations:")
    y -= 15
    for row in obligations:
        pdf.drawString(40, y, str(row))
        y -= 15

    y -= 10
    pdf.drawString(30, y, "Pending Documents:")
    y -= 15
    for item in pending_docs:
        pdf.drawString(40, y, f"- {item}")
        y -= 15

    y -= 10
    pdf.drawString(30, y, "Pending Form Details:")
    y -= 15
    for item in pending_forms:
        pdf.drawString(40, y, f"- {item}")
        y -= 15

    y -= 10
    pdf.drawString(30, y, "Probable Queries:")
    y -= 15
    for item in queries:
        pdf.drawString(40, y, f"- {item}")
        y -= 15

    pdf.save()
    buffer.seek(0)
    return buffer

if uploaded_files:
    all_text = ""

    for f in uploaded_files:
        ext = f.name.split(".")[-1].lower()
        file_bytes = f.read()

        if ext == "pdf":
            try:
                all_text += extract_text_from_pdf(file_bytes)
            except:
                img = Image.open(io.BytesIO(file_bytes))
                all_text += pytesseract.image_to_string(img)

        else:
            all_text += extract_text_from_image(file_bytes)

    st.subheader("Extracted Text Preview")
    st.text_area("OCR + PDF Extracted Text", all_text, height=250)

    # DEMO dummy logic (replace with your own business rules)
    eligibility = "Eligible (Dummy Logic)"
    salary_table = [
        {"Month": "Jan", "Salary": "50,000"},
        {"Month": "Feb", "Salary": "50,000"}
    ]
    obligations = [
        {"Obligation": "Credit Card EMI", "Amount": "2,000"}
    ]
    pending_docs = ["Bank Statement", "Form-16 Part B"]
    pending_forms = ["KYC Form", "Application Form"]
    queries = ["Mismatch in PAN", "Verify Employment"]

    st.write("### Generate Final PDF Report")
    if st.button("Generate PDF Report"):
        pdf_buffer = generate_report(
            eligibility,
            salary_table,
            obligations,
            pending_docs,
            pending_forms,
            queries
        )

        st.download_button(
            label="Download PDF Report",
            data=pdf_buffer,
            file_name="home_loan_assessment_report.pdf",
            mime="application/pdf"
        )

else:
    st.info("Upload one or more documents to start.")
