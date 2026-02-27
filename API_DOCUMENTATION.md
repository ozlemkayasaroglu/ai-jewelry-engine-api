# 💎 Jewelry AI API - Frontend Integration Guide

## Base URL

```
https://ai-jewelry-engine-api-1.onrender.com
```

## API Endpoints

### 1. Health Check

```http
GET /health
```

**Response:**

```json
{
  "status": "healthy",
  "gemini_configured": true
}
```

---

### 2. Upload Jewelry Image

```http
POST /api/upload
Content-Type: multipart/form-data
```

**Request:**

```javascript
const formData = new FormData();
formData.append("file", fileInput.files[0]);

const response = await fetch(
  "https://ai-jewelry-engine-api-1.onrender.com/api/upload",
  {
    method: "POST",
    body: formData,
  },
);

const data = await response.json();
```

**Response:**

```json
{
  "success": true,
  "product_id": "20240227_120000",
  "metadata": {
    "product_id": "20240227_120000",
    "filename": "ring.jpg",
    "size": {
      "width": 2048,
      "height": 2048
    },
    "format": "JPEG",
    "hash": "abc123...",
    "uploaded_at": "2024-02-27T12:00:00"
  }
}
```

**Validation:**

- Minimum resolution: 1024x1024
- Accepted formats: PNG, JPEG
- Returns 400 if validation fails

---

### 3. Generate AI Prompt

```http
POST /api/generate/prompt?product_id={id}&style={model|studio}
```

**Parameters:**

- `product_id` (required): Product ID from upload response
- `style` (required): "model" or "studio"

**Request:**

```javascript
const response = await fetch(
  "https://ai-jewelry-engine-api-1.onrender.com/api/generate/prompt?product_id=20240227_120000&style=model",
  { method: "POST" },
);

const data = await response.json();
```

**Response (style=model):**

```json
{
  "success": true,
  "product_id": "20240227_120000",
  "style": "model",
  "prompt": {
    "lighting": "luxury soft top light with subtle fill from 45 degrees",
    "model_description": "elegant female model, natural pose, confident expression",
    "background": "minimal luxury environment, soft neutral tones",
    "camera": "85mm portrait lens, f/2.8, professional studio setup",
    "integrity_rules": [
      "no metal tone shift",
      "no stone color modification",
      "preserve exact jewelry dimensions",
      "maintain original gemstone count"
    ]
  }
}
```

**Response (style=studio):**

```json
{
  "success": true,
  "product_id": "20240227_120000",
  "style": "studio",
  "prompt": {
    "lighting": "pure white background with soft diffused lighting",
    "angles": ["front", "45_degree", "side", "macro"],
    "shadow_softness": 0.3,
    "background": "#FFFFFF",
    "camera_settings": "macro lens, f/11, professional product photography"
  }
}
```

---

### 4. Get Product Info

```http
GET /api/products/{product_id}
```

**Request:**

```javascript
const response = await fetch(
  "https://ai-jewelry-engine-api-1.onrender.com/api/products/20240227_120000",
);

const data = await response.json();
```

**Response:**

```json
{
  "metadata": {
    "product_id": "20240227_120000",
    "filename": "ring.jpg",
    "size": { "width": 2048, "height": 2048 },
    "hash": "abc123...",
    "uploaded_at": "2024-02-27T12:00:00"
  },
  "prompts": {
    "model": {
      /* generated prompt */
    },
    "studio": {
      /* generated prompt */
    }
  }
}
```

---

### 5. Get Product Image

```http
GET /api/products/{product_id}/image
```

**Usage:**

```html
<img
  src="https://ai-jewelry-engine-api-1.onrender.com/api/products/20240227_120000/image"
/>
```

**Response:**

- Returns the original uploaded image
- Content-Type: image/png or image/jpeg

---

### 6. Export Product as ZIP

```http
GET /api/export/{product_id}
```

**Request:**

```javascript
const response = await fetch(
  "https://ai-jewelry-engine-api-1.onrender.com/api/export/20240227_120000",
);

const blob = await response.blob();
const url = window.URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
a.download = `product_${product_id}.zip`;
a.click();
```

**ZIP Contents:**

```
product_id/
├── metadata.json
├── original.jpg
├── prompt_model.json
└── prompt_studio.json
```

---

### 7. Delete Product

```http
DELETE /api/products/{product_id}
```

**Request:**

```javascript
const response = await fetch(
  "https://ai-jewelry-engine-api-1.onrender.com/api/products/20240227_120000",
  { method: "DELETE" },
);

const data = await response.json();
```

