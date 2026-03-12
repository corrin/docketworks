"""
SafetyAIService - AI prompting for JSA/SWP generation.

Handles all AI interactions for generating safety document content including:
- Full JSA/SWP generation from job/procedure context
- Structured output with tasks, hazards, controls, and PPE

Uses the shared LLMService for provider-agnostic LLM access.
"""

import logging
from typing import Any

from apps.job.models import Job
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.llm_service import LLMService

logger = logging.getLogger(__name__)


# Default PPE for metal fabrication work
DEFAULT_PPE = [
    "Hard hat",
    "Safety glasses",
    "Steel cap boots",
    "High visibility vest",
    "Gloves (appropriate for task)",
    "Hearing protection (as required)",
]


class SafetyAIService:
    """
    Service for AI-powered safety document content generation.

    Uses the shared LLMService for provider-agnostic access to Claude, Gemini, etc.
    Generates JSA/SWP content following NZ WorkSafe guidelines.
    """

    def __init__(self):
        """Initialize the AI service."""
        self.llm = LLMService()
        logger.info(f"SafetyAIService configured with model: {self.llm.model_name}")

    def _get_system_prompt(self) -> str:
        """Get the system prompt for safety document generation."""
        company = CompanyDefaults.get_solo()
        company_name = company.company_name

        return f"""You are a workplace safety expert specializing in New Zealand safety regulations,
WorkSafe NZ guidelines, and Job Safety Analysis (JSA) creation for metal fabrication and installation work.

You work for {company_name}, a custom metal fabrication business.

Your role is to create comprehensive safety documents that:
- Follow NZ Health and Safety at Work Act 2015 requirements
- Apply the hierarchy of controls (Elimination > Substitution > Engineering > Administrative > PPE)
- Focus on practical, implementable control measures
- Consider the metal fabrication and installation context

The primary use cases are:
- On-site installation work (installing fabricated metal items at customer premises)
- Working at heights, with heavy equipment, near traffic
- Hot work (welding, grinding) in variable environments
- Manual handling of heavy fabricated items

Risk ratings:
- Low: Minor injury unlikely, proceed with standard precautions
- Moderate: Injury possible, additional controls recommended
- High: Serious injury likely without controls, must implement controls
- Extreme: Life-threatening, do not proceed without comprehensive controls and approval

Always respond with valid JSON as specified in the prompt."""

    def _call_llm(self, prompt: str, expect_json: bool = True) -> dict | str:
        """
        Make a call to the LLM via the shared LLMService.

        Args:
            prompt: The user prompt to send
            expect_json: If True, parse response as JSON

        Returns:
            Parsed JSON dict or raw string response
        """
        messages = [{"role": "user", "content": prompt}]

        if expect_json:
            return self.llm.completion_with_json(
                messages=messages,
                system_prompt=self._get_system_prompt(),
            )
        else:
            return self.llm.get_text_response(
                messages=messages,
                system_prompt=self._get_system_prompt(),
            )

    def generate_full_jsa(self, job: Job) -> dict[str, Any]:
        """
        Generate a complete JSA for a job using AI.

        Args:
            job: The job to generate a JSA for

        Returns:
            Dict with JSA structure: title, description, ppe_requirements, tasks, etc.
        """
        prompt = f"""Generate a Job Safety Analysis (JSA) for the following job:

Job Name: {job.name}
Job Number: {job.job_number}
Client: {job.client.name if job.client else 'Unknown'}
Description: {job.description or 'No description provided'}

Generate a comprehensive JSA with:
1. A clear title (job name)
2. Site location (use client address if known, otherwise "To be confirmed on site")
3. A detailed job description for safety purposes
4. 4-6 sequential tasks covering the work from setup to completion
5. For each task: 2-4 potential hazards and appropriate control measures
6. PPE requirements specific to this work
7. Any additional safety notes

For control measures, always link them to the specific hazard they address.
Apply the hierarchy of controls (Elimination > Substitution > Engineering > Administrative > PPE).

Respond with JSON in this exact format:
{{
    "title": "JSA title",
    "site_location": "Work site location",
    "description": "Detailed job description for safety purposes",
    "ppe_requirements": ["PPE item 1", "PPE item 2", ...],
    "tasks": [
        {{
            "step_number": 1,
            "description": "Detailed task description",
            "summary": "1-3 word summary",
            "potential_hazards": ["Hazard 1", "Hazard 2"],
            "initial_risk_rating": "Low|Moderate|High|Extreme",
            "control_measures": [
                {{"measure": "Control measure text", "associated_hazard": "Hazard it addresses"}}
            ],
            "revised_risk_rating": "Low|Moderate|High|Extreme"
        }}
    ],
    "additional_notes": "Any additional safety notes or site-specific requirements"
}}"""

        result = self._call_llm(prompt, expect_json=True)

        # Ensure all required fields exist with defaults
        result.setdefault("title", job.name)
        result.setdefault("site_location", "To be confirmed on site")
        result.setdefault("description", job.description or "")
        result.setdefault("ppe_requirements", DEFAULT_PPE.copy())
        result.setdefault("tasks", [])
        result.setdefault("additional_notes", "")

        return result

    def generate_full_swp(
        self,
        title: str,
        description: str,
        site_location: str = "",
    ) -> dict[str, Any]:
        """
        Generate a complete SWP (Safe Work Procedure) using AI.

        Args:
            title: Name of the procedure
            description: Scope and description of the procedure
            site_location: Optional site location

        Returns:
            Dict with SWP structure
        """
        prompt = f"""Generate a Safe Work Procedure (SWP) for:

Procedure Name: {title}
Description/Scope: {description}
Location: {site_location or 'General workshop/site'}

Generate a comprehensive SWP with:
1. A clear title
2. Site/work location
3. A detailed procedure description
4. 4-8 sequential steps covering the procedure
5. For each step: 2-4 potential hazards and appropriate control measures
6. PPE requirements
7. Additional safety notes

This is a generic procedure (not job-specific), so focus on standard practices that can be applied consistently.

Respond with JSON in this exact format:
{{
    "title": "SWP title",
    "site_location": "Work location",
    "description": "Detailed procedure description",
    "ppe_requirements": ["PPE item 1", "PPE item 2", ...],
    "tasks": [
        {{
            "step_number": 1,
            "description": "Detailed step description",
            "summary": "1-3 word summary",
            "potential_hazards": ["Hazard 1", "Hazard 2"],
            "initial_risk_rating": "Low|Moderate|High|Extreme",
            "control_measures": [
                {{"measure": "Control measure text", "associated_hazard": "Hazard it addresses"}}
            ],
            "revised_risk_rating": "Low|Moderate|High|Extreme"
        }}
    ],
    "additional_notes": "Additional safety notes"
}}"""

        result = self._call_llm(prompt, expect_json=True)

        # Ensure all required fields exist with defaults
        result.setdefault("title", title)
        result.setdefault("site_location", site_location or "General")
        result.setdefault("description", description)
        result.setdefault("ppe_requirements", DEFAULT_PPE.copy())
        result.setdefault("tasks", [])
        result.setdefault("additional_notes", "")

        return result

    def generate_full_sop(
        self,
        title: str,
        description: str,
        document_number: str = "",
    ) -> dict[str, Any]:
        """
        Generate a complete SOP (Standard Operating Procedure) using AI.

        SOPs are general procedures (not safety-specific), like "How to enter an invoice".

        Args:
            title: Name of the procedure
            description: Scope and description of the procedure
            document_number: Optional document number (e.g., '307')

        Returns:
            Dict with SOP structure
        """
        prompt = f"""Generate a Standard Operating Procedure (SOP) for:

Procedure Name: {title}
{f"Document Number: {document_number}" if document_number else ""}
Description/Scope: {description}

Generate a comprehensive SOP with:
1. A clear title
2. Purpose/objective of the procedure
3. Scope (who this applies to)
4. 4-10 sequential steps covering the procedure
5. Any notes or tips for each step where helpful

This is a standard business procedure (not safety-specific), so focus on:
- Clear, actionable steps
- Who is responsible for each action
- Any systems or tools required
- Expected outcomes

Respond with JSON in this exact format:
{{
    "title": "SOP title",
    "description": "Purpose and scope of the procedure",
    "tasks": [
        {{
            "step_number": 1,
            "description": "Detailed step description",
            "summary": "1-3 word summary",
            "notes": "Optional tips or additional info"
        }}
    ],
    "additional_notes": "Any additional notes about this procedure"
}}"""

        result = self._call_llm(prompt, expect_json=True)

        # Ensure all required fields exist with defaults
        result.setdefault("title", title)
        result.setdefault("description", description)
        result.setdefault("tasks", [])
        result.setdefault("additional_notes", "")
        # SOPs don't have safety-specific fields
        result.setdefault("ppe_requirements", [])
        result.setdefault("site_location", "")

        return result

    def generate_hazards(self, task_description: str) -> list[str]:
        """
        Generate potential hazards for a specific task.

        Args:
            task_description: Description of the task

        Returns:
            List of potential hazards
        """
        prompt = f"""Identify 3-5 potential hazards for this task in a metal fabrication context:

Task: {task_description}

Consider hazards related to:
- Physical hazards (manual handling, noise, vibration, confined spaces)
- Machinery/equipment hazards
- Electrical hazards
- Chemical hazards (fumes, dusts, solvents)
- Environmental hazards (weather, heat, heights)
- Ergonomic hazards

Respond with JSON:
{{
    "hazards": ["Hazard 1", "Hazard 2", "Hazard 3"]
}}"""

        result = self._call_llm(prompt, expect_json=True)
        return result.get("hazards", [])

    def generate_controls(
        self, hazards: list[str], task_description: str = ""
    ) -> list[dict[str, str]]:
        """
        Generate control measures for specified hazards.

        Args:
            hazards: List of hazards to address
            task_description: Optional task context

        Returns:
            List of control measures with associated hazards
        """
        hazards_text = "\n".join(f"- {h}" for h in hazards)
        context = f"\nTask context: {task_description}" if task_description else ""

        prompt = f"""Generate appropriate control measures for these hazards:{context}

Hazards:
{hazards_text}

Apply the hierarchy of controls:
1. Elimination - Remove the hazard entirely
2. Substitution - Replace with something less hazardous
3. Engineering controls - Isolate people from the hazard
4. Administrative controls - Change the way people work
5. PPE - Protect the worker with equipment (last resort)

For each hazard, provide 1-2 practical control measures.

Respond with JSON:
{{
    "controls": [
        {{"measure": "Control measure description", "associated_hazard": "Which hazard this addresses"}}
    ]
}}"""

        result = self._call_llm(prompt, expect_json=True)
        return result.get("controls", [])

    def improve_section(
        self, section_text: str, section_type: str, context: str = ""
    ) -> str:
        """
        Improve a specific section of a safety document.

        Args:
            section_text: Current text of the section
            section_type: Type of section (description, ppe, notes, etc.)
            context: Optional additional context

        Returns:
            Improved section text
        """
        context_text = f"\nAdditional context: {context}" if context else ""

        prompt = f"""Improve this {section_type} section of a safety document:{context_text}

Current text:
{section_text}

Guidelines:
- Make it clearer and more specific
- Ensure compliance with NZ WorkSafe guidelines
- Use active voice and imperative statements
- Keep it concise but comprehensive
- For PPE sections, ensure items are specific and appropriate
- For procedure steps, ensure they are actionable

Respond with JSON:
{{
    "improved_text": "The improved section text"
}}"""

        result = self._call_llm(prompt, expect_json=True)
        return result.get("improved_text", section_text)

    def improve_document(
        self, raw_text: str, document_type: str = "swp"
    ) -> dict[str, Any]:
        """
        AI improves an entire safety document from its raw text.

        Args:
            raw_text: Full text content of the document
            document_type: 'jsa' or 'swp'

        Returns:
            Complete improved document structure
        """
        doc_type_name = (
            "Job Safety Analysis (JSA)"
            if document_type == "jsa"
            else "Safe Work Procedure (SWP)"
        )

        prompt = f"""Review and improve this {doc_type_name} document:

{raw_text}

Your task:
1. Parse the existing content
2. Identify any missing or weak areas
3. Improve hazard identification
4. Strengthen control measures
5. Ensure PPE requirements are complete
6. Add any missing safety considerations

Return a complete, improved document in this JSON format:
{{
    "title": "Document title",
    "site_location": "Work location",
    "description": "Improved description of the work/procedure",
    "ppe_requirements": ["PPE item 1", "PPE item 2", ...],
    "tasks": [
        {{
            "step_number": 1,
            "description": "Detailed task/step description",
            "summary": "1-3 word summary",
            "potential_hazards": ["Hazard 1", "Hazard 2"],
            "initial_risk_rating": "Low|Moderate|High|Extreme",
            "control_measures": [
                {{"measure": "Control measure text", "associated_hazard": "Hazard it addresses"}}
            ],
            "revised_risk_rating": "Low|Moderate|High|Extreme"
        }}
    ],
    "additional_notes": "Any additional safety notes"
}}"""

        result = self._call_llm(prompt, expect_json=True)

        # Ensure all required fields exist
        result.setdefault("title", "Safety Document")
        result.setdefault("site_location", "")
        result.setdefault("description", "")
        result.setdefault("ppe_requirements", DEFAULT_PPE.copy())
        result.setdefault("tasks", [])
        result.setdefault("additional_notes", "")

        return result
