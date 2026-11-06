"""Feed the Brands / Guarantees autocomplete from option capture.

Offers do this in OfferService. Mostrador options (POS capture, offer creator,
tube and invited shops) are stored on the folio instead, so they call here.
BrandService / GuaranteeService skip a label that already exists.
"""

import logging
from typing import Iterable, Optional, Set

from app.schemas.Brand import Brand
from app.schemas.Guarantee import Guarantee
from app.services import BrandService as brandService
from app.services import GuaranteeService as guaranteeService

logger = logging.getLogger(__name__)

FALLBACK_USER_UID = "mostrador"


def _label(value) -> str:
    return " ".join(str(value or "").split())


def option_labels(options: Iterable[dict]) -> tuple[Set[str], Set[str]]:
    """Distinct brand and guarantee labels (case-insensitive) in these options."""
    brands: dict[str, str] = {}
    guarantees: dict[str, str] = {}
    for option in options or []:
        brand = _label((option or {}).get("brand"))
        guarantee = _label((option or {}).get("guarantee"))
        if brand:
            brands.setdefault(brand.lower(), brand)
        if guarantee:
            guarantees.setdefault(guarantee.lower(), guarantee)
    return set(brands.values()), set(guarantees.values())


def record_option_labels(
    options: Iterable[dict],
    user_uid: Optional[str],
    *,
    known: Optional[Iterable[dict]] = None,
) -> None:
    """Add new brands and guarantees from `options`; never fails the caller.

    `known` are options already saved, whose labels were recorded earlier.
    """
    try:
        brands, guarantees = option_labels(options)
        known_brands, known_guarantees = option_labels(known or [])
        known_brands = {b.lower() for b in known_brands}
        known_guarantees = {g.lower() for g in known_guarantees}
        uid = user_uid or FALLBACK_USER_UID
        for label in sorted(brands):
            if label.lower() not in known_brands:
                brandService.insert(Brand(label=label, user_uid=uid))
        for label in sorted(guarantees):
            if label.lower() not in known_guarantees:
                guaranteeService.insert(Guarantee(label=label, user_uid=uid))
    except Exception:
        logger.exception("Could not record brand/guarantee labels")
