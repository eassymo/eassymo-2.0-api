#!/usr/bin/env python3
"""Reveal pending reviews whose double-blind window has expired."""
from __future__ import print_function

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ReviewService


def main():
    result = ReviewService.reveal_expired_reviews()
    print("Reveal sweep complete:")
    print("  revealed_transactions: {}".format(result["revealed_transactions"]))
    print("  affected_groups: {}".format(result["affected_groups"]))


if __name__ == "__main__":
    main()
