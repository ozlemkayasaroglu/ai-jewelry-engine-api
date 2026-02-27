# 💎 Jewelry AI API

REST API for AI-powered jewelry visualization using Gemini 2.0 Flash

## 🚀 Deployment (Ücretsiz Platformlar)

### Render (ÖNERİLEN)

1. [Render Dashboard](https://dashboard.render.com/) → "New Web Service"
2. GitHub repo'nu bağla
3. Environment Variables → `GEMINI_API_KEY` ekle
4. Deploy!

**Detaylı deployment guide**: [DEPLOYMENT.md](DEPLOYMENT.md)

### Diğer Platformlar

- **Fly.io**: `fly launch` (CLI gerekli)
- **Google Cloud Run**: `gcloud run deploy`
- **Vercel**: `vercel` (serverless, sınırlı)

Tüm platformlar için config dosyaları hazır:

- `render.yaml` - Render
- `fly.toml` - Fly.io
- `app.yaml` - Google Cloud Run
- `vercel.json` - Vercel
- `railway.json` - Railway

## 🔧 Local Development

### Docker ile (Önerilen)

```bash
# .env dosyası oluştur
cp .env.example .env
# GEMINI_API_KEY'i ekle

# Başlat
docker-compose up --build

# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### Manuel

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

export GEMINI_API_KEY=your_key_here
uvicorn main:app --reload
```

## 📡 API Endpoints

### 1. Upload Jewelry Image

```bash
POST /api/upload
Content-Type: multipart/form-data

curl -X POST http://localhost:8000/api/upload \
  -F "file=@jewelry.jpg"
```

Response:

```json
{
  "success": true,
  "product_id": "20240227_120000",
  "metadata": {
    "filename": "jewelry.jpg",
    "size": { "width": 2048, "height": 2048 },
    "hash": "abc123..."
  }
}
```

### 2. Generate AI Prompt

```bash
POST /api/generate/prompt?product_id={id}&style={model|studio}

curl -X POST "http://localhost:8000/api/generate/prompt?product_id=20240227_120000&style=model"
```

Response:

```json
{
  "success": true,
  "product_id": "20240227_120000",
  "style": "model",
  "prompt": {
    "lighting": "luxury soft top light...",
    "model_description": "elegant pose...",
    "background": "minimal luxury...",
    "camera": "85mm portrait lens...",
    "integrity_rules": ["no metal tone shift", "..."]
  }
}
```

### 3. Get Product Info

```bash
GET /api/products/{product_id}

curl http://localhost:8000/api/products/20240227_120000
```

### 4. Get Product Image

```bash
GET /api/products/{product_id}/image

curl http://localhost:8000/api/products/20240227_120000/image --output jewelry.jpg
```

### 5. Export as ZIP

```bash
GET /api/export/{product_id}

curl http://localhost:8000/api/export/20240227_120000 --output product.zip
```

### 6. Delete Product

```bash
DELETE /api/products/{product_id}

curl -X DELETE http://localhost:8000/api/products/20240227_120000
```

## 📚 Interactive Documentation

API çalıştıktan sonra:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## ✨ Features

- ✅ Jewelry image upload & validation (min 1024x1024)
- ✅ Gemini 2.0 Flash AI prompt generation
- ✅ Two modes: Model visualization & Studio photography
- ✅ Product metadata management
- ✅ ZIP export (image + metadata + prompts)
- ✅ Image integrity (SHA-256 hash)
- ✅ CORS enabled
- ✅ Railway ready
- ✅ Docker support

## 🛠 Tech Stack

- **FastAPI** - Modern Python web framework
- **Gemini 2.0 Flash** - Google's multimodal AI
- **Pillow** - Image processing
- **Redis** - Optional queue management
- **Docker** - Containerization

## 🔑 Getting Gemini API Key

1. [Google AI Studio](https://makersuite.google.com/app/apikey)
2. "Create API Key" butonuna tıkla
3. Key'i kopyala ve `.env` dosyasına ekle

## 📝 Example Usage

```python
import requests

# Upload
files = {'file': open('jewelry.jpg', 'rb')}
response = requests.post('http://localhost:8000/api/upload', files=files)
product_id = response.json()['product_id']

# Generate prompt
response = requests.post(
    f'http://localhost:8000/api/generate/prompt',
    params={'product_id': product_id, 'style': 'model'}
)
prompt = response.json()['prompt']
print(prompt)
```

## 🐛 Troubleshooting

### Gemini API Error

- API key'in doğru olduğundan emin ol
- [Google AI Studio](https://makersuite.google.com/app/apikey) üzerinden key'i kontrol et

### Port Already in Use

```bash
docker-compose down
docker-compose up
```

### Permission Issues

```bash
mkdir -p uploads outputs
chmod 777 uploads outputs
```

## 📄 License

MIT
