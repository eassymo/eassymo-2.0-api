 #!/usr/bin/env python3
"""
Test script to verify MongoDB connection and list collections.
"""

import sys
import os
from dotenv import load_dotenv
import pymongo

def test_db_connection():
    """Test the MongoDB connection and list collections."""
    
    # Load environment variables
    load_dotenv()
    
    mongo_uri = os.getenv("MONGO_URI")
    
    if not mongo_uri:
        print("❌ Error: MONGO_URI not found in environment variables")
        print("Make sure your .env file contains MONGO_URI=your_connection_string")
        return False
    
    print(f"🔗 Attempting to connect to MongoDB...")
    print(f"URI: {mongo_uri[:20]}..." if len(mongo_uri) > 20 else f"URI: {mongo_uri}")
    
    try:
        # Connect to MongoDB
        client = pymongo.MongoClient(mongo_uri)
        
        # Test the connection
        client.admin.command('ping')
        print("✅ Successfully connected to MongoDB!")
        
        # Get database
        db = client.EASSYMOSTAGING
        print(f"📊 Using database: {db.name}")
        
        # List collections
        collections = db.list_collection_names()
        print(f"📂 Found {len(collections)} collections:")
        
        for i, collection in enumerate(collections, 1):
            count = db[collection].count_documents({})
            print(f"  {i}. {collection} ({count:,} documents)")
        
        # Check for documents with coordinate fields
        print("\n🔍 Checking for documents with coordinate fields...")
        
        for collection_name in collections:
            collection = db[collection_name]
            
            # Check for coordinate fields
            sample_doc = collection.find_one({
                "$or": [
                    {"Entity_Location_Lat": {"$exists": True}},
                    {"Entity_Location_Lon": {"$exists": True}}
                ]
            })
            
            if sample_doc:
                # Count documents with string coordinates
                string_coords_count = collection.count_documents({
                    "$or": [
                        {"Entity_Location_Lat": {"$type": "string"}},
                        {"Entity_Location_Lon": {"$type": "string"}}
                    ]
                })
                
                if string_coords_count > 0:
                    print(f"  📍 {collection_name}: {string_coords_count:,} documents with string coordinates")
                    
                    # Show sample coordinate values
                    sample_with_string = collection.find_one({
                        "$or": [
                            {"Entity_Location_Lat": {"$type": "string"}},
                            {"Entity_Location_Lon": {"$type": "string"}}
                        ]
                    })
                    
                    if sample_with_string:
                        lat = sample_with_string.get("Entity_Location_Lat", "N/A")
                        lon = sample_with_string.get("Entity_Location_Lon", "N/A")
                        print(f"     Sample coordinates: Lat={lat}, Lon={lon}")
        
        return True
        
    except pymongo.errors.ServerSelectionTimeoutError as e:
        print(f"❌ Connection timeout: {str(e)}")
        print("Check if your MongoDB server is running and accessible")
        return False
    except pymongo.errors.ConfigurationError as e:
        print(f"❌ Configuration error: {str(e)}")
        print("Check your MONGO_URI format")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False


if __name__ == "__main__":
    print("🧪 Testing MongoDB Database Connection")
    print("=" * 50)
    
    success = test_db_connection()
    
    if success:
        print("\n✅ Database connection test completed successfully!")
        print("\nYou can now run the coordinate fixer script.")
    else:
        print("\n❌ Database connection test failed!")
        print("Please check your MongoDB configuration and try again.")
        sys.exit(1)