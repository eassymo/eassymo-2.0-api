#!/usr/bin/env python3
"""Create MongoDB indexes for GroupReviews and ReviewDisputes collections."""
from __future__ import print_function

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories import ReviewRepository as reviewRepository


def main():
    reviewRepository.ensure_indexes()
    print("Review indexes ensured.")


if __name__ == "__main__":
    main()
