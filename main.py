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
    version="1.4.0"
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

def analyze_image_params(file_path: Path) -> dict:
    """Use Gemini to auto-detect all generation parameters from the jewelry image"""
    import re as _re
    try:
        img = Image.open(file_path)
        response = model.generate_content([
            'Analyze this jewelry product image and return ONLY a JSON object with exactly these fields:\n'
            '{\n'
            '  "category": one of ["earrings", "necklace", "ring", "bracelet"],\n'
            '  "gender": one of ["female", "male", "child", "unisex"] based on jewelry design style,\n'
            '  "skin_tone": one of ["fair porcelain", "light warm", "light neutral", "warm medium", "medium olive", "medium tan", "deep warm", "rich deep"],\n'
            '  "stone_detail": describe any gemstones visible (color, cut, type), or empty string if none,\n'
            '  "name": a short luxury product name in English, max 4 words (e.g. "Celestial Gold Ring", "Turquoise Drop Earrings", "Diamond Tennis Bracelet"),\n'
            '  "aesthetic_vibe": describe the mood/aesthetic in 3-5 words that would suit this piece (e.g. "bohemian sunset warmth", "royal gala opulence", "minimalist morning calm", "ancient greek goddess", "urban chic edge", "romantic garden bloom")\n'
            '}\n'
            'IMPORTANT: Return ONLY the raw JSON object. No markdown, no code fences, no explanation.',
            img
        ])
        raw = response.text.strip()
        # Strip markdown code fences robustly
        raw = _re.sub(r'^```(?:json)?\s*', '', raw, flags=_re.MULTILINE)
        raw = _re.sub(r'```\s*$', '', raw, flags=_re.MULTILINE)
        raw = raw.strip()
        # Extract first JSON object found in response
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if json_match:
            raw = json_match.group()
        params = json.loads(raw)
        # Validate and sanitize fields
        if params.get("category") not in ALLOWED_CATEGORIES:
            params["category"] = None
        if params.get("gender") not in ALLOWED_GENDERS:
            params["gender"] = "female"
        if not params.get("skin_tone"):
            params["skin_tone"] = "warm medium"
        return params
    except Exception as e:
        print(f"[analyze_image_params] failed: {e}")
        return {}

def resolve_all_params(product_id: str, payload) -> tuple:
    """Resolve category, gender, skin_tone, stone_detail, aesthetic_vibe from request or metadata fallback"""
    detected = {}
    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            detected = json.load(f).get("detected_params", {}) or {}

    # If no category in metadata (detection failed at upload), retry now
    if not detected.get("category"):
        file_path = resolve_image_path(product_id)
        if file_path:
            detected = analyze_image_params(file_path)

    raw_category   = detected.get("category")       or payload.category       or ""
    raw_gender     = detected.get("gender")         or payload.gender         or "female"
    skin_tone      = payload.skin_tone      if payload.skin_tone      else detected.get("skin_tone", "medium")
    stone_detail   = payload.stone_detail   if payload.stone_detail   else detected.get("stone_detail", "")
    aesthetic_vibe = payload.aesthetic_vibe if payload.aesthetic_vibe else detected.get("aesthetic_vibe", "")

    category = normalize_category(raw_category) if raw_category else None
    if not category:
        print(f"[resolve_all_params] category detection failed for {product_id}, using fallback 'necklace'")
        category = "necklace"
    gender = normalize_gender(raw_gender)
    return category, gender, skin_tone, stone_detail, aesthetic_vibe

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

