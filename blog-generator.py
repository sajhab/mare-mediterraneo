#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blog-generator.py
Mare Mediterraneo — Daily Blog Automation
Called by GitHub Actions: .github/workflows/daily-blog.yml

Changes from original:
- Generates one DALL-E 3 image per topic (shared across all 4 language variants)
- Saves image as blog/images/YYYY-MM-DD-{topic-slug}.jpg
- Adds image_url field to articles.json entries
- Template now uses {{HERO_IMAGE_URL}} / {{HERO_IMAGE_ALT}} placeholders
"""

import os
import json
import re
import sys
import datetime
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
import base64

# ── CONFIGURATION ────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
REPO_ROOT      = os.path.dirname(os.path.abspath(__file__))
BLOG_DIR       = os.path.join(REPO_ROOT, "blog")
IMAGES_DIR     = os.path.join(BLOG_DIR, "images")
TEMPLATE_PATH  = os.path.join(BLOG_DIR, "template.html")
ARTICLES_JSON  = os.path.join(BLOG_DIR, "articles.json")
TOPICS_JSON    = os.path.join(REPO_ROOT, "topics.json")
SITEMAP_PATH   = os.path.join(REPO_ROOT, "sitemap.xml")
USED_TOPICS_PATH = os.path.join(REPO_ROOT, ".used_topics.json")

LANGUAGES = ["it", "de", "fr", "en"]

LANG_CONFIG = {
    "it": {
        "label": "Italiano",
        "og_locale": "it_IT",
        "cta_title": "Soggiornate in Salento?",
        "cta_text": "Mare Mediterraneo — due suite eleganti a Torre Chianca, 400m dal mare, 15 minuti da Lecce. Da €200 a notte, prenotazione diretta.",
        "cta_button": "Verifica disponibilità",
        "share_label": "Condividi",
        "related_heading": "Articoli correlati",
        "whatsapp_text": "Ho trovato questo articolo su Salento"
    },
    "de": {
        "label": "Deutsch",
        "og_locale": "de_DE",
        "cta_title": "Urlaub im Salento?",
        "cta_text": "Mare Mediterraneo — zwei elegante Suiten in Torre Chianca, 400m vom Meer, 15 Minuten von Lecce. Ab €200 pro Nacht, Direktbuchung.",
        "cta_button": "Verfügbarkeit prüfen",
        "share_label": "Teilen",
        "related_heading": "Weitere Artikel",
        "whatsapp_text": "Ich habe diesen Artikel über Salento gefunden"
    },
    "fr": {
        "label": "Français",
        "og_locale": "fr_FR",
        "cta_title": "Vacances en Salento?",
        "cta_text": "Mare Mediterraneo — deux suites élégantes à Torre Chianca, 400m de la mer, 15 minutes de Lecce. À partir de €200 par nuit, réservation directe.",
        "cta_button": "Vérifier les disponibilités",
        "share_label": "Partager",
        "related_heading": "Articles connexes",
        "whatsapp_text": "J'ai trouvé cet article sur le Salento"
    },
    "en": {
        "label": "English",
        "og_locale": "en_GB",
        "cta_title": "Staying in Salento?",
        "cta_text": "Mare Mediterraneo — two elegant suites in Torre Chianca, 400m from the sea, 15 minutes from Lecce. From €200 per night, direct booking.",
        "cta_button": "Check Availability",
        "share_label": "Share",
        "related_heading": "Related Articles",
        "whatsapp_text": "I found this article about Salento"
    }
}

RSS_FEEDS = [
    "https://www.lagazzettadelmezzogiorno.it/rss",
    "https://www.quotidianodipuglia.it/feed",
    "https://www.leccenews24.it/feed",
    "https://www.brindisireport.it/feed",
    "https://www.viaggiareinpuglia.it/feed"
]

ARTICLE_PROMPT = """You are a warm, knowledgeable local travel writer for Mare Mediterraneo, a vacation rental in Torre Chianca, Salento, 15 minutes from Lecce.

