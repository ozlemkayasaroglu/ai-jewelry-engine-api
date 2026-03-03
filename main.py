from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import google.generativeai as genai
from PIL import Image
import os
from pathlib import Path
import hashlib
import json
from datetime import datetime
from dotenv import load_dotenv
import io
import zipfile

load_dotenv()

app = FastAPI(
    title="Jewelry AI API",
    description="AI-powered jewelry visualization API using Gemini",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini setup
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NANO_ENABLED = False
IMAGEN_ENABLED = False

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY not set!")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Primary model for prompt generation
    try:
        model = genai.GenerativeModel(
            'gemini-2.0-flash-exp',
            generation_config=genai.GenerationConfig(
                temperature=0.2,
            )
        )
        print("✅ Gemini model initialized")
    except Exception as e:
        print(f"⚠️ Gemini model error: {e}")
    
    # Nano Banana for validation
    try:
        nano_model = genai.GenerativeModel('gemini-nano')
        NANO_ENABLED = True
        print("✅ Nano model initialized")
    except:
        print("⚠️ Nano model not available")
    
    # Image generation model
    try:
        imagen_model = genai.GenerativeModel('imagen-3.0-generate-001')
        IMAGEN_ENABLED = True
        print("✅ Imagen model initialized")
    except:
        print("⚠️ Imagen model not available")

# Directories
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

def calculate_hash(file_path: Path) -> str:
    """Calculate SHA-256 hash of file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def resolve_image_path(product_id: str):
    """Find product image file"""
    for ext in ["png", "jpg", "jpeg"]:
        path = UPLOAD_DIR / f"{product_id}.{ext}"
        if path.exists():
            return path
    return None

@app.get("/")
async def root():
    return {
        "status": "Jewelry AI API Running",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "upload": "POST /api/upload",
            "generate_prompt": "POST /api/generate/prompt",
            "generate_image": "POST /api/generate/image",
            "get_product": "GET /api/products/{product_id}",
            "get_image": "GET /api/products/{product_id}/image",
            "export": "GET /api/export/{product_id}"
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "gemini_configured": bool(GEMINI_API_KEY),
        "nano_enabled": NANO_ENABLED,
        "imagen_enabled": IMAGEN_ENABLED
    }

@app.get("/test-gemini")
async def test_gemini():
    """Test Gemini API connection"""
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY not configured")
    
    try:
        response = model.generate_content("Say hello in one word")
        return {
            "success": True,
            "model": "gemini-2.0-flash-exp",
            "response": response.text,
            "message": "Gemini API is working!"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Gemini API failed"
        }

@app.post("/api/upload")
async def upload_jewelry(file: UploadFile = File(...)):
    """Upload and validate jewelry image"""
    try:
        if not file.content_type in ["image/png", "image/jpeg"]:
            raise HTTPException(400, "Only PNG and JPEG files allowed")
        
        # Generate product ID
        product_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_ext = file.filename.split(".")[-1]
        file_path = UPLOAD_DIR / f"{product_id}.{file_ext}"
        
        # Save file
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Validate image
        img = Image.open(file_path)
        width, height = img.size
        
        if width < 1024 or height < 1024:
            os.remove(file_path)
            raise HTTPException(400, f"Image too small: {width}x{height}. Minimum 1024x1024")
        
        # Calculate hash
        file_hash = calculate_hash(file_path)
        
        # Save metadata
        metadata = {
            "product_id": product_id,
            "filename": file.filename,
            "size": {"width": width, "height": height},
            "format": img.format,
            "hash": file_hash,
            "uploaded_at": datetime.now().isoformat()
        }
        
        metadata_path = UPLOAD_DIR / f"{product_id}.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        return {
            "success": True,
            "product_id": product_id,
            "metadata": metadata
        }
    
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/generate/prompt")
async def generate_prompt(product_id: str, style: str = "model"):
    """Generate AI prompt using Gemini"""
    try:
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY not configured")
        
        # Load image
        file_path = resolve_image_path(product_id)
        if not file_path:
            raise HTTPException(404, "Product image not found")
        
        img = Image.open(file_path)
        
        # Gemini prompt based on style
        if style == "model":
            prompt = """You are a luxury jewelry visualization engine.

Task: Place the uploaded jewelry naturally on a professional female model.

STRICT RULES:
- Keep the jewelry EXACTLY the same
- Do NOT modify design, size, gold tone, stones, or structure
- Jewelry must look physically worn and realistic
- Model's FACE NOT VISIBLE (cropped or turned away)
- Natural elegant pose
- Soft studio lighting
- Clean soft background

Generate JSON with:
- lighting: luxury lighting setup (string)
- model_description: pose, body part visible (string)
- background: environment description (string)
- camera: angle and lens (string)
- integrity_rules: jewelry preservation rules (array)

Return ONLY valid JSON."""
        
        elif style == "studio":
            prompt = """You are a professional luxury jewelry retouching AI.

Task: Transform into high-end e-commerce studio photo.

STRICT RULES:
- Keep jewelry EXACTLY as it is
- Do NOT redesign, reshape, resize, or modify
- Preserve gold color, diamond brilliance, reflections
- Remove background completely
- Remove tags, strings, labels, stands, hands
- Pure white background (#FFFFFF)
- Soft shadow under jewelry
- Centered composition
- Ultra sharp focus

Generate JSON with:
- lighting: white background lighting (string)
- angles: needed angles (array)
- shadow_softness: 0-1 value (number)
- background: #FFFFFF (string)
- camera_settings: studio setup (string)
- integrity_rules: jewelry preservation rules (array)

Return ONLY valid JSON."""
        
        else:
            raise HTTPException(400, "Invalid style. Use 'model' or 'studio'")
        
        # Call Gemini
        response = model.generate_content([prompt, img])
        text = response.text.strip()
        
        # Clean markdown
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        try:
            prompt_data = json.loads(text)
        except json.JSONDecodeError:
            prompt_data = {"raw_response": text, "error": "Failed to parse JSON"}
        
        # Save prompt
        prompt_path = OUTPUT_DIR / f"{product_id}_prompt_{style}.json"
        with open(prompt_path, "w") as f:
            json.dump(prompt_data, f, indent=2)
        
        return {
            "success": True,
            "product_id": product_id,
            "style": style,
            "prompt": prompt_data
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/generate/image")
async def generate_image(
    product_id: str,
    style: str = "model",
    category: str = "bracelet",
    skin_tone: str = "medium",
    gender: str = "female"
):
    """Generate jewelry visualization image"""
    try:
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY not configured")
        
        if not IMAGEN_ENABLED:
            raise HTTPException(500, "Image generation not available")
        
        # Load original image
        file_path = resolve_image_path(product_id)
        if not file_path:
            raise HTTPException(404, "Product image not found")
        
        img = Image.open(file_path)
        
        # Build prompt
        if style == "model":
            prompt = f"""Professional jewelry photo: {category} on {gender} model, {skin_tone} skin.
- Keep jewelry EXACTLY as shown
- Face NOT visible
- Natural pose
- Soft lighting
- Clean background"""
        else:
            prompt = f"""Studio photo of {category}.
- Keep jewelry EXACTLY as shown
- White background
- Remove all tags/stands
- Centered, sharp focus"""
        
        # Generate with Imagen
        response = imagen_model.generate_content([prompt, img])
        
        # Save generated image
        generated_id = f"{product_id}_{style}_{datetime.now().strftime('%H%M%S')}"
        output_path = OUTPUT_DIR / f"{generated_id}.png"
        
        # Extract image
        if hasattr(response, 'parts'):
            for part in response.parts:
                if hasattr(part, 'inline_data'):
                    with open(output_path, 'wb') as f:
                        f.write(part.inline_data.data)
                    
                    return {
                        "success": True,
                        "product_id": product_id,
                        "generated_id": generated_id,
                        "style": style,
                        "image_url": f"/api/generated/{generated_id}/image"
                    }
        
        raise HTTPException(500, "No image generated")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/generated/{generated_id}/image")
async def get_generated_image(generated_id: str):
    """Get generated image"""
    file_path = OUTPUT_DIR / f"{generated_id}.png"
    if file_path.exists():
        return FileResponse(file_path)
    raise HTTPException(404, "Generated image not found")

@app.get("/api/products/{product_id}")
async def get_product(product_id: str):
    """Get product metadata"""
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if not metadata_path.exists():
        raise HTTPException(404, "Product not found")
    
    with open(metadata_path) as f:
        metadata = json.load(f)
    
    # Check for prompts
    prompts = {}
    for style in ["model", "studio"]:
        prompt_path = OUTPUT_DIR / f"{product_id}_prompt_{style}.json"
        if prompt_path.exists():
            with open(prompt_path) as f:
                prompts[style] = json.load(f)
    
    return {
        "metadata": metadata,
        "prompts": prompts
    }

@app.get("/api/products/{product_id}/image")
async def get_product_image(product_id: str):
    """Get product image"""
    file_path = resolve_image_path(product_id)
    if file_path:
        return FileResponse(file_path)
    raise HTTPException(404, "Image not found")

@app.get("/api/export/{product_id}")
async def export_product(product_id: str):
    """Export product as ZIP"""
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if not metadata_path.exists():
        raise HTTPException(404, "Product not found")
    
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add metadata
        zip_file.write(metadata_path, f"{product_id}/metadata.json")
        
        # Add image
        img_path = resolve_image_path(product_id)
        if img_path:
            zip_file.write(img_path, f"{product_id}/original{img_path.suffix}")
        
        # Add prompts
        for style in ["model", "studio"]:
            prompt_path = OUTPUT_DIR / f"{product_id}_prompt_{style}.json"
            if prompt_path.exists():
                zip_file.write(prompt_path, f"{product_id}/prompt_{style}.json")
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={product_id}.zip"}
    )

@app.delete("/api/products/{product_id}")
async def delete_product(product_id: str):
    """Delete product"""
    deleted_files = []
    
    # Delete metadata
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if metadata_path.exists():
        os.remove(metadata_path)
        deleted_files.append(str(metadata_path))
    
    # Delete image
    img_path = resolve_image_path(product_id)
    if img_path and img_path.exists():
        os.remove(img_path)
        deleted_files.append(str(img_path))
    
    # Delete prompts
    for style in ["model", "studio"]:
        prompt_path = OUTPUT_DIR / f"{product_id}_prompt_{style}.json"
        if prompt_path.exists():
            os.remove(prompt_path)
            deleted_files.append(str(prompt_path))
    
    if not deleted_files:
        raise HTTPException(404, "Product not found")
    
    return {
        "success": True,
        "deleted_files": deleted_files
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
