#!/usr/bin/env python3
"""Hourly cron: send relationship review reminders when due."""
from __future__ import print_function

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import RelationshipService


def main():
    RelationshipService.ensure_indexes()
    result = RelationshipService.send_due_reminders()
    print("Relationship reminder sweep complete:")
    print("  considered: {}".format(result["considered"]))
    print("  sent: {}".format(result["sent"]))
    print("  skipped: {}".format(result["skipped"]))


if __name__ == "__main__":
    main()
