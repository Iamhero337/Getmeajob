"""
Resume parser — extracts structured data from PDF or DOCX resume.
Outputs a ResumeData dict that the optimizer and builder consume.
"""
import os
import re
from typing import Optional


def parse_resume(path: str) -> dict:
    """Parse PDF or DOCX resume into structured dict."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = _extract_pdf(path)
    elif ext in (".docx", ".doc"):
        text = _extract_docx(path)
    else:
        raise ValueError(f"Unsupported resume format: {ext}. Use PDF or DOCX.")

    return _structure(text)


def _extract_pdf(path: str) -> str:
    import pdfplumber
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text


def _extract_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_email(text: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text, re.IGNORECASE)
    return m.group(0) if m else ""


def _extract_phone(text: str) -> str:
    m = re.search(r"[\+\d][\d\s\-\(\)]{8,14}\d", text)
    return m.group(0).strip() if m else ""


def _extract_linkedin(text: str) -> str:
    m = re.search(r"linkedin\.com/in/[\w-]+", text, re.IGNORECASE)
    return f"https://{m.group(0)}" if m else ""


def _extract_github(text: str) -> str:
    m = re.search(r"github\.com/[\w-]+", text, re.IGNORECASE)
    return f"https://{m.group(0)}" if m else ""


def _extract_name(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:5]:
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            if not any(c in line for c in ["@", "+", "http", "/"]):
                return line
    return lines[0] if lines else ""


def _structure(text: str) -> dict:
    """Return a structured resume dict from raw text."""
    return {
        "name": _extract_name(text),
        "email": _extract_email(text),
        "phone": _extract_phone(text),
        "linkedin": _extract_linkedin(text),
        "github": _extract_github(text),
        "raw_text": text,
        # These will be filled by the LLM optimizer
        "summary": "",
        "skills": [],
        "experience": [],
        "education": [],
        "projects": [],
        "certifications": [],
    }