Write a {word_count} word article in {language} about: {topic}

CONTEXT AND ANGLE: {angle}

SEO KEYWORDS TO USE NATURALLY: {keywords}

REQUIREMENTS:
- Genuinely useful to tourists visiting Salento — specific local details, real place names, distances, practical tips
- Naturally mention Mare Mediterraneo as the perfect base for exploring the area (not forced, maximum 2-3 mentions total)
- End with a soft, natural call to action to check availability at Mare Mediterraneo
- Warm, knowledgeable tone — like a local friend sharing insider knowledge, not a marketing brochure
- Never sound like AI or generic travel copy
- Include specific distances: Torre Chianca is 400m from the sea, 15 minutes from Lecce, 25 min from Punta Prosciutto, 30 min from Porto Cesareo, 35 min from Otranto, 45 min from Gallipoli
- When mentioning Mare Mediterraneo prices: Suite Pietra and Suite Cielo from 200 EUR per night, Villa Completa (4 beds, up to 8 guests) from 350 EUR per night. Minimum stay 4 nights.
- Value framing: a week for 4 people from 1550 EUR total — that is 55 EUR per person per night, less than a single hotel room in Lecce
- Mention direct booking saves 12-15% versus Airbnb fees
- Write in {language} — native quality, NOT translated, freshly written for {language}-speaking readers
- Structure with H2 subheadings for readability
- Total article word count: approximately {word_count} words

