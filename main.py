from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
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
import tempfile
from firebase_config import initialize_firebase, upload_to_firebase, get_firebase_url

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
    
    # Primary model for prompt generation
    model = genai.GenerativeModel(
        'gemini-2.5-flash',  # Latest stable model
        generation_config=genai.GenerationConfig(
            temperature=0.2,  # Low temperature for stable, consistent results
        )
    )
    
    # Nano Banana for lightweight validation/QA
    try:
        nano_model = genai.GenerativeModel(
            'nano-banana-pro-preview',
            generation_config=genai.GenerationConfig(
                temperature=0.1,  # Very low for consistency
            )
        )
        NANO_ENABLED = True
        print("✅ Nano Banana model initialized")
    except:
        NANO_ENABLED = False
        print("⚠️  Nano Banana not available")
    
    # Image generation model
    try:
        imagen_model = genai.GenerativeModel(
            'gemini-2.0-flash-exp-image-generation'
        )
        IMAGEN_ENABLED = True
        print("✅ Imagen model initialized")
    except:
        IMAGEN_ENABLED = False
        print("⚠️  Imagen not available")

# Directories (local temp storage)
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Initialize Firebase
try:
    firebase_bucket = initialize_firebase()
    FIREBASE_ENABLED = True
    print("✅ Firebase Storage initialized")
except Exception as e:
    FIREBASE_ENABLED = False
    print(f"⚠️  Firebase not configured: {e}")
ALLOWED_CONTENT_TYPES = {"image/png": "png", "image/jpeg": "jpg"}

def calculate_hash(file_path: Path) -> str:
    """Calculate SHA-256 hash of file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def resolve_image_path(product_id: str) -> Path | None:
    """Resolve the stored image path for a product_id (supports legacy files)."""
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if metadata_path.exists():
        try:
            with open(metadata_path) as f:
                metadata = json.load(f)
        except Exception:
            metadata = {}

        stored_filename = metadata.get("stored_filename")
        if stored_filename:
            candidate = UPLOAD_DIR / stored_filename
            if candidate.exists():
                return candidate

        image_extension = metadata.get("image_extension")
        if image_extension:
            candidate = UPLOAD_DIR / f"{product_id}.{str(image_extension).lower()}"
            if candidate.exists():
                return candidate

    # Common extensions fallback (legacy behavior)
    for ext in ["png", "jpg", "jpeg", "PNG", "JPG", "JPEG"]:
        candidate = UPLOAD_DIR / f"{product_id}.{ext}"
        if candidate.exists():
            return candidate

    # Last-resort fallback for unexpected extensions
    for candidate in sorted(UPLOAD_DIR.glob(f"{product_id}.*")):
        if candidate.is_file() and candidate.suffix.lower() != ".json":
            return candidate

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
    product_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    file_path = None

    try:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(400, "Only PNG and JPEG files allowed")

        # Normalize extension by MIME type instead of client filename
        file_ext = ALLOWED_CONTENT_TYPES[file.content_type]
        file_path = UPLOAD_DIR / f"{product_id}.{file_ext}"

        content = await file.read()
        if not content:
            raise HTTPException(400, "Empty file uploaded")

        # Validate image from memory first, before persisting anything
        try:
            img = Image.open(io.BytesIO(content))
            img.verify()
            img = Image.open(io.BytesIO(content))
            width, height = img.size
            image_format = img.format
        except Exception:
            raise HTTPException(400, "Invalid image file")

        if width < 1024 or height < 1024:
            raise HTTPException(400, f"Image too small: {width}x{height}. Minimum 1024x1024")

        # Persist image
        with open(file_path, "wb") as f:
            f.write(content)

        if not file_path.exists() or file_path.stat().st_size == 0:
            raise HTTPException(500, "Failed to store uploaded image")

        # Save metadata only after image is confirmed persisted
        file_hash = calculate_hash(file_path)
        metadata = {
            "product_id": product_id,
            "filename": file.filename,
            "stored_filename": file_path.name,
            "image_extension": file_ext,
            "content_type": file.content_type,
            "size": {"width": width, "height": height},
            "format": image_format,
            "hash": file_hash,
            "uploaded_at": datetime.now().isoformat()
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return {
            "success": True,
            "product_id": product_id,
            "metadata": metadata
        }

    except HTTPException:
        # Keep upload atomic: no metadata without image, no partial image on failure
        if metadata_path.exists():
            os.remove(metadata_path)
        if file_path and file_path.exists():
            os.remove(file_path)
        raise
    except Exception as e:
        if metadata_path.exists():
            os.remove(metadata_path)
        if file_path and file_path.exists():
            os.remove(file_path)
        raise HTTPException(500, str(e))

@app.post("/api/generate/image")
async def generate_image(
    product_id: str,
    style: str = "model",  # model or studio
    category: str = "bracelet",  # bracelet, ring, necklace, earring
    skin_tone: str = "medium",  # light, medium, dark
    gender: str = "female"  # female, male
):
    """
    Generate jewelry visualization image using Gemini Imagen
    
    - style: "model" (on mannequin) or "studio" (white background)
    - category: jewelry type
    - skin_tone: light, medium, dark
    - gender: female, male
    """
    try:
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY not configured")
        
        # Load original jewelry image
        file_path = None
        for ext in ["png", "jpg", "jpeg"]:
            path = UPLOAD_DIR / f"{product_id}.{ext}"
            if path.exists():
                file_path = path
                break
        
        if not file_path:
            raise HTTPException(404, "Product image not found")
        
        img = Image.open(file_path)
        
        # Build prompt based on parameters
        if style == "model":
            # Model visualization (face hidden)
            base_prompt = f"""Professional jewelry photography: {category} worn on {gender} model.

