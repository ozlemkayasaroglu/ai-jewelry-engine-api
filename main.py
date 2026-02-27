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
    description="AI-powered jewelry visualization API using Gemini 2.0 Flash",
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
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY not set!")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        'gemini-2.5-flash-image',
        generation_config=genai.GenerationConfig(
            temperature=0.2,  # Low temperature for stable, consistent results
        )
    )

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

@app.get("/")
async def root():
    return {
        "status": "Jewelry AI API Running",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "upload": "POST /api/upload",
            "generate_prompt": "POST /api/generate/prompt",
            "get_product": "GET /api/products/{product_id}",
            "get_image": "GET /api/products/{product_id}/image",
            "export": "GET /api/export/{product_id}"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "gemini_configured": bool(GEMINI_API_KEY)}

@app.get("/test-gemini")
async def test_gemini():
    """Test Gemini API connection"""
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY not configured")
    
    try:
        response = model.generate_content("Say hello in one word")
        return {
            "success": True,
            "model": "gemini-2.5-flash-image",
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
    """
    Upload and validate jewelry image
    
    - Accepts PNG/JPEG
    - Minimum resolution: 1024x1024
    - Returns product_id and metadata
    """
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
    """
    Generate AI prompt using Gemini 2.0 Flash
    
    - style: "model" (jewelry on model) or "studio" (white background)
    - Returns structured JSON prompt for image generation
    """
    try:
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY not configured")
        
        # Load image
        file_path = None
        for ext in ["png", "jpg", "jpeg"]:
            path = UPLOAD_DIR / f"{product_id}.{ext}"
            if path.exists():
                file_path = path
                break
        
        if not file_path:
            raise HTTPException(404, "Product image not found")
        
        img = Image.open(file_path)
        
        # Gemini prompt based on style
        if style == "model":
            prompt = """You are a luxury jewelry visualization engine.

Task: Place the uploaded jewelry naturally on a professional female model.

STRICT RULES:
- Keep the jewelry EXACTLY the same.
- Do NOT modify its design, size, gold tone, stones, or structure.
- Jewelry must look physically worn and realistic.
- Correct scale and natural placement.
- Realistic skin contact and shadows.

MODEL:
- Elegant female model
- Natural makeup
- Soft studio lighting
- Luxury fashion photography style

OUTPUT:
- High-end fashion editorial look
- Focus on jewelry
- Clean soft background
- Professional magazine-quality lighting

Generate a JSON response with:
- lighting: describe luxury lighting setup (string)
- model_description: ethnicity, pose, expression (string)
- background: environment description (string)
- camera: angle and lens details (string)
- integrity_rules: list of rules to preserve jewelry exactly (array of strings)

Return ONLY valid JSON, no markdown formatting."""
        
        elif style == "studio":
            prompt = """You are a professional luxury jewelry retouching AI.

Task: Transform the uploaded jewelry image into a high-end e-commerce studio product photo.

STRICT RULES:
- Keep the jewelry EXACTLY as it is.
- Do NOT redesign, reshape, resize, or modify the product.
- Preserve original gold color, diamond brilliance, reflections, texture, thickness, and proportions.
- Do NOT alter clasp, stones, engravings, or structure.
- Remove background completely.
- Remove tags, strings, labels, stands, mannequins, hands, or any visible support objects.
- Do not leave any trace, shadow, blur, hole, or artifact from removed elements.

OUTPUT REQUIREMENTS:
- Pure white luxury studio background (#FFFFFF).
- Soft, natural shadow directly under the jewelry for realism.
- Centered composition.
- High-end commercial lighting.
- Sharp focus, ultra detailed.
- Looks like shot in a professional jewelry photography studio.

Generate JSON with:
- lighting: pure white background lighting description (string)
- angles: list of angles needed like ["front", "45_degree", "side", "macro"] (array)
- shadow_softness: value between 0-1 (number)
- background: must be pure white #FFFFFF (string)
- camera_settings: professional studio camera setup (string)
- integrity_rules: list of rules to preserve jewelry exactly (array of strings)

Return ONLY valid JSON, no markdown formatting."""
        
        else:
            raise HTTPException(400, "Invalid style. Use 'model' or 'studio'")
        
        # Call Gemini
        response = model.generate_content([prompt, img])
        
        # Parse response
        text = response.text.strip()
        
        # Clean markdown formatting if present
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
            # If JSON parsing fails, return raw text
            prompt_data = {"raw_response": text, "error": "Failed to parse as JSON"}
        
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

@app.get("/api/products/{product_id}")
async def get_product(product_id: str):
    """Get product metadata"""
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if not metadata_path.exists():
        raise HTTPException(404, "Product not found")
    
    with open(metadata_path) as f:
        metadata = json.load(f)
    
    # Check for generated prompts
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
    for ext in ["png", "jpg", "jpeg"]:
        file_path = UPLOAD_DIR / f"{product_id}.{ext}"
        if file_path.exists():
            return FileResponse(file_path)
    
    raise HTTPException(404, "Image not found")

@app.get("/api/export/{product_id}")
async def export_product(product_id: str):
    """
    Export product as ZIP file
    
    Includes:
    - Original image
    - Metadata JSON
    - All generated prompts
    """
    # Check if product exists
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if not metadata_path.exists():
        raise HTTPException(404, "Product not found")
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add metadata
        zip_file.write(metadata_path, f"{product_id}/metadata.json")
        
        # Add original image
        for ext in ["png", "jpg", "jpeg"]:
            img_path = UPLOAD_DIR / f"{product_id}.{ext}"
            if img_path.exists():
                zip_file.write(img_path, f"{product_id}/original.{ext}")
                break
        
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
    """Delete product and all associated files"""
    deleted_files = []
    
    # Delete metadata
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if metadata_path.exists():
        os.remove(metadata_path)
        deleted_files.append(str(metadata_path))
    
    # Delete image
    for ext in ["png", "jpg", "jpeg"]:
        img_path = UPLOAD_DIR / f"{product_id}.{ext}"
        if img_path.exists():
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