# ── Category-specific editorial model shoot compositions ─────────────────────
MODEL_COMPOSITIONS = {
    "earrings": (
        "COMPOSITION & POSE: Fingertips lightly touching — or hovering millimeters from — the earring, "
        "hand raised gracefully to cheek level. The earring commands razor-sharp focus at center-frame. "
        "Face behind: one eye, one eyebrow, and a soft cheekbone dissolve into warm bokeh — "
        "impressionistic, never fully defined. "
        "Hair swept completely back — not a single strand may shadow or cross the earring."
    ),
    "necklace": (
        "COMPOSITION & POSE: One hand rests open on the chest, 1–2 fingertips delicately touching "
        "or cradling the pendant — as though sensing its weight and warmth. "
        "Chin and soft lips drift gently in from the top of frame, wrapped in warm bokeh — never a full face. "
        "A single luminous highlight ribbon runs along the collarbone skin. "
        "A whisper of silk or satin fabric enters from the lower corner — texture and luxury, not identity."
    ),
    "ring": (
        "COMPOSITION & POSE: Hand pressed softly against the cheek or jawline — the ring is the tack-sharp hero of the frame. "
        "Face behind: one eye, cheekbone, the curve of a jaw — all warm bokeh, impressionistic, never defined. "
        "SKIN QUALITY: Porcelain glass-skin — luminously translucent, lit from within, perfectly even tone, zero visible pores. "
        "A single soft-box from upper-left sculpts cinematic light; the gemstone catches a precise star-burst sparkle."
    ),
    "bracelet": (
        "COMPOSITION & POSE: The opposite hand wraps gently around the wrist from beneath — "
        "fingers curling underneath in a tender, instinctive gesture of care. "
        "The bracelet is the tack-sharp focal point. Wrapping fingers are slightly softer — readable but secondary. "
        "Arm dissolves upward into warm, painterly bokeh. "
        "No face, no upper body — the gesture alone carries the full emotion and story."
    ),
}

# ── Category-specific studio / e-commerce compositions ───────────────────────
STUDIO_COMPOSITIONS = {
    "earrings": (
        "COMPOSITION: Both earrings displayed as a matching pair, angled 10–15° to show dimensionality. "
        "Centered on the surface with a crisp, thin natural drop shadow beneath each. "
        "All-around tack-sharp focus from front post to backing."
    ),
    "necklace": (
        "COMPOSITION: Necklace arranged in a perfect graceful curve or gentle S-shape, pendant centered and prominent. "
        "Slight elevation on one side for natural depth. A thin, soft shadow grounds the chain."
    ),
    "ring": (
        "COMPOSITION: Ring standing upright or at a 15° dynamic tilt revealing both the profile and the full stone face. "
        "Crisp minimal drop shadow beneath. Complete depth-of-field sharpness throughout."
    ),
    "bracelet": (
        "COMPOSITION: Bracelet in an open oval or perfect circle, clasp discreetly at the base. "
        "Slight elevation creates dimensional shadow revealing depth. Full all-around tack-sharp focus."
    ),
}


