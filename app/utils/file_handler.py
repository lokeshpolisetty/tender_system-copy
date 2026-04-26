"""
Secure file upload handling.
Upgraded: saves to Amazon S3 (private bucket via VPC Endpoint).
Falls back to local disk if USE_S3=false.
"""

import os
import uuid
import logging
from typing import Optional, Set
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from flask import current_app

logger = logging.getLogger(__name__)


def save_uploaded_file(
    file: FileStorage,
    subfolder: str = '',
    allowed_extensions: Optional[Set[str]] = None,
) -> Optional[str]:
    """
    Validate and save an uploaded file.
    Returns an S3 key (s3://bucket/key) when USE_S3=true,
    or an absolute local path otherwise.
    """
    if not file or not file.filename:
        return None

    allowed = allowed_extensions or current_app.config.get(
        'ALLOWED_EXTENSIONS', {'pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg'})

    ext = _get_extension(file.filename)
    if ext not in allowed:
        logger.warning(f'File upload rejected — extension "{ext}" not in {allowed}')
        return None

    original_stem = secure_filename(file.filename.rsplit('.', 1)[0])[:50]
    unique_name = f"{original_stem}_{uuid.uuid4().hex}.{ext}"
    s3_key = f"uploads/{subfolder}/{unique_name}".replace('//', '/')

    if current_app.config.get('USE_S3'):
        return _save_to_s3(file, s3_key)
    else:
        return _save_to_local(file, subfolder, unique_name)


def _save_to_s3(file: FileStorage, s3_key: str) -> Optional[str]:
    """Upload file to S3. Returns s3_key string on success."""
    try:
        import boto3
        s3 = boto3.client(
            's3',
            region_name=current_app.config.get('AWS_S3_REGION', 'ap-south-1'),
        )
        bucket = current_app.config['AWS_S3_BUCKET']
        file.stream.seek(0)
        s3.upload_fileobj(
            file.stream,
            bucket,
            s3_key,
            ExtraArgs={
                'ServerSideEncryption': 'aws:kms',    # Encrypt at rest with KMS
                'ContentType': _mime_for_ext(_get_extension(s3_key)),
            }
        )
        logger.info(f'File uploaded to S3: s3://{bucket}/{s3_key}')
        return s3_key
    except Exception as e:
        logger.error(f'S3 upload failed: {e}')
        return None


def _save_to_local(file: FileStorage, subfolder: str, filename: str) -> Optional[str]:
    upload_base = current_app.config['UPLOAD_FOLDER']
    dest_dir = os.path.join(upload_base, subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, filename)
    file.save(dest_path)
    logger.info(f'File saved locally: {dest_path}')
    return dest_path


def get_presigned_url(file_path: str, expiry: int = 3600) -> Optional[str]:
    """
    Generate a short-lived pre-signed S3 URL for downloading a file.
    file_path is either an S3 key or a local path.
    """
    if not current_app.config.get('USE_S3'):
        return None  # Caller should use Flask send_from_directory for local files

    try:
        import boto3
        s3 = boto3.client(
            's3',
            region_name=current_app.config.get('AWS_S3_REGION', 'ap-south-1'),
        )
        url = s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': current_app.config['AWS_S3_BUCKET'],
                'Key': file_path,
            },
            ExpiresIn=expiry,
        )
        return url
    except Exception as e:
        logger.error(f'Pre-signed URL generation failed: {e}')
        return None


def delete_file(file_path: str) -> bool:
    """Delete a file from S3 or local disk."""
    if current_app.config.get('USE_S3'):
        try:
            import boto3
            s3 = boto3.client(
                's3',
                region_name=current_app.config.get('AWS_S3_REGION', 'ap-south-1'),
            )
            s3.delete_object(
                Bucket=current_app.config['AWS_S3_BUCKET'],
                Key=file_path,
            )
            return True
        except Exception as e:
            logger.error(f'S3 delete failed: {e}')
            return False
    else:
        upload_base = current_app.config['UPLOAD_FOLDER']
        abs_path = os.path.abspath(file_path)
        abs_base = os.path.abspath(upload_base)
        if not abs_path.startswith(abs_base):
            logger.error(f'Path traversal attempt: {file_path}')
            return False
        try:
            if os.path.exists(abs_path):
                os.remove(abs_path)
                return True
        except OSError as e:
            logger.error(f'File delete error: {e}')
        return False


def _get_extension(filename: str) -> str:
    if '.' not in filename:
        return ''
    return filename.rsplit('.', 1)[1].lower()


def _mime_for_ext(ext: str) -> str:
    return {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'doc': 'application/msword',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
    }.get(ext, 'application/octet-stream')
