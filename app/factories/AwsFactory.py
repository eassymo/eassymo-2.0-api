import boto3
import os
from dotenv import load_dotenv

load_dotenv()

def create_aws_session():
    return boto3.Session(aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                        aws_secret_access_key=os.getenv(
                            "AWS_SECRET_ACCESS_KEY"),
                        region_name=os.getenv("AWS_REGION"))