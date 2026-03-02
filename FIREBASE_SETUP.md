# 🔥 Firebase Storage Setup

## 1. Firebase Console Setup

1. [Firebase Console](https://console.firebase.google.com/) → Select/Create Project
2. Build → Storage → Get Started
3. Start in **production mode** (or test mode for development)
4. Choose location (e.g., `us-central1`)

## 2. Get Service Account Key

1. Project Settings (⚙️) → Service Accounts
2. "Generate New Private Key"
3. Download JSON file
4. Rename to `firebase-service-account.json`
5. **DO NOT commit this file to Git!** (already in .gitignore)

## 3. Local Development

```bash
# Add to .env
FIREBASE_STORAGE_BUCKET=your-project.appspot.com

# Place service account file
cp ~/Downloads/your-project-*.json firebase-service-account.json

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn main:app --reload
```

## 4. Render Deployment

### Option A: Environment Variable (Recommended)

1. Copy entire content of `firebase-service-account.json`
2. Render Dashboard → Environment
3. Add variable:
   - Key: `FIREBASE_SERVICE_ACCOUNT`
   - Value: Paste entire JSON content
4. Add:
   - Key: `FIREBASE_STORAGE_BUCKET`
   - Value: `your-project.appspot.com`

### Option B: Secret File

1. Render Dashboard → Secret Files
2. Add file:
   - Filename: `firebase-service-account.json`
   - Contents: Paste JSON content

## 5. Storage Rules (Optional)

Firebase Console → Storage → Rules:

```
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    match /uploads/{allPaths=**} {
      allow read: if true;  // Public read
      allow write: if false;  // Only server can write
    }
  }
}
```

## 6. Test

```bash
# Test upload
curl -X POST http://localhost:8000/api/upload \
  -F "file=@jewelry.jpg"

# Test image retrieval
curl http://localhost:8000/api/products/{product_id}/image
```

## 7. Verify

Firebase Console → Storage → Files

You should see uploaded files in `uploads/` folder.

## Troubleshooting

### "Default credentials not found"

- Make sure `firebase-service-account.json` exists
- Or set `FIREBASE_SERVICE_ACCOUNT` environment variable

### "Permission denied"

- Check Storage Rules
- Verify service account has Storage Admin role

### "Bucket not found"

- Verify `FIREBASE_STORAGE_BUCKET` is correct
- Format: `project-id.appspot.com`
