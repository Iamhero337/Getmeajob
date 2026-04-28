"""
LinkedIn Easy Apply automation using Playwright.
Handles single-page and multi-step Easy Apply flows.
Fills all form fields including screening questions using LLM answers.
"""
import asyncio
import random
import os
from src.llm.client import LMStudioClient

try:
    from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

ANSWER_PROMPT = """You are filling out a job application form.
Answer this screening question for a software developer candidate.
Question: {question}
Options (if any): {options}
Candidate info: {candidate_info}

Rules:
- If it asks years of experience, answer "1" (unless the question specifies a minimum higher than 1)
- If it asks about authorization to work, answer "Yes"
- If it asks about sponsorship needed, answer "No"
- If it asks salary, use the value or say "Negotiable"
- Keep answers SHORT. If it's a text field, max 2 sentences.
- Be honest about technical skills the candidate actually listed
- For "are you comfortable with X" — answer Yes for any common tech skill

Return ONLY the answer text. Nothing else.
"""


class LinkedInApplier:
    def __init__(self, llm: LMStudioClient, config: dict):
        self.llm = llm
        self.config = config
        self.session_cookie = config.get("boards", {}).get("linkedin", {}).get("session_cookie", "")
        self.apply_cfg = config.get("apply", {})
        self.candidate = config.get("candidate", {})

    def apply(self, job: dict, resume_path: str, cover_letter: str) -> bool:
        """Synchronous entry point. Returns True if application submitted."""
        if not PLAYWRIGHT_AVAILABLE:
            print("[LinkedIn Apply] playwright not installed")
            return False
        if not self.session_cookie:
            print("[LinkedIn Apply] No session cookie — cannot apply")
            return False
        return asyncio.run(self._async_apply(job, resume_path, cover_letter))

    async def _async_apply(self, job: dict, resume_path: str, cover_letter: str) -> bool:
        url = job.get("url", "")
        if not url:
            return False

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
            )
            await context.add_cookies([{
                "name": "li_at", "value": self.session_cookie,
                "domain": ".linkedin.com", "path": "/",
                "httpOnly": True, "secure": True,
            }])
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )

            page = await context.new_page()
            success = False

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(2, 3))

                # Look for Easy Apply button
                easy_btn = await page.query_selector(
                    "button.jobs-apply-button, button[aria-label*='Easy Apply']"
                )
                if not easy_btn:
                    print(f"[LinkedIn Apply] No Easy Apply button for: {job.get('title')}")
                    await browser.close()
                    return False

                await easy_btn.click()
                await asyncio.sleep(random.uniform(1.5, 2.5))

                # Handle multi-step application modal
                success = await self._handle_modal(page, resume_path, cover_letter, job)

            except Exception as e:
                print(f"[LinkedIn Apply] Error: {e}")
            finally:
                await browser.close()

        return success

    async def _handle_modal(
        self, page: Page, resume_path: str, cover_letter: str, job: dict
    ) -> bool:
        max_steps = 10
        for step in range(max_steps):
            await asyncio.sleep(random.uniform(1, 2))

            # Upload resume if file input appears
            file_input = await page.query_selector("input[type='file']")
            if file_input and os.path.exists(resume_path):
                await file_input.set_input_files(resume_path)
                await asyncio.sleep(1)

            # Fill text areas (cover letter / additional info)
            textareas = await page.query_selector_all("textarea")
            for ta in textareas:
                placeholder = (await ta.get_attribute("placeholder") or "").lower()
                label = await self._get_label(page, ta)
                if any(x in label.lower() for x in ["cover", "letter", "message", "additional"]):
                    await ta.fill(cover_letter[:2000])
                    await asyncio.sleep(0.5)

            # Fill text inputs
            inputs = await page.query_selector_all("input[type='text'], input[type='number'], input[type='tel']")
            for inp in inputs:
                label = await self._get_label(page, inp)
                value = self._get_default_answer(label)
                if value:
                    current = await inp.input_value()
                    if not current:
                        await inp.fill(value)
                        await asyncio.sleep(0.3)

            # Handle radio buttons and checkboxes via LLM
            await self._handle_radio_select(page, job)

            # Handle dropdowns
            await self._handle_dropdowns(page)

            # Check for Submit button
            submit_btn = await page.query_selector(
                "button[aria-label='Submit application'], button:has-text('Submit application')"
            )
            if submit_btn:
                await asyncio.sleep(random.uniform(1, 2))
                await submit_btn.click()
                await asyncio.sleep(2)
                print(f"[LinkedIn Apply] ✓ Applied to {job.get('title')} at {job.get('company')}")
                return True

            # Next/Continue button
            next_btn = await page.query_selector(
                "button[aria-label='Continue to next step'], "
                "button:has-text('Next'), button:has-text('Continue'), "
                "button:has-text('Review')"
            )
            if next_btn:
                await next_btn.click()
                await asyncio.sleep(random.uniform(1, 2))
                continue

            # Dismiss / Done
            done_btn = await page.query_selector("button:has-text('Done')")
            if done_btn:
                await done_btn.click()
                return True

            break  # No more buttons found

        return False

    async def _get_label(self, page: Page, element) -> str:
        try:
            elem_id = await element.get_attribute("id")
            if elem_id:
                label_el = await page.query_selector(f"label[for='{elem_id}']")
                if label_el:
                    return await label_el.inner_text()
            aria = await element.get_attribute("aria-label") or ""
            return aria
        except Exception:
            return ""

    def _get_default_answer(self, label: str) -> str:
        label_l = label.lower()
        defaults = self.apply_cfg.get("default_answers", {})
        if any(x in label_l for x in ["years of exp", "years exp", "experience"]):
            return defaults.get("years_experience", "1")
        if any(x in label_l for x in ["salary", "ctc", "compensation", "package"]):
            return defaults.get("salary_expectation", "") or self._salary_str()
        if any(x in label_l for x in ["notice", "start date", "joining"]):
            return defaults.get("available_start", "1 month")
        if any(x in label_l for x in ["phone", "mobile", "contact"]):
            return self.candidate.get("phone", "")
        if any(x in label_l for x in ["city", "location"]):
            return self.candidate.get("location", "")
        return ""

    def _salary_str(self) -> str:
        cfg = self.config.get("candidate", {})
        mn = cfg.get("expected_salary_min", 0)
        if mn:
            return str(mn)
        return ""

    async def _handle_radio_select(self, page: Page, job: dict):
        try:
            fieldsets = await page.query_selector_all("fieldset")
            for fs in fieldsets:
                legend = await fs.query_selector("legend")
                question = await legend.inner_text() if legend else ""
                if not question:
                    continue

                radios = await fs.query_selector_all("input[type='radio']")
                if not radios:
                    continue

                options = []
                for r in radios:
                    label_id = await r.get_attribute("id")
                    lbl = await page.query_selector(f"label[for='{label_id}']")
                    lbl_text = await lbl.inner_text() if lbl else ""
                    options.append((r, lbl_text))

                # Use LLM to pick best answer
                answer = self._fast_answer(
                    question,
                    [o[1] for o in options],
                )
                for radio, label_text in options:
                    if answer.lower() in label_text.lower():
                        await radio.click()
                        break
                else:
                    # Default: pick first option
                    await options[0][0].click()

        except Exception:
            pass

    async def _handle_dropdowns(self, page: Page):
        try:
            selects = await page.query_selector_all("select")
            for sel in selects:
                label = await self._get_label(page, sel)
                options = await sel.query_selector_all("option")
                values = [await o.get_attribute("value") for o in options if await o.get_attribute("value")]
                if not values:
                    continue

                answer = self._fast_answer(label, [await o.inner_text() for o in options])
                for opt in options:
                    txt = await opt.inner_text()
                    if answer.lower() in txt.lower():
                        val = await opt.get_attribute("value")
                        await sel.select_option(value=val)
                        break
                else:
                    # Pick second option (first is often blank/placeholder)
                    if len(values) > 1:
                        await sel.select_option(value=values[1])
        except Exception:
            pass

    def _fast_answer(self, question: str, options: list[str]) -> str:
        """
        Two-stage answer: heuristic first (fast), LLM fallback for complex questions.
        """
        if not options:
            return ""

        q_lower = question.lower()
        yes_triggers = ["authorized", "eligible to work", "comfortable", "willing to",
                        "have experience", "do you know", "familiar", "proficient",
                        "are you able"]
        no_triggers = ["require sponsorship", "need visa", "need sponsorship",
                       "require visa"]

        # Heuristic Yes
        if any(t in q_lower for t in yes_triggers):
            for opt in options:
                if opt.lower().strip() in ("yes",):
                    return opt

        # Heuristic No
        if any(t in q_lower for t in no_triggers):
            for opt in options:
                if opt.lower().strip() in ("no",):
                    return opt

        # Years of experience question
        if "year" in q_lower and "experience" in q_lower:
            # Prefer 1-2 yr or "less than 2"
            for opt in options:
                ol = opt.lower()
                if "1" in ol or "2" in ol or "less than" in ol:
                    return opt

        # Salary question
        if any(w in q_lower for w in ["salary", "ctc", "compensation", "expected"]):
            return options[0]  # Pick first/lowest tier

        # Complex question — defer to LLM
        try:
            resp = self.llm.chat([
                {"role": "system",
                 "content": "You answer job application screening questions for a software engineer with 2 years of experience. Respond with ONLY the exact text of the most appropriate option from the list — nothing else."},
                {"role": "user",
                 "content": f"Question: {question}\n\nOptions:\n" + "\n".join(f"- {o}" for o in options) + "\n\nReturn the option text only."},
            ], temperature=0.0, max_tokens=50)
            resp_clean = resp.strip().strip('"').strip("'").lower()
            for opt in options:
                if opt.lower().strip() == resp_clean or resp_clean in opt.lower():
                    return opt
        except Exception:
            pass

        # Final fallback: prefer Yes-style options, else first non-empty
        for opt in options:
            if opt.lower().strip() in ("yes", "available", "agree"):
                return opt
        return options[0]
