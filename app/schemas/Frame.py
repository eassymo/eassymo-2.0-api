from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

FrameStatus = Literal["active", "pending"]
ScreenshotSource = Literal["script", "manual"]

# Fields a super admin may edit. `code` never changes; screenshots go through the upload endpoint.
EDITABLE_FRAME_FIELDS = frozenset({"name", "description", "route", "sample", "element", "steps", "status", "notes", "needs_update"})


class FrameSchema(BaseModel):
    """A named place in the app (screen, dialog or control) that grants point to."""

    code: str = Field(description="Immutable frame code, e.g. C.WG.1; also the data-frame anchor in the client")
    name: str
    description: str = ""
    pov: str = "ambos"
    route: Optional[str] = None
    sample: Optional[str] = Field(None, description="Sample record the route needs, e.g. 'pedido'")
    element: Optional[str] = Field(None, description="What the screenshot outlines")
    steps: Optional[str] = Field(None, description="Steps before the screenshot, e.g. 'Abrir menú lateral'")
    status: FrameStatus = "active"
    notes: Optional[str] = None
    sort_order: int = 0
    screenshot_url: Optional[str] = None
    screenshot_source: Optional[ScreenshotSource] = None
    captured_at: Optional[datetime] = None
    captured_by: Optional[str] = None
    # Set when a code change touches this frame's screen (scripts/flag_changed_frames.py);
    # cleared by a new screenshot or by a super admin.
    needs_update: bool = False
    update_reason: Optional[str] = None
    flagged_at: Optional[datetime] = None
    flagged_by: Optional[str] = None