def _vibe_scene(vibe: str) -> dict:
    """Map aesthetic_vibe keywords to scene/lighting/atmosphere descriptors."""
    vibe_lower = vibe.lower() if vibe else ""

    if any(k in vibe_lower for k in ["bohem", "sunset", "warm", "golden hour", "earth"]):
        return {
            "scene": "sun-drenched terracotta balcony with warm amber tones and dried wildflowers softly blurred behind",
            "lighting": "warm golden-hour side lighting at 30° — honeyed amber tones kissing the metal, deep rich shadows",
            "atmosphere": "bohemian sunset warmth — wanderlust, free-spirited, sun-kissed luxury",
        }
    if any(k in vibe_lower for k in ["royal", "gala", "opulen", "regal", "imperial", "baroque"]):
        return {
            "scene": "deep midnight-blue velvet drape with subtle brocade texture receding into darkness",
            "lighting": "dramatic chiaroscuro — single focused key light from above left, dark moody shadows, theatrical contrast",
            "atmosphere": "royal gala opulence — aristocratic, commanding, old-world grandeur",
        }
    if any(k in vibe_lower for k in ["minimal", "morning", "calm", "clean", "nordic", "zen"]):
        return {
            "scene": "pale linen textile surface with soft architectural shadows and clean negative space",
            "lighting": "soft diffused northern-window light — even, shadow-less, whisper-quiet",
            "atmosphere": "minimalist morning calm — breathable, serene, Scandinavian restraint",
        }
    if any(k in vibe_lower for k in ["greek", "goddess", "ancient", "roman", "marble", "olymp"]):
        return {
            "scene": "cool Carrara marble surface with classical column texture barely visible in soft bokeh background",
            "lighting": "cool Mediterranean daylight — bright, pure, classical balance of highlights and mid-tones",
            "atmosphere": "ancient goddess majesty — timeless, mythological, sculptural",
        }
    if any(k in vibe_lower for k in ["urban", "chic", "edge", "street", "modern", "sleek"]):
        return {
            "scene": "polished dark concrete surface with subtle city-light reflections and cool steel tones",
            "lighting": "sharp directional artificial light — crisp high-contrast, cool white with neon accent rim",
            "atmosphere": "urban chic edge — contemporary, bold, metropolitan sophistication",
        }
    if any(k in vibe_lower for k in ["romantic", "garden", "bloom", "floral", "spring", "rose"]):
        return {
            "scene": "blush-pink petal scatter on soft ivory silk with garden greenery dissolving into bokeh",
            "lighting": "soft romantic backlight through sheer curtain — luminous halo, pastel-warm, dreamlike",
            "atmosphere": "romantic garden bloom — tender, feminine, fresh-blossom luxury",
        }
    if any(k in vibe_lower for k in ["celestial", "cosmic", "night", "mystic", "dark", "moon"]):
        return {
            "scene": "deep indigo velvet with subtle star-dust shimmer dusted across the surface",
            "lighting": "cool silver rim light from above — moonlit glow, ethereal highlights, deep shadowed mystery",
            "atmosphere": "celestial mystique — otherworldly, enigmatic, night-sky fantasy",
        }
    # Default: timeless luxury
    return {
        "scene": "neutral warm-ivory silk surface with a soft organic gradient dissolving to darkness",
        "lighting": "cinematic three-point lighting — diffused key at 45° above, warm golden rim, gentle fill to open shadows",
        "atmosphere": "timeless luxury — elegant, aspirational, high-fashion editorial",
    }


