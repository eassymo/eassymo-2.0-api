"""Grant sets that keep today's access for the legacy roles (role-templates.csv, legacy rows).

Used by the migration, and as a safety net in authz while a legacy role has no `grants`
field yet (code deployed before the migration ran).
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, Optional

ROLE_DATA = Path(__file__).resolve().parents[2] / "scripts" / "data" / "role_templates.json"

LEGACY_VALUE_TO_SET: Dict[str, str] = {
    "212": "legacy.with_wa_draft",
    "213": "legacy.with_wa_draft",
    "214": "legacy.standard",
    "322": "legacy.standard",
    "324": "legacy.standard",
    "326": "legacy.standard",
    "327": "legacy.standard",
    "215": "legacy.215",
}


@lru_cache(maxsize=1)
def role_data() -> Dict[str, dict]:
    return {r["id"]: r for r in json.loads(ROLE_DATA.read_text(encoding="utf-8"))}


def legacy_grants(role_value) -> Optional[FrozenSet[str]]:
    set_id = LEGACY_VALUE_TO_SET.get(str(role_value).strip())
    return frozenset(role_data()[set_id]["grants"]) if set_id else None