OUTPUT FORMAT — return only a JSON object with these exact fields, no markdown fences, no backticks:
{{
  "title": "article title in {language}",
  "meta_description": "150-160 character meta description in {language}",
  "excerpt": "2-3 sentence excerpt for blog index in {language}",
  "body_html": "full article body HTML with <h2>, <p>, <ul>, <li> tags — no <html>, <head>, <body> wrappers",
  "reading_time": 5,
  "image_prompt": "a single English sentence describing a photorealistic travel photo that would illustrate this article — specific Salento/Puglia scene, no text overlays, golden hour preferred"
}}"""


# ── HELPERS ──────────────────────────────────────────────────

def log(msg):
    print("[blog-generator] " + str(msg))

def load_json(path, default=None):
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log("Failed to load " + path + ": " + str(e))
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def slugify(text):
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


# ── RSS FETCHING ─────────────────────────────────────────────

def fetch_rss_headline():
    for feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed_url)
            req.add_header("User-Agent", "MareMediterraneo-BlogBot/1.0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read()
            root = ET.fromstring(content)
            items = root.findall(".//item")
            if not items:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                items = root.findall(".//atom:entry", ns)
            if items:
                item = items[0]
                title_el = item.find("title")
                desc_el  = item.find("description")
                if title_el is not None and title_el.text:
                    headline = title_el.text.strip()
                    summary  = ""
                    if desc_el is not None and desc_el.text:
                        summary = re.sub("<[^>]+>", "", desc_el.text).strip()[:300]
                    return {"headline": headline, "summary": summary, "source": feed_url}
        except Exception as e:
            log("RSS failed for " + feed_url + ": " + str(e))
            continue
    return None


# ── TOPIC SELECTION ──────────────────────────────────────────

def pick_topic(topics):
    used = load_json(USED_TOPICS_PATH, {"used_ids": []})
    used_ids = used.get("used_ids", [])
    for topic in topics:
        if topic["id"] not in used_ids:
            return topic
    log("All topics used — resetting cycle")
    save_json(USED_TOPICS_PATH, {"used_ids": []})
    return topics[0]

def mark_topic_used(topic_id):
    used = load_json(USED_TOPICS_PATH, {"used_ids": []})
    used_ids = used.get("used_ids", [])
    if topic_id not in used_ids:
        used_ids.append(topic_id)
    save_json(USED_TOPICS_PATH, {"used_ids": used_ids})


# ── OPENAI API ───────────────────────────────────────────────

def call_openai_json(prompt):
    """Call GPT-4o and return parsed JSON."""
    payload = json.dumps({
        "model": "gpt-4o",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }).encode("utf-8")
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + OPENAI_API_KEY)
    req.add_header("User-Agent", "MareMediterraneo-BlogBot/1.0")
    req.method = "POST"
    with urllib.request.urlopen(req, data=payload, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["choices"][0]["message"]["content"].strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def generate_image(image_prompt, image_path):
    """
    Call DALL-E 3 to generate an image and save it to image_path.
    Returns True on success, False on failure.

    Uses b64_json response format so we don't need a second download step.
    """
    if not OPENAI_API_KEY:
        log("Skipping image generation — no API key")
        return False

    # Wrap the prompt with style guidance to match the site aesthetic
    # dall-e-2 limit: 1000 chars total
    full_prompt = (
        "Travel photo, Puglia Italy, golden hour. "
        + image_prompt
        + " No text, no watermarks."
    )
    full_prompt = full_prompt[:1000]

    payload = json.dumps({
        "model": "dall-e-2",
        "prompt": full_prompt[:1000],  # dall-e-2 has 1000 char limit
        "n": 1,
        "size": "1024x1024"
    }).encode("utf-8")

    req = urllib.request.Request("https://api.openai.com/v1/images/generations")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + OPENAI_API_KEY)
    req.add_header("User-Agent", "MareMediterraneo-BlogBot/1.0")
    req.method = "POST"

    try:
        with urllib.request.urlopen(req, data=payload, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        image_url = data["data"][0]["url"]
        # Download the image from the temporary OpenAI URL
        img_req = urllib.request.Request(image_url)
        img_req.add_header("User-Agent", "MareMediterraneo-BlogBot/1.0")
        with urllib.request.urlopen(img_req, timeout=60) as img_resp:
            image_bytes = img_resp.read()
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        with open(image_path, "wb") as f:
            f.write(image_bytes)
        log("Image saved: " + image_path + " (" + str(len(image_bytes) // 1024) + " KB)")
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log("DALL-E HTTP error " + str(e.code) + ": " + body[:300])
        return False
    except Exception as e:
        log("DALL-E error: " + str(e))
        return False


def call_claude(prompt, lang):
    """Wrapper around call_openai_json with retry logic."""
    if not OPENAI_API_KEY:
        log("ERROR: OPENAI_API_KEY not set")
        return None
    for attempt in range(1, 3):
        try:
            return call_openai_json(prompt)
        except urllib.error.HTTPError as e:
            log("OpenAI API HTTP error " + str(e.code) + ": " + e.read().decode("utf-8"))
            return None
        except json.JSONDecodeError as e:
            log("Invalid JSON from OpenAI (attempt " + str(attempt) + "): " + str(e))
            if attempt < 2:
                log("Retrying...")
            else:
                return None
        except Exception as e:
            log("OpenAI API error (attempt " + str(attempt) + "): " + str(e))
            if attempt < 2:
                log("Retrying...")
            else:
                return None
    return None


# ── ARTICLE BUILDER ──────────────────────────────────────────

def build_article_html(template, article_data, lang, slug, topic_info, today, image_url, image_alt):
    cfg = LANG_CONFIG[lang]
    publish_date_iso   = today.strftime("%Y-%m-%dT07:00:00+00:00")
    publish_date_human = today.strftime("%B %d, %Y")

    share_url     = "https://maremediterraneo.com/blog/" + slug + ".html"
    whatsapp_msg  = urllib.parse.quote(cfg["whatsapp_text"] + ": " + share_url)

    html = template
    replacements = {
        "{{LANG_CODE}}":          lang,
        "{{LANG_LABEL}}":         cfg["label"],
        "{{OG_LOCALE}}":          cfg["og_locale"],
        "{{ARTICLE_TITLE}}":      article_data.get("title", ""),
        "{{META_DESCRIPTION}}":   article_data.get("meta_description", ""),
        "{{TARGET_KEYWORDS}}":    topic_info.get("target_keywords", ""),
        "{{ARTICLE_SLUG}}":       slug,
        "{{PUBLISH_DATE_ISO}}":   publish_date_iso,
        "{{PUBLISH_DATE_HUMAN}}": publish_date_human,
        "{{READING_TIME}}":       str(article_data.get("reading_time", 5)),
        "{{ARTICLE_EXCERPT}}":    article_data.get("excerpt", ""),
        "{{ARTICLE_BODY}}":       article_data.get("body_html", ""),
        "{{CTA_TITLE}}":          cfg["cta_title"],
        "{{CTA_TEXT}}":           cfg["cta_text"],
        "{{CTA_BUTTON_LABEL}}":   cfg["cta_button"],
        "{{SHARE_LABEL}}":        cfg["share_label"],
        "{{WHATSAPP_SHARE_TEXT}}": whatsapp_msg,
        "{{RELATED_HEADING}}":    cfg["related_heading"],
        # New image placeholders
        "{{HERO_IMAGE_URL}}":     image_url,
        "{{HERO_IMAGE_ALT}}":     image_alt,
        # Also update the OG image to use the article image
        "https://maremediterraneo.com/hero.jpg": image_url,
    }

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    return html


# ── SITEMAP UPDATE ────────────────────────────────────────────

def update_sitemap(new_slugs, today):
    if not os.path.exists(SITEMAP_PATH):
        log("sitemap.xml not found — skipping update")
        return

    with open(SITEMAP_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    date_str    = today.strftime("%Y-%m-%d")
    new_entries = ""

    for slug in new_slugs:
        url = "https://maremediterraneo.com/blog/" + slug + ".html"
        if url in content:
            continue
        entry = (
            "\n  <url>\n"
            "    <loc>" + url + "</loc>\n"
            "    <lastmod>" + date_str + "</lastmod>\n"
            "    <changefreq>monthly</changefreq>\n"
            "    <priority>0.6</priority>\n"
            "  </url>"
        )
        new_entries += entry

    if new_entries:
        content = content.replace(
            "  <!-- BLOG_ARTICLES_PLACEHOLDER -->",
            new_entries + "\n  <!-- BLOG_ARTICLES_PLACEHOLDER -->"
        )
        with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        log("Sitemap updated with " + str(len(new_slugs)) + " new URLs")


# ── ARTICLES INDEX ────────────────────────────────────────────

def update_articles_index(new_articles):
    existing        = load_json(ARTICLES_JSON, [])
    existing_slugs  = set(a.get("slug", "") for a in existing)

    added = 0
    for article in new_articles:
        if article["slug"] not in existing_slugs:
            existing.insert(0, article)
            added += 1

    save_json(ARTICLES_JSON, existing)
    log("articles.json updated — added " + str(added) + " new entries")


# ── MAIN ─────────────────────────────────────────────────────

def main():
    today       = datetime.date.today()
    date_prefix = today.strftime("%Y-%m-%d")

    log("Starting blog generation for " + date_prefix)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    if not os.path.exists(TEMPLATE_PATH):
        log("ERROR: blog/template.html not found")
        sys.exit(1)

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    topics = load_json(TOPICS_JSON, [])
    if not topics:
        log("ERROR: topics.json empty or missing")
        sys.exit(1)

    # Try RSS first, fall back to topics
    news_angle  = None
    rss_result  = fetch_rss_headline()
    if rss_result:
        log("RSS success: " + rss_result["headline"])
        news_angle = rss_result["headline"]
        if rss_result["summary"]:
            news_angle += " — " + rss_result["summary"]

    topic = pick_topic(topics)
    log("Using topic #" + str(topic["id"]) + ": " + topic["topic"])

    if news_angle:
        write_angle = (
            "Inspired by recent Salento/Puglia news: " + news_angle +
            ". Add tourism and travel context relevant to visitors."
        )
    else:
        write_angle = topic.get("angle", topic["topic"])

    # ── STEP 1: Generate the first language article (EN as master)
    #            Extract image_prompt from it, then generate image once
    log("Generating master article (EN) to extract image prompt...")
    lang_names = {"it": "Italian", "de": "German", "fr": "French", "en": "English"}

    master_prompt = ARTICLE_PROMPT.format(
        word_count=topic.get("word_count", 900),
        language="English",
        topic=topic["topic"],
        angle=write_angle,
        keywords=topic.get("target_keywords", "")
    )
    master_data = call_claude(master_prompt, "en")
    if not master_data:
        log("ERROR: Failed to generate master article")
        sys.exit(1)

    # ── STEP 2: Generate image from the prompt in the master article
    image_prompt    = master_data.get("image_prompt", "")
    topic_slug      = slugify(topic["topic"])[:40]
    image_filename  = date_prefix + "-" + topic_slug + ".jpg"
    image_local     = os.path.join(IMAGES_DIR, image_filename)
    image_web_url   = "https://maremediterraneo.com/blog/images/" + image_filename
    fallback_image  = "https://maremediterraneo.com/hero.jpg"

    if image_prompt:
        log("Generating image: " + image_prompt[:80] + "...")
        image_ok = generate_image(image_prompt, image_local)
    else:
        log("No image_prompt returned — using fallback hero.jpg")
        image_ok = False

    final_image_url = image_web_url if image_ok else fallback_image
    image_alt       = master_data.get("title", topic["topic"]) + " — Mare Mediterraneo, Salento"

    log("Image URL for all articles: " + final_image_url)

    # ── STEP 3: Generate all 4 language articles
    articles_by_lang = {"en": master_data}  # reuse master EN data

    for lang in ["it", "de", "fr"]:
        log("Generating article in: " + lang)
        prompt = ARTICLE_PROMPT.format(
            word_count=topic.get("word_count", 900),
            language=lang_names[lang],
            topic=topic["topic"],
            angle=write_angle,
            keywords=topic.get("target_keywords", "")
        )
        data = call_claude(prompt, lang)
        if data:
            articles_by_lang[lang] = data
        else:
            log("FAILED to generate " + lang + " article")

    # ── STEP 4: Build HTML files
    new_articles = []
    new_slugs    = []
    errors       = []

    for lang in LANGUAGES:
        article_data = articles_by_lang.get(lang)
        if not article_data:
            errors.append(lang)
            continue

        title_for_slug = article_data.get("title", topic["topic"])
        slug           = date_prefix + "-" + lang + "-" + slugify(title_for_slug)

        article_html = build_article_html(
            template, article_data, lang, slug, topic, today,
            final_image_url, image_alt
        )

        filename = slug + ".html"
        filepath = os.path.join(BLOG_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(article_html)

        log("Saved: " + filename)
        new_slugs.append(slug)

        new_articles.append({
            "slug":         slug,
            "lang":         lang.upper(),
            "lang_label":   LANG_CONFIG[lang]["label"],
            "title":        article_data.get("title", ""),
            "excerpt":      article_data.get("excerpt", "")[:160],
            "date":         today.strftime("%B %d, %Y"),
            "date_iso":     today.strftime("%Y-%m-%d"),
            "reading_time": article_data.get("reading_time", 5),
            "image_url":    final_image_url,   # ← NEW: used by blog index for card thumbnails
        })

    mark_topic_used(topic["id"])

    if new_articles:
        update_articles_index(new_articles)
        update_sitemap(new_slugs, today)
        log("Done. Generated " + str(len(new_articles)) + "/4 articles.")
        if errors:
            log("WARNING: Failed languages (non-fatal): " + ", ".join(errors))
    else:
        log("ERROR: No articles generated at all.")
        sys.exit(1)


if __name__ == "__main__":
    main()
