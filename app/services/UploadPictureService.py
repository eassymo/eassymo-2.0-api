from botocore.exceptions import NoCredentialsError
from app.factories.AwsFactory import create_aws_session
from typing import List
from fastapi import UploadFile
from dotenv import load_dotenv
import os
from uuid import uuid4
from app.repositories import PhotoRepository as photoRepository

load_dotenv()


async def upload_user_photos(files: List[UploadFile], userId: str):
    uploadedImageURL = ""
    uploadedImageUrls: List[str] = []
    session = create_aws_session()
    for file in files:
        uploadedImageURL = await upload_image_to_S3(session, file)
        uploadedImageUrls.append(uploadedImageURL)
        uploadPhotoToDB = {
            "fileName": file.filename,
            "url": uploadedImageURL,
            "userId": userId,
        }

        photoRepository.insert(uploadPhotoToDB)

    return {"message:": "OK", "body": uploadedImageUrls}


async def upload_image_to_S3(session, file: UploadFile):
    bucket_name = os.getenv("AWS_BUCKET_NAME")
    await file.seek(0)
    client = session.resource("s3")
    bucket = client.Bucket(bucket_name)
    formatted_name = os.path.basename(file.filename)
    object_name = f'{str(uuid4())}-{formatted_name}'
    bucket.upload_fileobj(
        file.file,
        object_name
    )
    return f"https://{bucket_name}.s3.amazonaws.com/{object_name}"