def build_prompt(
    category: str,
    gender: str,
    style: str,
    skin_tone: str,
    stone_detail: str = "",
    aesthetic_vibe: str = ""
) -> str:
    JEWELRY_DESC = {
        "bracelet": "solid 18k gold bracelet/bangle",
        "ring":     "solid 18k gold ring",
        "earrings": "solid 18k gold earrings",
        "necklace": "solid 18k gold necklace",
    }
    GENDER_BODY = {
        "female":  "slender elegant female model",
        "male":    "refined masculine male model",
        "child":   "gentle age-appropriate child model",
        "unisex":  "gender-neutral modern model",
    }
    stone_line = (
        f"STONES: Reproduce exactly — {stone_detail}. Keep cut, color saturation, fire, transparency and setting 1:1."
        if stone_detail.strip()
        else "STONES: Reproduce all visible gemstone details exactly as in source — color, cut, fire, transparency, settings."
    )

    vibe = _vibe_scene(aesthetic_vibe)
    vibe_note = f"AESTHETIC VIBE: {aesthetic_vibe} — " if aesthetic_vibe.strip() else ""

    if style == "model":
        return f"""Ultra-realistic luxury jewelry editorial photograph. Shot in the style of a Vogue or Harper's Bazaar campaign.

SUBJECT: {JEWELRY_DESC[category]} worn on a {GENDER_BODY[gender]}.
SCENE: {vibe["scene"]}.
LIGHTING: {vibe["lighting"]}.
ATMOSPHERE: {vibe_note}{vibe["atmosphere"]}.

{MODEL_COMPOSITIONS[category]}

SKIN: {skin_tone} skin tone — porcelain-smooth, flawless glass-skin texture with luminous translucency and subtle natural glow.
BACKGROUND: Shallow depth of field, f/1.8 macro — jewelry stays razor-sharp, background melts into painterly bokeh.

══════════ ABSOLUTE PRODUCT INTEGRITY — ZERO TOLERANCE ══════════
• The gold jewelry in the output MUST be 100% identical to the reference source image.
• FORBIDDEN: any reshaping of links, missing stones, altered proportions, wrong gold color, simplified geometry.
• Gold color: warm rich 18k–22k yellow gold — authentic metallic reflections and natural surface texture.
• Reproduce EVERY detail: prongs, links, clasps, engravings, stone settings, surface texture, patina.
• Gemstones: exact color, cut, facets, fire, brilliance, and transparency — no creative reinterpretation.
• Do NOT upgrade, simplify, stylize or redesign — mirror the source jewelry with photographic accuracy.
═════════════════════════════════════════════════════════════════

TECHNICAL: 100mm macro lens, f/1.8–f/2.8, ISO 100, tack-sharp on jewelry, 8K photorealistic quality.
{stone_line}

STRICTLY AVOID: blurry jewelry, distorted metal, wrong gold color, missing details, CGI-plastic look, overexposed highlights, flat lighting, cartoonish rendering, warped geometry, altered design, extra anatomy, full face visible in frame.""".strip()

    else:  # studio — exact retouching prompt, no dynamic additions
        label = JEWELRY_DESC.get(category, "gold jewelry piece")
        return f"""Task: High-resolution luxury jewelry retouching for "{label}".

Core Action: Carefully remove the black display stand from under the object and any attached product tags/labels. Ensure zero trace of strings, attachment marks, holes, shadows, blurring, cloning artifacts, or surface distortions.

Strict Constraints:
Positioning: The {label} must remain in the exact same position, height, angle, perspective, framing, and proportions. Do NOT rotate, tilt, flip, resize, or reshape.
Preservation: Maintain 100% of the original gold color tone, surface reflections, metal textures, thickness, and light behavior.
Grounding: After stand removal, the object must rest naturally as if lightly touching the surface. It must NOT look floating.

Environment & Style:
Background: Pure seamless white (#FFFFFF), uniform, no gradients, no horizon line, no vignette.
Lighting: Maintain the original soft, diffused studio lighting direction.
Shadows: Add only a subtle, realistic contact shadow directly beneath the object to ground it naturally.
Aesthetic: High-resolution luxury product photography, ultra-sharp focus, clean, minimal, premium e-commerce look. No artificial glow, no over-retouching.""".strip()

class GenerateImageRequest(BaseModel):
    product_id: str
    category: str = ""
    gender: str = ""
    style: str = "model"
    skin_tone: str = ""
    stone_detail: str = ""
    aesthetic_vibe: str = ""
    render_preset: str = "hero"

class GeneratePromptRequest(BaseModel):
    product_id: str
    category: str = ""
    gender: str = ""
    style: str = "model"
    skin_tone: str = ""
    stone_detail: str = ""
    aesthetic_vibe: str = ""

class GenerateSeoRequest(BaseModel):
    product_id: str

def build_specs_table_html(specs: dict) -> str:
    """Build a WooCommerce-compatible HTML product specs table from a specs dict."""
    FIELD_ORDER = [
        ("seri",      "Seri"),
        ("model",     "Model"),
        ("ayar",      "Ayar"),
        ("materyal",  "Materyal"),
        ("tas_turu",  "Taş Türü"),
        ("agirlik",   "Ağırlık"),
        ("urun_tipi", "Ürün Tipi"),
        ("cinsiyet",  "Cinsiyet"),
        ("kargo",     "Kargo"),
    ]
    rows = ""
    for key, label in FIELD_ORDER:
        value = specs.get(key) or "-"
        rows += (
            f'\n<tr>'
            f'<td style="border:1px solid #ddd;padding:10px;font-weight:bold;">{label}</td>'
            f'<td style="border:1px solid #ddd;padding:10px;">{value}</td>'
            f'</tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;margin:20px 0;font-family:Arial,sans-serif;">\n'
        '<thead>\n'
        '<tr style="background-color:#f2f2f2;">\n'
        '<th style="border:1px solid #ddd;padding:12px;text-align:left;">Özellik</th>\n'
        '<th style="border:1px solid #ddd;padding:12px;text-align:left;">Bilgi</th>\n'
        '</tr>\n'
        '</thead>\n'
        f'<tbody>{rows}\n</tbody>\n'
        '</table>'
    )


