#!/usr/bin/env python3
"""
Wrapper script to run the coordinate fixer from the project root.
This avoids Python path issues.
"""

import sys
import os

# Ensure we're in the project root
if not os.path.exists('app/utils/fix_coordinates.py'):
    print("Error: This script must be run from the project root directory")
    sys.exit(1)

# Import and run the coordinate fixer
from app.utils.fix_coordinates import fix_coordinates_in_collection

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix malformed coordinates in MongoDB collection')
    parser.add_argument('collection', help='MongoDB collection name')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for processing')
    parser.add_argument('--dry-run', action='store_true', help='Simulate fixes without updating')
    parser.add_argument('--preview', action='store_true', help='Preview fixes for first N documents')
    parser.add_argument('--preview-limit', type=int, default=10, help='Number of documents to preview')
    
    args = parser.parse_args()
    
    try:
        if args.preview:
            fix_coordinates_in_collection(
                collection_name=args.collection,
                preview=True,
                preview_limit=args.preview_limit
            )
        else:
            stats = fix_coordinates_in_collection(
                collection_name=args.collection,
                batch_size=args.batch_size,
                dry_run=args.dry_run
            )
            
            if not args.dry_run:
                print(f"\nCoordinate fixing completed successfully!")
            else:
                print(f"\nDry run completed!")
                
            print(f"Total processed: {stats['total_processed']}")
            print(f"Total fixed: {stats['total_fixed']}")
            print(f"Invalid coordinates: {stats['invalid_coordinates']}")
            print(f"Errors: {stats['total_errors']}")
        
    except Exception as e:
        print(f"Coordinate fixing failed: {str(e)}")
        sys.exit(1) 