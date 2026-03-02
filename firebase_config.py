import firebase_admin
from firebase_admin import credentials, storage
import os
from pathlib import Path

def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    
    # Check if already initialized
    if firebase_admin._apps:
        return storage.bucket()
    
    # Try to load service account from file
    service_account_path = Path("firebase-service-account.json")
    
    if service_account_path.exists():
        cred = credentials.Certificate(str(service_account_path))
    else:
        # Use default credentials (for Cloud Run, etc.)
        cred = credentials.ApplicationDefault()
    
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET")
    
    firebase_admin.initialize_app(cred, {
        'storageBucket': bucket_name
    })
    
    return storage.bucket()

def upload_to_firebase(local_path: str, firebase_path: str) -> str:
    """
    Upload file to Firebase Storage
    
    Args:
        local_path: Local file path
        firebase_path: Path in Firebase Storage
    
    Returns:
        Public URL of uploaded file
    """
    bucket = initialize_firebase()
    blob = bucket.blob(firebase_path)
    blob.upload_from_filename(local_path)
    
    # Make public (optional)
    blob.make_public()
    
    return blob.public_url

def download_from_firebase(firebase_path: str, local_path: str):
    """
    Download file from Firebase Storage
    
    Args:
        firebase_path: Path in Firebase Storage
        local_path: Local destination path
    """
    bucket = initialize_firebase()
    blob = bucket.blob(firebase_path)
    blob.download_to_filename(local_path)

def delete_from_firebase(firebase_path: str):
    """Delete file from Firebase Storage"""
    bucket = initialize_firebase()
    blob = bucket.blob(firebase_path)
    blob.delete()

def get_firebase_url(firebase_path: str) -> str:
    """Get public URL for a file in Firebase Storage"""
    bucket = initialize_firebase()
    blob = bucket.blob(firebase_path)
    return blob.public_url
