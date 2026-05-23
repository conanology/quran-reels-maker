"""
AI Brain - Interface with OpenRouter for thematic background prompts and metadata generation.
"""
import os
import json
import requests
from loguru import logger

from config.settings import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)

def call_openrouter(prompt: str, system_prompt: str = "") -> str:
    """
    Call OpenRouter API with a prompt and system prompt.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not set. Skipping AI brain call.")
        return ""

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/conanology/quran-reels-maker",
        "X-Title": "Quran Reels Maker"
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }

    primary_model = OPENROUTER_MODEL or "deepseek/deepseek-v4-flash:free"
    models_to_try = [primary_model]
    if primary_model != "openrouter/free":
        models_to_try.append("openrouter/free")
    
    # Specific stable free models as additional fallbacks
    stable_fallbacks = ["nvidia/nemotron-3-super-120b-a12b:free", "liquid/lfm-2.5-1.2b-instruct:free"]
    for fb in stable_fallbacks:
        if fb not in models_to_try:
            models_to_try.append(fb)

    for idx, model in enumerate(models_to_try):
        payload["model"] = model
        try:
            logger.info(f"Calling OpenRouter model: {model} (Attempt {idx+1}/{len(models_to_try)})")
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0].get("message", {}).get("content")
                    if content:
                        return content.strip()
                    else:
                        logger.warning(f"OpenRouter model {model} returned choice but no message content. Full Response: {result}")
                else:
                    logger.error(f"OpenRouter returned unexpected response structure for {model}: {result}")
            else:
                logger.error(f"OpenRouter API error for {model}: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"OpenRouter request failed for {model}: {e}")

    return ""


def generate_visual_prompt(translation: str) -> str:
    """
    Generate a descriptive text-to-image prompt based on the verse translation.
    """
    if not translation:
        return ""

    system_prompt = (
        "You are an expert visual director for Islamic media. Your task is to analyze the English translation of a Quranic "
        "verse and output a highly descriptive visual prompt for a text-to-image generator (Stable Diffusion/Flux). "
        "The background should be a majestic, peaceful nature scene matching the themes, tone, or metaphors of the verse "
        "(e.g., mountains, oceans, night sky, celestial bodies, rivers, forests, dawn, desert dunes, rain). "
        "STRICT RULES:\n"
        "1. NO human figures, faces, silhouettes, or characters of any kind.\n"
        "2. NO text, titles, writing, or watermarks.\n"
        "3. Focus purely on natural elements, lighting, atmosphere, and visual aesthetics.\n"
        "4. The output must be in vertical orientation.\n"
        "5. Output ONLY the visual prompt string itself. Do not include introductory phrases, quotes, or formatting."
    )

    prompt = f"Verse Translation: \"{translation}\"\n\nGenerate the visual prompt now:"
    
    ai_response = call_openrouter(prompt, system_prompt)
    
    if ai_response:
        # Strip outer quotes if the model wrapped it in quotes
        ai_response = ai_response.strip("\"'")
        logger.info(f"AI generated visual prompt: {ai_response}")
        return ai_response

    return ""


def _clean_json_response(text: str) -> str:
    """Clean markdown backticks or extra lines around a JSON response."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def generate_video_metadata(
    surah_name: str,
    start_ayah: int,
    end_ayah: int,
    reciter_name: str,
    translation: str,
) -> dict:
    """
    Generate engaging title, description, and tags for YouTube upload.
    """
    system_prompt = (
        "You are a social media growth expert specializing in Islamic content. Your task is to generate engaging metadata "
        "for a YouTube Short / TikTok video based on the Quranic verse translation and reciter.\n"
        "Output a JSON object containing exactly three fields:\n"
        "1. \"title\": a hook-filled, emotionally resonant title (maximum 55 characters) that includes a thematic "
        "English phrase, a relevant emoji, the Surah name, and the verse range (e.g. \"Trust Allah's Plan 💫 | Surah Al-Kahf 10\").\n"
        "2. \"description\": a beautifully formatted description incorporating a short reflection paragraph (2-3 sentences) "
        "on the verse's meaning/relevance, the full English translation, and key hashtags.\n"
        "3. \"tags\": a list of 10-15 highly relevant tags/keywords.\n\n"
        "STRICT RULE: Output ONLY raw JSON. Do not include markdown code block formatting or explanations outside the JSON."
    )

    prompt = (
        f"Surah: {surah_name}\n"
        f"Verses: {start_ayah}-{end_ayah}\n"
        f"Reciter: {reciter_name}\n"
        f"English Translation: \"{translation}\"\n\n"
        "Generate the metadata JSON now:"
    )

    ai_response = call_openrouter(prompt, system_prompt)
    if not ai_response:
        return {}

    try:
        cleaned_json = _clean_json_response(ai_response)
        metadata = json.loads(cleaned_json)
        
        # Basic validation
        if all(k in metadata for k in ("title", "description", "tags")):
            logger.info(f"AI generated metadata title: {metadata['title']}")
            return metadata
        else:
            logger.warning(f"AI metadata response missing required fields: {metadata}")
            return {}
    except Exception as e:
        logger.error(f"Failed to parse AI metadata JSON: {e}\nRaw response:\n{ai_response}")
        return {}


