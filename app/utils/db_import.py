import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
import logging
from datetime import datetime
import sys
import os

# Add the project root to the path to import from app.config
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.config.database import db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CSVToMongoImporter:
    """
    A utility class for importing CSV data into MongoDB collections.
    """
    
    def __init__(self, collection_name: str):
        """
        Initialize the importer with a specific MongoDB collection.
        
        Args:
            collection_name (str): Name of the MongoDB collection to import data into
        """
        self.collection = db[collection_name]
        self.collection_name = collection_name
        
    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean the DataFrame by handling NaN values and data types.
        
        Args:
            df (pd.DataFrame): Input DataFrame
            
        Returns:
            pd.DataFrame: Cleaned DataFrame
        """
        # Replace NaN values with None (which becomes null in MongoDB)
        df = df.replace({np.nan: None})
        
        # Convert numpy data types to Python native types
        for col in df.columns:
            if df[col].dtype == 'object':
                # Keep as is for strings and mixed types
                continue
            elif pd.api.types.is_integer_dtype(df[col]):
                df[col] = df[col].astype('Int64')  # Nullable integer
            elif pd.api.types.is_float_dtype(df[col]):
                df[col] = df[col].astype('float64')
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = pd.to_datetime(df[col])
                
        return df
    
    def transform_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform a single record before insertion.
        Override this method for custom transformations.
        
        Args:
            record (Dict[str, Any]): Input record
            
        Returns:
            Dict[str, Any]: Transformed record
        """
        # Add import timestamp
        record['_imported_at'] = datetime.utcnow()

        if record["Entity_Location_Lat"] and record["Entity_Location_Lon"]:
            lon = float(record["Entity_Location_Lon"].replace(",", "."))
            lat = float(record["Entity_Location_Lat"].replace(",", "."))

        record["location"] = {
            "type": "Point",
            "coordinates": [lon, lat]
        }
        
        # Convert pandas Timestamp to datetime
        for key, value in record.items():
            if isinstance(value, pd.Timestamp):
                record[key] = value.to_pydatetime()
            elif pd.isna(value):
                record[key] = None
                
        return record
    
    def import_csv(
        self,
        csv_file_path: str,
        batch_size: int = 1000,
        skip_duplicates: bool = True,
        unique_field: Optional[str] = None,
        encoding: str = 'utf-8',
        **csv_kwargs
    ) -> Dict[str, int]:
        """
        Import CSV data into MongoDB collection.
        
        Args:
            csv_file_path (str): Path to the CSV file
            batch_size (int): Number of records to insert in each batch
            skip_duplicates (bool): Whether to skip duplicate records
            unique_field (str): Field name to check for duplicates (if skip_duplicates=True)
            encoding (str): File encoding
            **csv_kwargs: Additional arguments for pd.read_csv()
            
        Returns:
            Dict[str, int]: Statistics about the import operation
        """
        try:
            # Read CSV file
            logger.info(f"Reading CSV file: {csv_file_path}")
            df = pd.read_csv(csv_file_path, encoding=encoding, **csv_kwargs)
            logger.info(f"Loaded {len(df)} records from CSV")
            
            # Clean data
            df = self.clean_data(df)
            
            # Convert to list of dictionaries
            records = df.to_dict('records')
            
            # Transform records
            records = [self.transform_record(record) for record in records]
            
            # Import statistics
            stats = {
                'total_records': len(records),
                'inserted_records': 0,
                'skipped_records': 0,
                'error_records': 0
            }
            
            # Process in batches
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                batch_stats = self._insert_batch(batch, skip_duplicates, unique_field)
                
                # Update statistics
                stats['inserted_records'] += batch_stats['inserted']
                stats['skipped_records'] += batch_stats['skipped']
                stats['error_records'] += batch_stats['errors']
                
                logger.info(f"Processed batch {i//batch_size + 1}: "
                           f"{batch_stats['inserted']} inserted, "
                           f"{batch_stats['skipped']} skipped, "
                           f"{batch_stats['errors']} errors")
            
            logger.info(f"Import completed. Final stats: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error importing CSV: {str(e)}")
            raise
    
    def _insert_batch(
        self,
        batch: List[Dict[str, Any]],
        skip_duplicates: bool,
        unique_field: Optional[str]
    ) -> Dict[str, int]:
        """
        Insert a batch of records into MongoDB.
        
        Args:
            batch (List[Dict[str, Any]]): Batch of records to insert
            skip_duplicates (bool): Whether to skip duplicates
            unique_field (str): Field to check for duplicates
            
        Returns:
            Dict[str, int]: Batch statistics
        """
        batch_stats = {'inserted': 0, 'skipped': 0, 'errors': 0}
        
        if not skip_duplicates:
            # Simple bulk insert
            try:
                result = self.collection.insert_many(batch)
                batch_stats['inserted'] = len(result.inserted_ids)
            except Exception as e:
                logger.error(f"Bulk insert error: {str(e)}")
                batch_stats['errors'] = len(batch)
        else:
            # Insert with duplicate checking
            for record in batch:
                try:
                    if unique_field and unique_field in record:
                        # Check if record already exists
                        existing = self.collection.find_one({unique_field: record[unique_field]})
                        if existing:
                            batch_stats['skipped'] += 1
                            continue
                    
                    # Insert record
                    self.collection.insert_one(record)
                    batch_stats['inserted'] += 1
                    
                except Exception as e:
                    logger.error(f"Error inserting record: {str(e)}")
                    batch_stats['errors'] += 1
        
        return batch_stats
    
    def create_index(self, field_name: str, unique: bool = False) -> None:
        """
        Create an index on the specified field.
        
        Args:
            field_name (str): Name of the field to index
            unique (bool): Whether the index should be unique
        """
        try:
            self.collection.create_index(field_name, unique=unique)
            logger.info(f"Created {'unique ' if unique else ''}index on field: {field_name}")
        except Exception as e:
            logger.error(f"Error creating index: {str(e)}")
            raise
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the collection.
        
        Returns:
            Dict[str, Any]: Collection statistics
        """
        try:
            stats = {
                'document_count': self.collection.count_documents({}),
                'collection_name': self.collection_name,
                'indexes': list(self.collection.list_indexes())
            }
            return stats
        except Exception as e:
            logger.error(f"Error getting collection stats: {str(e)}")
            raise


def import_csv_to_mongo(
    csv_file_path: str,
    collection_name: str,
    batch_size: int = 1000,
    skip_duplicates: bool = True,
    unique_field: Optional[str] = None,
    create_unique_index: bool = False,
    encoding: str = 'utf-8',
    **csv_kwargs
) -> Dict[str, int]:
    """
    Convenience function to import CSV data to MongoDB.
    
    Args:
        csv_file_path (str): Path to the CSV file
        collection_name (str): MongoDB collection name
        batch_size (int): Batch size for insertion
        skip_duplicates (bool): Whether to skip duplicate records
        unique_field (str): Field name to check for duplicates
        create_unique_index (bool): Whether to create a unique index on unique_field
        encoding (str): File encoding
        **csv_kwargs: Additional arguments for pd.read_csv()
        
    Returns:
        Dict[str, int]: Import statistics
    """
    importer = CSVToMongoImporter(collection_name)
    
    # Create unique index if requested
    if create_unique_index and unique_field:
        importer.create_index(unique_field, unique=True)
    
    # Import data
    stats = importer.import_csv(
        csv_file_path=csv_file_path,
        batch_size=batch_size,
        skip_duplicates=skip_duplicates,
        unique_field=unique_field,
        encoding=encoding,
        **csv_kwargs
    )
    
    return stats


if __name__ == "__main__":
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description='Import CSV data to MongoDB')
    parser.add_argument('csv_file', help='Path to CSV file')
    parser.add_argument('collection', help='MongoDB collection name')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for insertion')
    parser.add_argument('--skip-duplicates', action='store_true', help='Skip duplicate records')
    parser.add_argument('--unique-field', help='Field to check for duplicates')
    parser.add_argument('--create-index', action='store_true', help='Create unique index on unique field')
    parser.add_argument('--encoding', default='utf-8', help='File encoding')
    
    args = parser.parse_args()
    
    try:
        stats = import_csv_to_mongo(
            csv_file_path=args.csv_file,
            collection_name=args.collection,
            batch_size=args.batch_size,
            skip_duplicates=args.skip_duplicates,
            unique_field=args.unique_field,
            create_unique_index=args.create_index,
            encoding=args.encoding
        )
        
    except Exception as e:
        print(f"Import failed: {str(e)}")
        sys.exit(1)


class CustomImporter(CSVToMongoImporter):
    def transform_record(self, record):
        # Custom transformation logic
        record = super().transform_record(record)
        
        # Example: Convert string dates to datetime
        if 'date_field' in record and record['date_field']:
            record['date_field'] = pd.to_datetime(record['date_field'])
        
        # Example: Add custom fields
        record['processed_by'] = 'custom_importer'
        
        return record

# Use custom importer
importer = CustomImporter("my_collection")
stats = importer.import_csv("data.csv") 