def generate_seo_content(product_id: str) -> dict:
    """Generate WooCommerce + RankMath SEO content in Turkish using Gemini."""
    import re as _re

    metadata_path = UPLOAD_DIR / f"{product_id}.json"
    if not metadata_path.exists():
        raise HTTPException(404, "Product not found")

    with open(metadata_path) as f:
        metadata = json.load(f)

    detected    = metadata.get("detected_params", {}) or {}
    name        = detected.get("name")        or "Altın Takı"
    category    = detected.get("category")    or "necklace"
    gender      = detected.get("gender")      or "female"
    stone_detail = detected.get("stone_detail") or ""

    CATEGORY_TR = {"earrings": "küpe", "necklace": "kolye", "ring": "yüzük", "bracelet": "bileklik"}
    GENDER_TR   = {"female": "Kadın", "male": "Erkek", "child": "Çocuk", "unisex": "Uniseks"}

    category_tr = CATEGORY_TR.get(category, category)
    gender_tr   = GENDER_TR.get(gender, gender)
    stone_info  = f", taş: {stone_detail}" if stone_detail else ""

    prompt_text = (
        f'Bu mücevher ürünü için WooCommerce + RankMath SEO içeriği üret. Tamamen Türkçe olacak.\n'
        f'Ürün: "{name}", tür: {category_tr}, cinsiyet: {gender_tr}{stone_info}\n\n'
        'SADECE şu JSON objesini döndür:\n'
        '{\n'
        '  "focus_keyword": "ana SEO anahtar kelimesi (ör. \'14 ayar altın kolye kadın\'), max 50 karakter",\n'
        '  "meta_title": "SEO meta başlığı — max 60 karakter, marka+ürün+ayar formatında",\n'
        '  "meta_description": "RankMath meta açıklaması — max 155 karakter, anahtar kelimeyi içermeli, satın almaya teşvik etmeli",\n'
        '  "url_slug": "woocommerce url slug — küçük harf, tire ile ayrılmış, Türkçe karakter kullanma (ç→c, ş→s, ı→i, ğ→g, ö→o, ü→u)",\n'
        '  "product_description": "2–3 paragraf lüks ürün açıklaması Türkçe, WooCommerce için HTML <p> etiketleriyle. Duygusal, lüks marka tonu.",\n'
        '  "specs": {\n'
        '    "seri": "tasarıma uygun yaratıcı seri adı (ör. Celeste Serisi, Aurora Serisi, Lumina Serisi)",\n'
        f'    "model": "{name}",\n'
        '    "ayar": "14 Ayar Altın veya 18 Ayar Altın (görselden tahmin et; emin değilsen 14 Ayar Altın yaz)",\n'
        '    "materyal": "Altın",\n'
        f'    "tas_turu": "Türkçe taş türü{(chr(32) + stone_detail[:30]) if stone_detail else " veya Taşsız"}",\n'
        '    "agirlik": "gram cinsinden tahmini ağırlık (ör. \'2,14 gr\') veya \'- gr\'",\n'
        f'    "urun_tipi": "Türkçe spesifik ürün tipi (ör. \'Sarkıt Küpe\', \'Kalp Kolye\', \'Tektaş Yüzük\', \'Zincir Bileklik\')",\n'
        f'    "cinsiyet": "{gender_tr}",\n'
        '    "kargo": "Ücretsiz Sigortalı Kargo"\n'
        '  }\n'
        '}\n'
        'ÖNEMLİ: Sadece ham JSON objesi döndür. Markdown, kod bloğu veya açıklama ekleme.'
    )

    # Pass image for context (karat estimation, weight, type refinement)
    file_path = resolve_image_path(product_id)
    if file_path:
        img = Image.open(file_path)
        response = model.generate_content([img, prompt_text])
    else:
        response = model.generate_content([prompt_text])

    raw = response.text.strip()
    raw = _re.sub(r'^```(?:json)?\s*', '', raw, flags=_re.MULTILINE)
    raw = _re.sub(r'```\s*$', '', raw, flags=_re.MULTILINE)
    raw = raw.strip()
    json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
    if json_match:
        raw = json_match.group()

    seo = json.loads(raw)
    seo["specs_html"] = build_specs_table_html(seo.get("specs", {}))
    return seo


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
        "version": "1.4.0",
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
        
        # Calculate hash
        file_hash = calculate_hash(file_path)

        # Auto-detect all generation parameters
        detected_params = analyze_image_params(file_path)

        # Save metadata
        metadata = {
            "product_id": product_id,
            "filename": file.filename,
            "size": {"width": width, "height": height},
            "format": img.format,
            "hash": file_hash,
            "uploaded_at": datetime.now().isoformat(),
            "detected_params": detected_params
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

        category, gender, skin_tone, stone_detail, aesthetic_vibe = resolve_all_params(payload.product_id, payload)
        style = normalize_style(payload.style)

        prompt_text = build_prompt(
            category=category,
            gender=gender,
            style=style,
            skin_tone=skin_tone,
            stone_detail=stone_detail,
            aesthetic_vibe=aesthetic_vibe
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

def generate_creative_model_prompt(
    category: str,
    gender: str,
    skin_tone: str,
    stone_detail: str,
    aesthetic_vibe: str,
    image_path: Path
) -> str:
    """
    Ask Gemini to study the product and invent a unique editorial campaign prompt.
    Each call produces a fresh, original composition — no two shots should look the same.
    Falls back to static build_prompt on failure.
    """
    JEWELRY_LABEL = {
        "bracelet": "gold bracelet",
        "ring":     "gold ring",
        "earrings": "gold earrings",
        "necklace": "gold necklace",
    }
    label       = JEWELRY_LABEL.get(category, "gold jewelry")
    stone_ctx   = f"set with {stone_detail}" if stone_detail.strip() else "no gemstones"
    vibe_ctx    = f"The overall mood should evoke: {aesthetic_vibe}." if aesthetic_vibe.strip() else ""

    meta_prompt = (
        f"You are a world-class luxury jewelry art director creating a one-of-a-kind editorial campaign image.\n\n"
        f"Study this {label} ({stone_ctx}) carefully — every curve, texture, and detail matters.\n"
        f"Subject: {gender} model with {skin_tone} skin tone. {vibe_ctx}\n\n"
        f"TASK: Write a vivid, specific image generation prompt (150–250 words) for a UNIQUE editorial model shoot.\n\n"
        f"CREATIVE FREEDOM — invent your own scene. Vary freely:\n"
        f"  · Pose & gesture — hand positions, how the body interacts with the {label}\n"
        f"  · Face inclusion — none / chin+lips only / cheek+jaw / eye+brow only — never a full face\n"
        f"  · Background — velvet, marble, silk, concrete, linen, terracotta, nature — anything evocative\n"
        f"  · Lighting — golden hour, chiaroscuro, diffused window, neon accent, candlelight rim\n"
        f"  · Mood — romantic, editorial cold, warm intimate, architectural minimal, mystic, cinematic\n"
        f"  · Framing — extreme close-up, medium crop, dramatic diagonal, symmetric\n\n"
        f"ALWAYS follow these rules:\n"
        f"  1. The {label} is the ABSOLUTE hero — in razor-sharp focus, center of visual gravity\n"
        f"  2. Skin: porcelain glass-skin — luminously translucent, lit from within, zero visible pores\n"
        f"  3. Nails: impeccably manicured, nude or white — never distracting\n"
        f"  4. No full face in frame — only partial impressionistic face elements in warm bokeh\n"
        f"  5. Specify exact technical: lens, aperture, lighting source direction\n"
        f"  6. End your prompt with this exact sentence:\n"
        f'     "ZERO TOLERANCE: Reproduce the {label} EXACTLY as in the reference image — '
        f'identical design, gold color, all proportions, every stone, link, and detail unchanged. '
        f'Do NOT redesign, simplify, or alter the jewelry in any way."\n\n'
        f"Return ONLY the prompt text. No headings, labels, or explanation."
    )

    img = Image.open(image_path)
    response = model.generate_content([img, meta_prompt])
    creative_prompt = response.text.strip()

    # Ensure product integrity block is always appended
    integrity_block = (
        "\n\n══════════ ABSOLUTE PRODUCT INTEGRITY — ZERO TOLERANCE ══════════\n"
        f"• The {label} in the output MUST be 100% identical to the reference source image.\n"
        "• FORBIDDEN: any reshaping, missing stones, altered proportions, wrong gold color, simplified geometry.\n"
        "• Gold color: warm rich 18k–22k yellow gold — authentic metallic reflections and surface texture.\n"
        "• Reproduce EVERY detail: prongs, links, clasps, engravings, stone settings, surface texture, patina.\n"
        "• Gemstones: exact color, cut, facets, fire, brilliance, transparency — zero creative reinterpretation.\n"
        "• Do NOT upgrade, stylize, or redesign — mirror the source jewelry with photographic precision.\n"
        "═════════════════════════════════════════════════════════════════"
    )
    return creative_prompt + integrity_block


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

        category, gender, skin_tone, stone_detail, aesthetic_vibe = resolve_all_params(payload.product_id, payload)
        style = normalize_style(payload.style)
        render_preset = normalize_render_preset(payload.render_preset)
        image_model, model_name = select_image_model(render_preset)

        if style == "model":
            try:
                prompt = generate_creative_model_prompt(
                    category=category,
                    gender=gender,
                    skin_tone=skin_tone,
                    stone_detail=stone_detail,
                    aesthetic_vibe=aesthetic_vibe,
                    image_path=file_path
                )
                print(f"[creative_prompt] Generated unique editorial prompt for job {job_id}")
            except Exception as e:
                print(f"[creative_prompt] Failed ({e}), falling back to static prompt")
                prompt = build_prompt(
                    category=category,
                    gender=gender,
                    style=style,
                    skin_tone=skin_tone,
                    stone_detail=stone_detail,
                    aesthetic_vibe=aesthetic_vibe
                )
        else:
            prompt = build_prompt(
                category=category,
                gender=gender,
                style=style,
                skin_tone=skin_tone,
                stone_detail=stone_detail,
                aesthetic_vibe=aesthetic_vibe
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
        error_msg = exc.detail if hasattr(exc, "detail") else str(exc)
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = error_msg

@app.post("/api/generate/image")
async def generate_image(payload: GenerateImageRequest, background_tasks: BackgroundTasks):
    """Start async jewelry image generation job"""
    file_path = resolve_image_path(payload.product_id)
    if not file_path:
        raise HTTPException(404, "Product image not found")
    if payload.category:
        normalize_category(payload.category)
    if payload.gender:
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

@app.post("/api/generate/seo")
async def generate_seo(payload: GenerateSeoRequest):
    """Generate WooCommerce + RankMath SEO content for a product"""
    try:
        seo = generate_seo_content(payload.product_id)
        return {
            "success": True,
            "product_id": payload.product_id,
            "seo": seo
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


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
