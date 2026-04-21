"""
ProcedureService — Orchestrates JSA/SWP/SOP generation workflow.

Handles:
- Generating new JSAs from job context
- Generating new SWPs (standalone)
- Generating new SOPs (standalone)
- Creating blank procedures with Google Docs
"""

import logging

from django.db import transaction

from apps.job.models import Job, JobEvent
from apps.process.models import Procedure
from apps.process.services.google_docs_service import GoogleDocsService
from apps.process.services.safety_ai_service import SafetyAIService
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class ProcedureService:
    """
    Service for managing procedure lifecycle.

    Orchestrates JSA/SWP/SOP generation with AI content and Google Docs creation.
    """

    def __init__(self):
        self.ai_service = SafetyAIService()
        self.docs_service = GoogleDocsService()

    @transaction.atomic
    def generate_jsa(self, job: Job) -> Procedure:
        """Generate a new JSA for a job using AI and create Google Doc."""
        logger.info(f"Generating JSA for job {job.job_number}: {job.name}")

        try:
            jsa_content = self.ai_service.generate_full_jsa(job=job)

            doc_result = self.docs_service.create_process_document(
                document_type="jsa",
                title=jsa_content.get("title", job.name),
                content=jsa_content,
                job=job,
            )

            jsa = Procedure.objects.create(
                document_type="procedure",
                tags=["jsa", "safety"],
                job=job,
                title=jsa_content.get("title", job.name),
                site_location=jsa_content.get("site_location", ""),
                google_doc_id=doc_result.document_id,
                google_doc_url=doc_result.edit_url,
            )

            JobEvent.objects.create(
                job=job,
                event_type="jsa_generated",
                detail={
                    "jsa_title": jsa.title,
                    "jsa_id": str(jsa.id),
                    "google_doc_url": doc_result.edit_url,
                },
            )

            logger.info(
                f"JSA created: {jsa.id} for job {job.job_number} "
                f"-> {doc_result.edit_url}"
            )
            return jsa

        except Exception as exc:
            logger.exception(f"Failed to generate JSA for job {job.job_number}")
            persist_app_error(exc)
            raise

    @transaction.atomic
    def generate_swp(
        self,
        title: str,
        description: str,
        site_location: str = "",
        document_number: str = "",
    ) -> Procedure:
        """Generate a new SWP (standalone) using AI and create Google Doc."""
        logger.info(f"Generating SWP: {title} (doc #{document_number or 'N/A'})")

        try:
            swp_content = self.ai_service.generate_full_swp(
                title=title,
                description=description,
                site_location=site_location,
            )

            doc_result = self.docs_service.create_process_document(
                document_type="swp",
                title=swp_content.get("title", title),
                content=swp_content,
                job=None,
                document_number=document_number,
            )

            swp = Procedure.objects.create(
                document_type="procedure",
                tags=["swp", "safety"],
                job=None,
                document_number=document_number or None,
                title=swp_content.get("title", title),
                site_location=swp_content.get("site_location", site_location),
                google_doc_id=doc_result.document_id,
                google_doc_url=doc_result.edit_url,
            )

            logger.info(f"SWP created: {swp.id} -> {doc_result.edit_url}")
            return swp

        except Exception as exc:
            logger.exception(f"Failed to generate SWP: {title}")
            persist_app_error(exc)
            raise

    @transaction.atomic
    def generate_sop(
        self,
        title: str,
        description: str,
        document_number: str = "",
    ) -> Procedure:
        """Generate a new SOP (Standard Operating Procedure) using AI and create Google Doc."""
        logger.info(f"Generating SOP: {title} (doc #{document_number or 'N/A'})")

        try:
            sop_content = self.ai_service.generate_full_sop(
                title=title,
                description=description,
                document_number=document_number,
            )

            doc_result = self.docs_service.create_process_document(
                document_type="sop",
                title=sop_content.get("title", title),
                content=sop_content,
                job=None,
                document_number=document_number,
            )

            sop = Procedure.objects.create(
                document_type="procedure",
                tags=["sop", "safety"],
                job=None,
                document_number=document_number or None,
                title=sop_content.get("title", title),
                site_location="",
                google_doc_id=doc_result.document_id,
                google_doc_url=doc_result.edit_url,
            )

            logger.info(f"SOP created: {sop.id} -> {doc_result.edit_url}")
            return sop

        except Exception as exc:
            logger.exception(f"Failed to generate SOP: {title}")
            persist_app_error(exc)
            raise

    @transaction.atomic
    def create_blank_procedure(
        self,
        document_type: str,
        title: str,
        tags: list[str] | None = None,
        document_number: str = "",
        site_location: str = "",
    ) -> Procedure:
        """Create a blank Procedure with a new Google Doc."""
        valid_types = [t[0] for t in Procedure.DOCUMENT_TYPES]
        if document_type not in valid_types:
            raise ValueError(
                f"Invalid document_type '{document_type}'. "
                f"Must be one of: {valid_types}"
            )

        company = CompanyDefaults.get_solo()
        folder_id = company.gdrive_reference_library_folder_id
        if not folder_id:
            raise ValueError(
                "gdrive_reference_library_folder_id is not configured in CompanyDefaults"
            )

        doc_result = self.docs_service.create_blank_in_folder(
            title=title, folder_id=folder_id
        )

        doc = Procedure.objects.create(
            document_type=document_type,
            title=title,
            tags=tags or [],
            document_number=document_number or None,
            site_location=site_location,
            status="draft",
            google_doc_id=doc_result.document_id,
            google_doc_url=doc_result.edit_url,
        )

        logger.info(f"Created blank procedure: {doc.pk} -> {doc_result.edit_url}")
        return doc
