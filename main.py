from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
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
from pydantic import BaseModel
from uuid import uuid4
import subprocess
import shutil
import threading

load_dotenv()

app = FastAPI(
    title="Jewelry AI API",
    description="AI-powered jewelry visualization API using Gemini",
    version="1.1.0"
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
        image_model_name = os.getenv("IMAGE_GENERATION_MODEL", "gemini-2.5-flash-image")
        imagen_model = genai.GenerativeModel(image_model_name)
        IMAGEN_ENABLED = True
        print(f"✅ Image model initialized: {image_model_name}")
    except Exception as e:
        print(f"⚠️ Image model not available: {e}")

# Directories
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_CATEGORIES = {"earrings", "necklace", "ring", "bracelet"}
ALLOWED_GENDERS = {"female", "male", "child", "unisex"}
ALLOWED_STYLES = {"model", "studio"}
ALLOWED_RENDER_PRESETS = {"thumbnail", "hero"}

CATEGORY_ALIASES = {
    "küpe": "earrings",
    "kupe": "earrings",
    "earring": "earrings",
    "earrings": "earrings",
    "kolye": "necklace",
    "necklace": "necklace",
    "yüzük": "ring",
    "yuzuk": "ring",
    "ring": "ring",
    "bileklik": "bracelet",
    "kelepçe": "bracelet",
    "kelepce": "bracelet",
    "bracelet": "bracelet",
    "bangle": "bracelet",
}

GENDER_ALIASES = {
    "kadın": "female",
    "kadin": "female",
    "female": "female",
    "woman": "female",
    "erkek": "male",
    "male": "male",
    "man": "male",
    "çocuk": "child",
    "cocuk": "child",
    "child": "child",
    "kid": "child",
    "unisex": "unisex",
    "neutral": "unisex",
}

CATEGORY_COMPOSITIONS = {
    "earrings": (
        "Extreme macro framing of the earlobe and soft jawline only. "
        "The rest of the face must stay completely out of frame."
    ),
    "necklace": (
        "Close-up macro framing on collarbone, neck, and shoulders. "
        "No facial features in frame."
    ),
    "ring": (
        "Macro framing on hand and fingers with natural, elegant anatomy. "
        "Fingers must look proportionate and realistic."
    ),
    "bracelet": (
        "Macro framing on wrist and forearm with natural posture. "
        "Only forearm/hand area visible, no face."
    ),
}

GENDER_GUIDANCE = {
    "female": "adult female model styling with elegant posture",
    "male": "adult male model styling with natural masculine proportions",
    "child": "child model styling, age-appropriate wardrobe, safe and non-revealing composition",
    "unisex": "modern neutral styling suitable for unisex luxury campaigns",
}

STYLE_ALIASES = {
    "model": "model",
    "luxury model": "model",
    "studio": "studio",
    "luxury studio": "studio",
}

JOBS = {}
JOBS_LOCK = threading.Lock()

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

def normalize_category(category: str) -> str:
    normalized = CATEGORY_ALIASES.get(category.strip().lower())
    if not normalized or normalized not in ALLOWED_CATEGORIES:
        raise HTTPException(
            400,
            "Invalid category. Use one of: earrings, necklace, ring, bracelet"
        )
    return normalized

def normalize_gender(gender: str) -> str:
    normalized = GENDER_ALIASES.get(gender.strip().lower())
    if not normalized or normalized not in ALLOWED_GENDERS:
        raise HTTPException(400, "Invalid gender. Use one of: female, male, child, unisex")
    return normalized

def normalize_style(style: str) -> str:
    normalized = STYLE_ALIASES.get(style.strip().lower())
    if not normalized or normalized not in ALLOWED_STYLES:
        raise HTTPException(400, "Invalid style. Use one of: model, studio")
    return normalized

def build_prompt(
    category: str,
    gender: str,
    style: str,
    skin_tone: str,
    stone_detail: str = ""
) -> str:
    category_map = {
        "bracelet": "high-end solid gold bracelet/bangle",
        "ring": "high-end solid gold ring",
        "earrings": "high-end solid gold earrings",
        "necklace": "high-end solid gold necklace",
    }
    gender_map = {
        "female": "elegant feminine styling",
        "male": "minimal masculine styling",
        "child": "age-appropriate child styling",
        "unisex": "modern neutral styling",
    }
    style_map = {
        "model": "luxury editorial macro on model",
        "studio": "luxury e-commerce studio product shot",
    }
    composition_line = CATEGORY_COMPOSITIONS[category] if style == "model" else (
        "Centered composition with crisp edges and soft grounded shadow."
    )
    face_line = (
        "Face strictly out of frame. Show only the relevant body area for wearing realism."
        if style == "model"
        else "No model body visible."
    )
    stone_line = (
        f"Stone details: {stone_detail}. Keep exact stone cut, color, and settings."
        if stone_detail.strip()
        else "Preserve all gemstone details exactly from source."
    )

    return f"""
Ultra realistic jewelry product photography.
Subject: {category_map[category]}.
Styling: {gender_map[gender]}.
Render mode: {style_map[style]}.
Skin tone direction: {skin_tone}.
Model guidance: {GENDER_GUIDANCE[gender]}.
Composition: {composition_line}
Framing rule: {face_line}

STRICT PRODUCT INTEGRITY:
- Keep jewelry 1:1 identical to source product image.
- No redesign, no distortion, no warped geometry, no missing elements.
- Accurate gold color tone, accurate gemstone sparkle, realistic metal reflections.
- Preserve prongs, links, clasps, stone count, dimensions, and engraving details.

VISUAL QUALITY:
- macro lens 100mm
- sharp focus
- natural luxury lighting
- bright but controlled highlights
- soft shadow
- no artificial glow
- white seamless background for studio style
- premium creamy bokeh for model style
- base generation must be optimized for 1024x1024 speed path

NEGATIVE PROMPT:
blurry, overexposed, fake gold, cartoonish, distorted shape, extra fingers,
anatomy errors, low resolution, plastic texture, noisy background, bad reflections

{stone_line}
""".strip()

class GenerateImageRequest(BaseModel):
    product_id: str
    category: str = "bracelet"
    gender: str = "female"
    style: str = "model"
    skin_tone: str = "medium"
    stone_detail: str = ""
    render_preset: str = "hero"

class GeneratePromptRequest(BaseModel):
    product_id: str
    category: str = "bracelet"
    gender: str = "female"
    style: str = "model"
    skin_tone: str = "medium"
    stone_detail: str = ""

def normalize_render_preset(render_preset: str) -> str:
    normalized = render_preset.strip().lower()
    if normalized not in ALLOWED_RENDER_PRESETS:
        raise HTTPException(400, "Invalid render_preset. Use one of: thumbnail, hero")
    return normalized

def select_image_model(render_preset: str):
    primary_model_name = os.getenv("IMAGE_GENERATION_MODEL", "gemini-2.5-flash-image")
    if render_preset == "thumbnail":
        thumbnail_model_name = os.getenv("THUMBNAIL_IMAGE_MODEL", primary_model_name)
        try:
            return genai.GenerativeModel(thumbnail_model_name), thumbnail_model_name
        except Exception:
            return imagen_model, primary_model_name
    return imagen_model, primary_model_name

def _inline_part_to_bytes(part):
    inline = getattr(part, "inline_data", None)
    if inline is None:
        return None
    data = getattr(inline, "data", None)
    if data:
        return data
    if isinstance(inline, dict) and inline.get("data"):
        return inline["data"]
    return None

def extract_inline_image_bytes(response):
    # Path 1: response.parts
    if hasattr(response, "parts") and response.parts:
        for part in response.parts:
            data = _inline_part_to_bytes(part)
            if data:
                return data

    # Path 2: response.candidates[*].content.parts
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            data = _inline_part_to_bytes(part)
            if data:
                return data

    # Path 3: dictionary-like fallback
    if isinstance(response, dict):
        for candidate in response.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                inline = part.get("inline_data") or part.get("inlineData")
                if inline and inline.get("data"):
                    return inline["data"]

    return None

def prepare_base_image_1024(source_path: Path) -> Image.Image:
    with Image.open(source_path) as img:
        src = img.convert("RGB")
        src.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1024, 1024), (255, 255, 255))
        offset = ((1024 - src.size[0]) // 2, (1024 - src.size[1]) // 2)
        canvas.paste(src, offset)
        return canvas

def upscale_with_pillow(source_path: Path, target_path: Path) -> dict:
    with Image.open(source_path) as img:
        img = img.convert("RGB")
        source_width, source_height = img.size
        scale = 3840 / max(source_width, source_height)
        resized = img.resize(
            (max(1, int(round(source_width * scale))), max(1, int(round(source_height * scale)))),
            Image.Resampling.LANCZOS
        )
        resized.save(target_path, format="PNG", optimize=True)
        return {
            "provider": "pillow",
            "source_width": source_width,
            "source_height": source_height,
            "target_width": resized.size[0],
            "target_height": resized.size[1]
        }

def upscale_with_realesrgan(source_path: Path, target_path: Path) -> dict:
    binary = os.getenv("REALESRGAN_BIN", "realesrgan-ncnn-vulkan")
    if shutil.which(binary) is None:
        raise RuntimeError(f"{binary} not found in PATH")

    tmp_target = target_path.with_name(f"{target_path.stem}_tmp{target_path.suffix}")
    command = [binary, "-i", str(source_path), "-o", str(tmp_target), "-s", "4"]
    subprocess.run(command, check=True, capture_output=True, text=True)

    with Image.open(tmp_target) as upscaled:
        upscaled = upscaled.convert("RGB")
        source = Image.open(source_path)
        source_width, source_height = source.size
        source.close()
        scale = 3840 / max(upscaled.size)
        resized = upscaled.resize(
            (max(1, int(round(upscaled.size[0] * scale))), max(1, int(round(upscaled.size[1] * scale)))),
            Image.Resampling.LANCZOS
        )
        resized.save(target_path, format="PNG", optimize=True)
        tmp_target.unlink(missing_ok=True)
        return {
            "provider": "realesrgan",
            "source_width": source_width,
            "source_height": source_height,
            "target_width": resized.size[0],
            "target_height": resized.size[1]
        }

def upscale_with_imagen(source_path: Path, target_path: Path) -> dict:
    if not IMAGEN_ENABLED:
        raise RuntimeError("Imagen not available for upscale")
    base_image = Image.open(source_path)
    response = imagen_model.generate_content([
        "Upscale this jewelry image to true 4K while preserving exact product integrity, metal texture, and gemstone details.",
        base_image
    ])
    base_image.close()
    image_bytes = extract_inline_image_bytes(response)
    if not image_bytes:
        raise RuntimeError("Imagen upscale returned no image")

    with open(target_path, "wb") as f:
        f.write(image_bytes)

    with Image.open(source_path) as src, Image.open(target_path) as out:
        source_width, source_height = src.size
        target_width, target_height = out.size
    return {
        "provider": "imagen",
        "source_width": source_width,
        "source_height": source_height,
        "target_width": target_width,
        "target_height": target_height
    }

def upscale_to_4k(source_path: Path, target_path: Path) -> dict:
    provider = os.getenv("UPSCALE_PROVIDER", "imagen").strip().lower()
    try:
        if provider == "realesrgan":
            return upscale_with_realesrgan(source_path, target_path)
        if provider == "imagen":
            return upscale_with_imagen(source_path, target_path)
        return upscale_with_pillow(source_path, target_path)
    except Exception as exc:
        fallback = upscale_with_pillow(source_path, target_path)
        fallback["fallback_reason"] = str(exc)
        return fallback

@app.get("/")
async def root():
    return {
        "status": "Jewelry AI API Running",
        "version": "1.1.0",
        "endpoints": {
            "docs": "/docs",
            "upload": "POST /api/upload",
            "generate_prompt": "POST /api/generate/prompt",
            "generate_image": "POST /api/generate/image",
            "status": "GET /api/status/{job_id}",
            "options": "GET /api/options",
            "get_product": "GET /api/products/{product_id}",
            "get_image": "GET /api/products/{product_id}/image",
            "export": "GET /api/export/{product_id}"
        }
    }

@app.get("/api/options")
async def get_options():
    return {
        "categories": sorted(ALLOWED_CATEGORIES),
        "genders": sorted(ALLOWED_GENDERS),
        "styles": sorted(ALLOWED_STYLES),
        "render_presets": sorted(ALLOWED_RENDER_PRESETS),
        "upscale_provider": os.getenv("UPSCALE_PROVIDER", "imagen")
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "gemini_configured": bool(GEMINI_API_KEY),
        "nano_enabled": NANO_ENABLED,
        "imagen_enabled": IMAGEN_ENABLED,
        "image_model": os.getenv("IMAGE_GENERATION_MODEL", "gemini-2.5-flash-image"),
        "upscale_provider": os.getenv("UPSCALE_PROVIDER", "imagen")
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
async def generate_prompt(payload: GeneratePromptRequest):
    """Generate backend-controlled image prompt template"""
    try:
        file_path = resolve_image_path(payload.product_id)
        if not file_path:
            raise HTTPException(404, "Product image not found")

        category = normalize_category(payload.category)
        gender = normalize_gender(payload.gender)
        style = normalize_style(payload.style)

        prompt_text = build_prompt(
            category=category,
            gender=gender,
            style=style,
            skin_tone=payload.skin_tone,
            stone_detail=payload.stone_detail
        )

        prompt_data = {
            "prompt_text": prompt_text,
            "style": style,
            "category": category,
            "gender": gender,
            "skin_tone": payload.skin_tone,
            "stone_detail": payload.stone_detail,
            "base_resolution": "1024x1024",
            "upscale_target": "4k"
        }

        prompt_path = OUTPUT_DIR / f"{payload.product_id}_prompt_{style}.json"
        with open(prompt_path, "w") as f:
            json.dump(prompt_data, f, indent=2)

        return {
            "success": True,
            "product_id": payload.product_id,
            "style": style,
            "category": category,
            "gender": gender,
            "prompt": prompt_data
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

def process_generation_job(job_id: str, payload: GenerateImageRequest):
    try:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "processing"
            JOBS[job_id]["progress"] = 20

        if not IMAGEN_ENABLED:
            raise RuntimeError("Image generation not available")

        file_path = resolve_image_path(payload.product_id)
        if not file_path:
            raise RuntimeError("Product image not found")

        category = normalize_category(payload.category)
        gender = normalize_gender(payload.gender)
        style = normalize_style(payload.style)
        render_preset = normalize_render_preset(payload.render_preset)
        image_model, model_name = select_image_model(render_preset)

        prompt = build_prompt(
            category=category,
            gender=gender,
            style=style,
            skin_tone=payload.skin_tone,
            stone_detail=payload.stone_detail
        )

        with JOBS_LOCK:
            JOBS[job_id]["progress"] = 45
            JOBS[job_id]["prompt_preview"] = prompt[:400]
            JOBS[job_id]["model"] = model_name

        base_img = prepare_base_image_1024(file_path)
        try:
            response = image_model.generate_content(
                [prompt, base_img],
                generation_config=genai.GenerationConfig(
                    response_modalities=["IMAGE", "TEXT"]
                )
            )
        except Exception:
            response = image_model.generate_content([prompt, base_img])
        base_img.close()

        with JOBS_LOCK:
            JOBS[job_id]["progress"] = 70

        image_bytes = extract_inline_image_bytes(response)
        if not image_bytes:
            raise RuntimeError("No image generated")

        generated_id = f"{payload.product_id}_{style}_{datetime.now().strftime('%H%M%S')}"
        output_path = OUTPUT_DIR / f"{generated_id}.png"
        output_4k_path = OUTPUT_DIR / f"{generated_id}_4k.png"

        with open(output_path, "wb") as f:
            f.write(image_bytes)

        resolution_info = {}
        image_4k_url = None
        download_4k_url = None
        if render_preset == "hero":
            resolution_info = upscale_to_4k(output_path, output_4k_path)
            image_4k_url = f"/api/generated/{generated_id}/image?quality=4k"
            download_4k_url = f"/api/generated/{generated_id}/image?quality=4k&download=true"
        else:
            with Image.open(output_path) as out:
                resolution_info = {
                    "provider": "base-only",
                    "source_width": out.size[0],
                    "source_height": out.size[1],
                    "target_width": out.size[0],
                    "target_height": out.size[1]
                }

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["progress"] = 100
            JOBS[job_id]["result"] = {
                "success": True,
                "product_id": payload.product_id,
                "generated_id": generated_id,
                "style": style,
                "category": category,
                "gender": gender,
                "render_preset": render_preset,
                "image_url": f"/api/generated/{generated_id}/image?quality=original",
                "image_4k_url": image_4k_url,
                "download_4k_url": download_4k_url,
                "resolution": resolution_info
            }
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(exc)

@app.post("/api/generate/image")
async def generate_image(payload: GenerateImageRequest, background_tasks: BackgroundTasks):
    """Start async jewelry image generation job"""
    file_path = resolve_image_path(payload.product_id)
    if not file_path:
        raise HTTPException(404, "Product image not found")
    normalize_category(payload.category)
    normalize_gender(payload.gender)
    normalize_style(payload.style)
    normalize_render_preset(payload.render_preset)

    job_id = uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "created_at": datetime.now().isoformat(),
            "result": None,
            "error": None
        }

    background_tasks.add_task(process_generation_job, job_id, payload)
    return {
        "success": True,
        "job_id": job_id,
        "status_url": f"/api/status/{job_id}"
    }

@app.get("/api/status/{job_id}")
async def get_generation_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@app.get("/api/generated/{generated_id}/image")
async def get_generated_image(
    generated_id: str,
    quality: str = "4k",
    download: bool = False
):
    """Get generated image"""
    if quality not in {"original", "4k"}:
        raise HTTPException(400, "Invalid quality. Use 'original' or '4k'")

    file_path = OUTPUT_DIR / f"{generated_id}.png"
    if quality == "4k":
        file_path = OUTPUT_DIR / f"{generated_id}_4k.png"

    if not file_path.exists():
        raise HTTPException(404, "Generated image not found")

    filename = f"{generated_id}_{quality}.png"
    disposition = "attachment" if download else "inline"
    return FileResponse(
        file_path,
        media_type="image/png",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
    )

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