**Response:**

```json
{
  "success": true,
  "deleted_files": [
    "uploads/20240227_120000.json",
    "uploads/20240227_120000.jpg",
    "outputs/20240227_120000_prompt_model.json",
    "outputs/20240227_120000_prompt_studio.json"
  ]
}
```

---

## Complete Frontend Example (React)

```jsx
import { useState } from "react";

const API_URL = "https://ai-jewelry-engine-api-1.onrender.com";

function JewelryUploader() {
  const [file, setFile] = useState(null);
  const [productId, setProductId] = useState("");
  const [prompt, setPrompt] = useState(null);
  const [loading, setLoading] = useState(false);

  // 1. Upload Image
  const handleUpload = async () => {
    if (!file) return;

    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_URL}/api/upload`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (data.success) {
        setProductId(data.product_id);
        alert("Upload successful!");
      }
    } catch (error) {
      alert("Upload failed: " + error.message);
    } finally {
      setLoading(false);
    }
  };

  // 2. Generate Prompt
  const handleGeneratePrompt = async (style) => {
    if (!productId) return;

    setLoading(true);
    try {
      const response = await fetch(
        `${API_URL}/api/generate/prompt?product_id=${productId}&style=${style}`,
        { method: "POST" },
      );

      const data = await response.json();

      if (data.success) {
        setPrompt(data.prompt);
        alert("Prompt generated!");
      }
    } catch (error) {
      alert("Generation failed: " + error.message);
    } finally {
      setLoading(false);
    }
  };

  // 3. Export ZIP
  const handleExport = async () => {
    if (!productId) return;

    try {
      const response = await fetch(`${API_URL}/api/export/${productId}`);
      const blob = await response.blob();

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${productId}.zip`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      alert("Export failed: " + error.message);
    }
  };

  return (
    <div>
      <h1>Jewelry AI Visualizer</h1>

      {/* Upload */}
      <div>
        <input
          type="file"
          accept="image/png,image/jpeg"
          onChange={(e) => setFile(e.target.files[0])}
        />
        <button onClick={handleUpload} disabled={!file || loading}>
          {loading ? "Uploading..." : "Upload"}
        </button>
      </div>

      {/* Generate Prompt */}
      {productId && (
        <div>
          <p>Product ID: {productId}</p>
          <button
            onClick={() => handleGeneratePrompt("model")}
            disabled={loading}
          >
            Generate Model Prompt
          </button>
          <button
            onClick={() => handleGeneratePrompt("studio")}
            disabled={loading}
          >
            Generate Studio Prompt
          </button>
        </div>
      )}

      {/* Display Prompt */}
      {prompt && (
        <div>
          <h2>Generated Prompt</h2>
          <pre>{JSON.stringify(prompt, null, 2)}</pre>
        </div>
      )}

      {/* Export */}
      {productId && <button onClick={handleExport}>Export as ZIP</button>}

      {/* Display Image */}
      {productId && (
        <img
          src={`${API_URL}/api/products/${productId}/image`}
          alt="Jewelry"
          style={{ maxWidth: "400px" }}
        />
      )}
    </div>
  );
}

export default JewelryUploader;
```

---

## Error Handling

All endpoints return standard error responses:

```json
{
  "detail": "Error message here"
}
```

**Common HTTP Status Codes:**

- `200` - Success
- `400` - Bad Request (validation error)
- `404` - Not Found (product doesn't exist)
- `500` - Server Error

**Example Error Handling:**

```javascript
try {
  const response = await fetch(API_URL + "/api/upload", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Upload failed");
  }

  const data = await response.json();
  // Handle success
} catch (error) {
  console.error("Error:", error.message);
  alert(error.message);
}
```

---

## CORS

CORS is enabled for all origins. You can call the API from any domain.

---

## Rate Limiting

Currently no rate limiting. Use responsibly.

---

## Interactive API Documentation

Visit the interactive Swagger UI:

```
https://ai-jewelry-engine-api-1.onrender.com/docs
```

You can test all endpoints directly from the browser!

---

## Notes

1. **First Request Delay**: Render free tier sleeps after 15 minutes of inactivity. First request may take 30-60 seconds.

2. **File Size**: No explicit limit, but keep images under 10MB for best performance.

3. **Storage**: Files are stored temporarily. Consider implementing cleanup for production.

4. **Gemini API**: Prompt generation uses Gemini 2.0 Flash. Response time: 2-5 seconds.

---

## Support

For issues or questions, check the API logs or contact the backend team.
