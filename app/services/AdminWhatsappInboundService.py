from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.repositories import WhatsappInboundRepository as inbound_repo


class AdminWhatsappInboundService:
    @staticmethod
    def list_messages(
        page: int = 1,
        page_size: int = 20,
        *,
        from_number: Optional[str] = None,
        extraction_status: Optional[str] = None,
        processing_status: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return inbound_repo.list_messages(
            page,
            page_size,
            from_number=from_number,
            extraction_status=extraction_status,
            processing_status=processing_status,
            group_id=group_id,
        )

    @staticmethod
    def get_message(document_id: str) -> Dict[str, Any]:
        doc = inbound_repo.find_by_id(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="WhatsApp inbound message not found")
        return doc
