"""
Generic apply — for jobs where you click "Apply" and land on an external form.
Opens the URL in a visible browser so you can complete it manually,
but pre-fills whatever it can detect.

Also handles email-based applications: generates a ready-to-send email.
"""
import asyncio
import subprocess
import os


class GenericApplier:
    def __init__(self, config: dict):
        self.config = config
        self.candidate = config.get("candidate", {})

    def open_browser(self, url: str):
        """Open the application URL in the default browser."""
        subprocess.Popen(["xdg-open", url])

    def generate_email_application(
        self, resume_data: dict, job: dict, cover_letter: str
    ) -> dict:
        """
        Generate a ready-to-use email application.
        Returns dict with subject, body, and attachment path.
        """
        name = resume_data.get("name", "")
        title = job.get("title", "")
        company = job.get("company", "")

        subject = f"Application for {title} Position — {name}"
        body = f"""Hi,

{cover_letter}

Please find my resume attached.

Best regards,
{name}
{resume_data.get('email', '')}
{resume_data.get('phone', '')}
"""
        return {
            "to": "",  # User needs to fill this
            "subject": subject,
            "body": body,
            "resume_path": job.get("resume_path", ""),
        }

    def print_application_email(self, email_data: dict):
        """Print the email to terminal for easy copy-paste."""
        print("\n" + "="*60)
        print(f"Subject: {email_data['subject']}")
        print("="*60)
        print(email_data["body"])
        print("="*60 + "\n")
