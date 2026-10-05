from botocore.exceptions import NoCredentialsError
from app.factories.AwsFactory import create_aws_session
from typing import List
from fastapi import HTTPException, UploadFile, status
from dotenv import load_dotenv
import os
from uuid import uuid4
from app.repositories import PhotoRepository as photoRepository

load_dotenv()

ALLOWED_IMAGE_CONTENT_TYPES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
})
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _validate_upload_file(file: UploadFile) -> None:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image uploads are allowed",
        )
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File exceeds maximum upload size",
        )


async def upload_guest_photos(files: List[UploadFile], guest_token: str) -> dict:
    """
    Uploads files to S3 under the guest/<guest_token>/ prefix.
    Returns the list of uploaded URLs.
    """
    session = create_aws_session()
    uploaded_urls: List[str] = []

    for file in files:
        _validate_upload_file(file)
        url = await _upload_image_to_s3_with_prefix(session, file, prefix=f"guest/{guest_token}")
        uploaded_urls.append(url)

    return {"message": "ok", "body": uploaded_urls}


async def upload_tube_photos(files: List[UploadFile], tube_token: str) -> dict:
    """Uploads files to S3 under tube/<tube_token>/ for temp-shop quoting."""
    session = create_aws_session()
    uploaded_urls: List[str] = []

    for file in files:
        _validate_upload_file(file)
        url = await _upload_image_to_s3_with_prefix(session, file, prefix=f"tube/{tube_token}")
        uploaded_urls.append(url)

    return {"message": "ok", "body": uploaded_urls}


async def _upload_image_to_s3_with_prefix(session, file: UploadFile, prefix: str) -> str:
    bucket_name = os.getenv("AWS_BUCKET_NAME")
    await file.seek(0)
    client = session.resource("s3")
    bucket = client.Bucket(bucket_name)
    formatted_name = os.path.basename(file.filename)
    object_name = f"{prefix}/{str(uuid4())}-{formatted_name}"
    bucket.upload_fileobj(file.file, object_name)
    return f"https://{bucket_name}.s3.amazonaws.com/{object_name}"


async def upload_user_photos(files: List[UploadFile], userId: str):
    uploadedImageURL = ""
    uploadedImageUrls: List[str] = []
    session = create_aws_session()
    for file in files:
        _validate_upload_file(file)
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
