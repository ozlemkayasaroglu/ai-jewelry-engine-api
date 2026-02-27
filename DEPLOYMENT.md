# 🚀 Deployment Guide - Ücretsiz Platformlar

## 1. Render (ÖNERİLEN - En Kolay)

### Avantajlar

- ✅ Tamamen ücretsiz tier
- ✅ Otomatik HTTPS
- ✅ GitHub entegrasyonu
- ✅ Persistent disk (1GB)
- ⚠️ 15 dakika inaktiviteden sonra uyur

### Deploy Adımları

1. [Render Dashboard](https://dashboard.render.com/) → "New" → "Web Service"
2. GitHub repo'nu bağla
3. Settings:
   - **Name**: jewelry-ai-api
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Environment Variables:
   - `GEMINI_API_KEY` = your_key
5. "Create Web Service"

**render.yaml** dosyası otomatik config için hazır.

---

## 2. Fly.io (En Güçlü)

### Avantajlar

- ✅ Ücretsiz tier (3 shared-cpu VM)
- ✅ Global deployment
- ✅ Auto-scale to zero
- ✅ Persistent volumes
- ⚠️ CLI gerekli

### Deploy Adımları

```bash
# Fly CLI kur
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Deploy
fly launch
# fly.toml otomatik kullanılacak

# Secret ekle
fly secrets set GEMINI_API_KEY=your_key_here

# Volume oluştur (opsiyonel)
fly volumes create uploads_data --size 1
fly volumes create outputs_data --size 1

# Deploy
fly deploy
```

**fly.toml** dosyası hazır.

---

## 3. Google Cloud Run (Serverless)

### Avantajlar

- ✅ Ücretsiz tier (2M requests/ay)
- ✅ Sadece kullandığın kadar öde
- ✅ Auto-scale
- ✅ Google altyapısı
- ⚠️ Cold start var

### Deploy Adımları

```bash
# Google Cloud SDK kur
# https://cloud.google.com/sdk/docs/install

# Login
gcloud auth login

# Project oluştur
gcloud projects create jewelry-ai-api

# Cloud Run'a deploy
gcloud run deploy jewelry-ai-api \
  --source . \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your_key_here

# Ya da app.yaml ile
gcloud app deploy
```

**app.yaml** dosyası hazır.

---

## 4. Vercel (Sınırlı)

### Avantajlar

- ✅ Ücretsiz tier
- ✅ Çok hızlı deploy
- ✅ GitHub entegrasyonu
- ⚠️ Serverless (10 sn timeout)
- ⚠️ File upload sınırlı

### Deploy Adımları

```bash
# Vercel CLI kur
npm i -g vercel

# Deploy
vercel

# Environment variable ekle
vercel env add GEMINI_API_KEY
```

**vercel.json** dosyası hazır.

⚠️ **Not**: Vercel serverless olduğu için file upload/storage sınırlı. Küçük testler için uygun.

---

## 5. Railway (Artık Ücretli ama Kolay)

### Avantajlar

- ✅ Çok kolay setup
- ✅ GitHub entegrasyonu
- ⚠️ $5 credit ile başlıyor (ücretsiz değil)

### Deploy Adımları

1. [Railway Dashboard](https://railway.app/) → "New Project"
2. "Deploy from GitHub repo"
3. Environment Variables → `GEMINI_API_KEY`
4. Otomatik deploy

**railway.json** dosyası hazır.

---

## Karşılaştırma Tablosu

| Platform      | Ücretsiz | Kolay  | Persistent Storage | Cold Start | Önerilen        |
| ------------- | -------- | ------ | ------------------ | ---------- | --------------- |
| **Render**    | ✅       | ⭐⭐⭐ | ✅ 1GB             | Var (15dk) | ✅ En İyi       |
| **Fly.io**    | ✅       | ⭐⭐   | ✅ Custom          | Yok        | ✅ Güçlü        |
| **Cloud Run** | ✅       | ⭐⭐   | ❌                 | Var        | Serverless için |
| **Vercel**    | ✅       | ⭐⭐⭐ | ❌                 | Var        | Test için       |
| **Railway**   | ❌       | ⭐⭐⭐ | ✅                 | Yok        | Ücretli         |

---

## Önerim

**Başlangıç için**: Render (en kolay, ücretsiz, storage var)

**Production için**: Fly.io (daha güçlü, global, auto-scale)

**Serverless tercih edersen**: Google Cloud Run

---

## Environment Variables (Hepsi için)

```bash
GEMINI_API_KEY=your_gemini_api_key_here
PORT=8000  # Otomatik set edilir genelde
```

---

## Test

Deploy sonrası:

```bash
# Health check
curl https://your-app.com/health

# Upload test
curl -X POST https://your-app.com/api/upload \
  -F "file=@test.jpg"

# API docs
https://your-app.com/docs
```

---

## Sorun Giderme

### Render'da uyuyor

- Ücretsiz tier 15 dakika sonra uyur
- İlk istek 30-60 saniye sürebilir

### Fly.io volume hatası

```bash
fly volumes list
fly volumes create uploads_data --size 1
```

### Cloud Run timeout

- Serverless 10 sn timeout var
- Büyük dosyalar için uygun değil

### Vercel file upload

- Vercel serverless, file storage sınırlı
- S3/Cloud Storage kullan
