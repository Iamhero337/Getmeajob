"""
Resume builder — renders optimized resume data to PDF using WeasyPrint.
Produces clean, ATS-readable single-page PDF resumes.
"""
import os
import re
import hashlib
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration


TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "templates"
)


def _slug(text: str) -> str:
    return re.sub(r"[^\w-]", "_", text.lower())[:40]


def build_pdf(resume_data: dict, output_path: str, template: str = "resume_modern") -> str:
    """
    Render resume_data dict into a PDF file at output_path.
    Returns the output path on success.
    """
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    tmpl = env.get_template(f"{template}.html")

    # Build context — flatten for easier template use
    ctx = {
        "name": resume_data.get("name", ""),
        "tagline": resume_data.get("tagline", ""),
        "email": resume_data.get("email", ""),
        "phone": resume_data.get("phone", ""),
        "location": resume_data.get("location", ""),
        "linkedin": resume_data.get("linkedin", ""),
        "github": resume_data.get("github", ""),
        "summary": resume_data.get("summary", ""),
        "skills": resume_data.get("skills", []),
        "experience": resume_data.get("experience", []),
        "projects": resume_data.get("projects", []),
        "education": resume_data.get("education", []),
        "certifications": resume_data.get("certifications", []),
    }

    html_content = tmpl.render(**ctx)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    font_config = FontConfiguration()
    HTML(string=html_content, base_url=TEMPLATE_DIR).write_pdf(
        output_path,
        font_config=font_config,
    )
    return output_path


def resume_filename(resume_data: dict, job: dict) -> str:
    """Generate a unique filename for this resume variant."""
    name = _slug(resume_data.get("name", "candidate"))
    company = _slug(job.get("company", "company"))
    title = _slug(job.get("title", "role"))
    return f"{name}_{company}_{title}.pdf"