CRITICAL RULES:
- Keep the jewelry EXACTLY as shown in the reference image
- Do NOT modify design, size, gold tone, stones, or structure
- Model's face is NOT visible (cropped or turned away)
- Focus on {category} placement on body
- {skin_tone.capitalize()} skin tone
- Natural, elegant pose
- Soft studio lighting
- Clean background
- High-end fashion editorial style"""

        else:  # studio
            # Studio product photography
            base_prompt = f"""Professional studio product photography of {category}.

CRITICAL RULES:
- Keep the jewelry EXACTLY as shown in the reference image
- Pure white background (#FFFFFF)
- Remove ALL tags, labels, strings, stands
- Professional lighting with soft shadow
- Centered composition
- Ultra sharp focus
- High-end e-commerce quality
- No modifications to jewelry design"""
        
        # Generate image using Gemini Imagen
        try:
            # Note: Gemini Imagen API might need different endpoint
            # This is a placeholder - actual implementation depends on available API
            response = model.generate_content([
                base_prompt,
                img,
                "Generate a photorealistic image following these exact specifications."
            ])
            
            # For now, return the prompt (actual image generation needs Imagen API)
            return {
                "success": True,
                "product_id": product_id,
                "style": style,
                "category": category,
                "skin_tone": skin_tone,
                "gender": gender,
                "prompt": base_prompt,
                "note": "Image generation requires Imagen API integration",
                "generated_image_url": None  # Will be populated when Imagen is integrated
            }
            
        except Exception as e:
            raise HTTPException(500, f"Image generation failed: {str(e)}")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
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
        file_path = resolve_image_path(product_id)
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
- If any tag or label is blurry/foggy/partially visible, remove it completely as well.
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
        
        # Optional: Validate with Nano Banana
        if NANO_ENABLED and isinstance(prompt_data, dict) and "error" not in prompt_data:
            try:
                validation_prompt = f"""Review this jewelry visualization prompt for accuracy and completeness:
{json.dumps(prompt_data, indent=2)}

Check:
1. Are all required fields present?
2. Do the instructions preserve jewelry integrity?
3. Is the lighting description professional?

Respond with: "APPROVED" or "NEEDS_REVISION: [reason]"
"""
                validation = nano_model.generate_content(validation_prompt)
                prompt_data["nano_validation"] = validation.text.strip()
            except:
                pass  # Validation is optional
        
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
    file_path = resolve_image_path(product_id)
    if file_path:
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
        img_path = resolve_image_path(product_id)
        if img_path:
            zip_file.write(img_path, f"{product_id}/original{img_path.suffix.lower()}")
        
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