def generate_longform_video_metadata(
    surah_start: int,
    surah_end: int,
    reciter_name: str,
    translation: str,
) -> dict:
    """
    Generate high-CTR title, descriptive reflection, and tags for long-form videos.
    """
    from config.settings import SURAH_NAMES_AR, SURAH_NAMES_EN
    
    if surah_start == surah_end:
        surah_label = f"Surah {SURAH_NAMES_EN[surah_start - 1]} ({SURAH_NAMES_AR[surah_start - 1]})"
    else:
        surah_label = f"Surahs {SURAH_NAMES_EN[surah_start - 1]}-{SURAH_NAMES_EN[surah_end - 1]} ({SURAH_NAMES_AR[surah_start - 1]}-{SURAH_NAMES_AR[surah_end - 1]})"

    system_prompt = (
        "You are an expert YouTube growth strategist specializing in Islamic content. Your task is to generate highly engaging, "
        "SEO-optimized metadata for a long-form YouTube video of Quran recitation.\n"
        "Output a JSON object containing exactly three fields:\n"
        "1. \"title\": a high-CTR, emotionally resonant title (maximum 90 characters) that includes a beautiful thematic hook, "
        "the Surah names in both Arabic and English, and the reciter's name (e.g., \"Heart Soothing Recitation 🕊️ | سورة الملك كاملة | Surah Al-Mulk Full - Mishary Alafasy\").\n"
        "2. \"reflection\": a beautifully written, reflective introduction paragraph (3-4 sentences) explaining the key themes, "
        "spiritual benefits, or meanings of the Surah(s) compiled. This will be placed at the top of the description to engage listeners.\n"
        "3. \"tags\": a list of 15-20 highly searched tags/keywords for this specific compilation.\n\n"
        "STRICT RULE: Output ONLY raw JSON. Do not include markdown code block formatting or explanations outside the JSON."
    )

    prompt = (
        f"Compilation: {surah_label}\n"
        f"Reciter: {reciter_name}\n"
        f"Starting Verse Translation: \"{translation}\"\n\n"
        "Generate the long-form metadata JSON now:"
    )

    ai_response = call_openrouter(prompt, system_prompt)
    if not ai_response:
        return {}

    try:
        cleaned_json = _clean_json_response(ai_response)
        metadata = json.loads(cleaned_json)
        
        # Basic validation
        if all(k in metadata for k in ("title", "reflection", "tags")):
            logger.info(f"AI generated longform title: {metadata['title']}")
            return metadata
        else:
            logger.warning(f"AI longform metadata response missing required fields: {metadata}")
            return {}
    except Exception as e:
        logger.error(f"Failed to parse AI longform metadata JSON: {e}\nRaw response:\n{ai_response}")
        return {}
