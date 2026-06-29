import sys
import os
import logging
from typing import Dict, Any, Optional
import re

# Add the project root to the path to import from app.config
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.config.database import db

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CoordinateFixer:
    """
    A utility class for fixing malformed latitude and longitude coordinates in MongoDB.
    """
    
    def __init__(self, collection_name: str):
        """
        Initialize the coordinate fixer with a specific MongoDB collection.
        
        Args:
            collection_name (str): Name of the MongoDB collection to fix
        """
        self.collection = db[collection_name]
        self.collection_name = collection_name
        
    def parse_coordinate(self, coord_str: str) -> Optional[float]:
        """
        Parse a malformed coordinate string and convert to proper decimal format.
        
        Args:
            coord_str (str): Malformed coordinate string (e.g., "2.190.635.038")
            
        Returns:
            Optional[float]: Parsed coordinate or None if invalid
        """
        if not coord_str or not isinstance(coord_str, str):
            return None
            
        try:
            # Handle negative sign
            is_negative = coord_str.startswith('-')
            clean_str = coord_str.lstrip('-')
            
            # Check if this is already a proper decimal format (with comma or single period)
            if ',' in clean_str and clean_str.count(',') == 1:
                # Format like "19,81052532" -> "19.81052532"
                coord_float = float(clean_str.replace(',', '.'))
                if is_negative:
                    coord_float = -coord_float
                return coord_float
            elif '.' in clean_str and clean_str.count('.') == 1:
                # Already proper decimal format like "19.81052532"
                coord_float = float(clean_str)
                if is_negative:
                    coord_float = -coord_float
                return coord_float
            
            # Remove all periods and treat as a malformed coordinate
            # Handle cases like "2.190.635.038" -> "21.90635038"
            clean_str = clean_str.replace('.', '')
            
            # Convert to float and adjust decimal placement
            if len(clean_str) >= 8:  # Handle longer coordinate strings
                # For coordinates like "2189187626" -> "21.89187626"
                # For coordinates like "1022719395" -> "102.2719395"
                if len(clean_str) == 10:  # Like "2189187626" or "1022719395"
                    if clean_str.startswith('10'):  # Longitude like "1022719395" -> "102.2719395"
                        coord_float = float(clean_str[:3] + '.' + clean_str[3:])
                    else:  # Latitude like "2189187626" -> "21.89187626"
                        coord_float = float(clean_str[:2] + '.' + clean_str[2:])
                elif len(clean_str) == 9:  # Like "218918762" or "102275449"
                    if clean_str.startswith('10'):  # Longitude like "102275449" -> "102.275449"
                        coord_float = float(clean_str[:3] + '.' + clean_str[3:])
                    else:  # Latitude like "218918762" -> "21.8918762"
                        coord_float = float(clean_str[:2] + '.' + clean_str[2:])
                else:
                    # General case: determine based on expected ranges for Mexico
                    # Mexico lat: ~14-32°N, lon: ~86-118°W
                    if clean_str.startswith('10') or clean_str.startswith('11'):  # Longitude 100-119°
                        coord_float = float(clean_str[:3] + '.' + clean_str[3:])
                    else:  # Latitude 14-32°
                        coord_float = float(clean_str[:2] + '.' + clean_str[2:])
            elif len(clean_str) >= 6:
                # Shorter strings: place decimal after 2nd digit for lat, 3rd for lon starting with 10
                if clean_str.startswith('10'):
                    coord_float = float(clean_str[:3] + '.' + clean_str[3:])
                else:
                    coord_float = float(clean_str[:2] + '.' + clean_str[2:])
            else:
                # Very short strings: try direct conversion
                coord_float = float(clean_str)
            
            # Apply negative sign if needed
            if is_negative:
                coord_float = -coord_float
                
            return coord_float
                
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not parse coordinate: {coord_str} - {str(e)}")
            return None
    
    def validate_coordinates(self, lat: float, lon: float) -> bool:
        """
        Validate if coordinates are within valid ranges.
        
        Args:
            lat (float): Latitude value
            lon (float): Longitude value
            
        Returns:
            bool: True if coordinates are valid
        """
        return (-90 <= lat <= 90) and (-180 <= lon <= 180)
    
    def fix_document_coordinates(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fix coordinates in a single document.
        
        Args:
            doc (Dict[str, Any]): MongoDB document
            
        Returns:
            Dict[str, Any]: Document with fixed coordinates or None if no changes needed
        """
        changes = {}
        
        # Check for latitude field
        lat_field = "Entity_Location_Lat"
        lon_field = "Entity_Location_Lon"
        
        if lat_field in doc and isinstance(doc[lat_field], str):
            fixed_lat = self.parse_coordinate(doc[lat_field])
            if fixed_lat is not None:
                changes[lat_field] = fixed_lat
        
        if lon_field in doc and isinstance(doc[lon_field], str):
            fixed_lon = self.parse_coordinate(doc[lon_field])
            if fixed_lon is not None:
                changes[lon_field] = fixed_lon
        
        # Validate coordinates if both were parsed
        if lat_field in changes and lon_field in changes:
            if not self.validate_coordinates(changes[lat_field], changes[lon_field]):
                logger.warning(f"Invalid coordinates for document {doc.get('_id')}: "
                             f"lat={changes[lat_field]}, lon={changes[lon_field]}")
                return None
        
        return changes if changes else None
    
    def fix_all_coordinates(self, batch_size: int = 1000, dry_run: bool = False) -> Dict[str, int]:
        """
        Fix coordinates in all documents in the collection.
        
        Args:
            batch_size (int): Number of documents to process in each batch
            dry_run (bool): If True, only simulate the fixes without updating
            
        Returns:
            Dict[str, int]: Statistics about the fix operation
        """
        stats = {
            'total_processed': 0,
            'total_fixed': 0,
            'total_errors': 0,
            'invalid_coordinates': 0
        }
        
        try:
            # Find documents with string coordinates
            query = {
                "$or": [
                    {"Entity_Location_Lat": {"$type": "string"}},
                    {"Entity_Location_Lon": {"$type": "string"}}
                ]
            }
            
            total_docs = self.collection.count_documents(query)
            logger.info(f"Found {total_docs} documents with string coordinates")
            
            if dry_run:
                logger.info("DRY RUN MODE - No actual updates will be performed")
            
            # Process documents in batches
            skip = 0
            while skip < total_docs:
                docs = list(self.collection.find(query).skip(skip).limit(batch_size))
                
                for doc in docs:
                    stats['total_processed'] += 1
                    
                    try:
                        changes = self.fix_document_coordinates(doc)
                        
                        if changes:
                            if not dry_run:
                                # Update the document
                                result = self.collection.update_one(
                                    {"_id": doc["_id"]},
                                    {"$set": changes}
                                )
                                
                                if result.modified_count > 0:
                                    stats['total_fixed'] += 1
                                    logger.debug(f"Fixed coordinates for document {doc['_id']}")
                            else:
                                stats['total_fixed'] += 1
                                logger.info(f"Would fix document {doc['_id']}: {changes}")
                        else:
                            stats['invalid_coordinates'] += 1
                            
                    except Exception as e:
                        stats['total_errors'] += 1
                        logger.error(f"Error processing document {doc.get('_id')}: {str(e)}")
                
                skip += batch_size
                logger.info(f"Processed {min(skip, total_docs)}/{total_docs} documents")
            
            logger.info(f"Coordinate fixing completed. Stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error during coordinate fixing: {str(e)}")
            raise
    
    def preview_fixes(self, limit: int = 10) -> None:
        """
        Preview what fixes would be applied to documents.
        
        Args:
            limit (int): Number of documents to preview
        """
        query = {
            "$or": [
                {"Entity_Location_Lat": {"$type": "string"}},
                {"Entity_Location_Lon": {"$type": "string"}}
            ]
        }
        
        docs = list(self.collection.find(query).limit(limit))
        
        print(f"\nPreview of coordinate fixes (showing up to {limit} documents):")
        print("-" * 80)
        
        for doc in docs:
            changes = self.fix_document_coordinates(doc)
            if changes:
                print(f"Document ID: {doc['_id']}")
                print(f"  Original Lat: {doc.get('Entity_Location_Lat')}")
                print(f"  Fixed Lat:    {changes.get('Entity_Location_Lat', 'No change')}")
                print(f"  Original Lon: {doc.get('Entity_Location_Lon')}")
                print(f"  Fixed Lon:    {changes.get('Entity_Location_Lon', 'No change')}")
                print("-" * 40)


def fix_coordinates_in_collection(
    collection_name: str,
    batch_size: int = 1000,
    dry_run: bool = False,
    preview: bool = False,
    preview_limit: int = 10
) -> Dict[str, int]:
    """
    Convenience function to fix coordinates in a MongoDB collection.
    
    Args:
        collection_name (str): Name of the MongoDB collection
        batch_size (int): Batch size for processing
        dry_run (bool): If True, simulate fixes without updating
        preview (bool): If True, show preview of fixes
        preview_limit (int): Number of documents to preview
        
    Returns:
        Dict[str, int]: Fix operation statistics
    """
    fixer = CoordinateFixer(collection_name)
    
    if preview:
        fixer.preview_fixes(preview_limit)
        return {}
    
    return fixer.fix_all_coordinates(batch_size=batch_size, dry_run=dry_run)


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