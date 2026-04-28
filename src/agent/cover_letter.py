"""
Cover letter helpers — wrap a body string into header/footer + render PDF.

The actual body now comes from ResumeOptimizer.optimize_with_cover() (same LLM call
that produces the optimized resume — saves a network round-trip).
This module only handles formatting and PDF rendering.
"""
import os
from typing import Optional


def wrap_letter(body: str, resume_data: dict) -> str:
    """Wrap an LLM-generated body with proper header/footer."""
    name = resume_data.get("name", "")
    email = resume_data.get("email", "")
    phone = resume_data.get("phone", "")

    body = (body or "").strip()
    return f"""Dear Hiring Team,

{body}

Best regards,
{name}
{email} | {phone}
"""


def save_text(letter: str, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(letter)
    return output_path


COVER_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"/><style>
  @page {{ size: A4; margin: 0; }}
  body {{
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 11pt;
    color: #1a1a1a;
    line-height: 1.55;
    padding: 0.7in 0.75in;
    white-space: pre-wrap;
  }}
  .header {{
    font-size: 16pt;
    font-weight: 700;
    color: #0a3d62;
    margin-bottom: 4px;
  }}
  .contact {{
    font-size: 9.5pt;
    color: #444;
    margin-bottom: 18px;
    border-bottom: 1px solid #ddd;
    padding-bottom: 8px;
  }}
  .body {{ font-size: 10.5pt; }}
</style></head><body>
<div class="header">{name}</div>
<div class="contact">{email} · {phone} · {location}</div>
<div class="body">{body}</div>
</body></html>"""


def save_pdf(letter_text: str, resume_data: dict, output_path: str) -> Optional[str]:
    """Render the cover letter to a PDF using WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        return None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    html = COVER_HTML.format(
        name=resume_data.get("name", ""),
        email=resume_data.get("email", ""),
        phone=resume_data.get("phone", ""),
        location=resume_data.get("location", ""),
        body=letter_text.replace("Dear Hiring Team,", "").replace("\n", "<br/>"),
    )
    try:
        HTML(string=html).write_pdf(output_path)
        return output_path
    except Exception as e:
        print(f"[CoverLetter] PDF render failed: {e}")
        return None
