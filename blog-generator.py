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
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
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
    # Puglia / Salento local news
    "https://www.leccenews24.it/feed",
    "https://www.brindisireport.it/feed",
    # Italian national travel
    "https://www.viaggiart.com/feed",
    "https://feeds.feedburner.com/turismo-italia",
    # International travel — high quality open feeds
    "https://www.theguardian.com/travel/italy/rss",
    "https://www.theguardian.com/travel/rss",
    "https://feeds.lonelyplanet.com/lonelyplanet/news",
    # Official Italian tourism
    "https://www.italia.it/en/rss.xml",
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
  "image_search": "2-4 English keywords for searching a travel photo on Unsplash that would illustrate this article — e.g. Lecce baroque, Salento beach, Puglia olive trees, Gallipoli sea"
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


def fetch_unsplash_image(search_query):
    """
    Search Unsplash for a photo matching the query.
    Returns dict with {url, photographer_name, photographer_url} or None.
    Complies with Unsplash API guidelines:
      - Hotlinks to original Unsplash URL (no download to server)
      - Triggers download endpoint
      - Returns attribution data for caption
    """
    if not UNSPLASH_ACCESS_KEY:
        log("Skipping Unsplash — no UNSPLASH_ACCESS_KEY set")
        return None

    try:
        # Search for a photo
        search_url = (
            "https://api.unsplash.com/search/photos"
            "?query=" + urllib.parse.quote(search_query) +
            "&per_page=1&orientation=landscape"
            "&content_filter=high"
        )
        req = urllib.request.Request(search_url)
        req.add_header("Authorization", "Client-ID " + UNSPLASH_ACCESS_KEY)
        req.add_header("User-Agent", "MareMediterraneo-BlogBot/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        if not results:
            log("Unsplash: no results for query: " + search_query)
            return None

        photo      = results[0]
        photo_id   = photo["id"]
        # Use the "regular" size URL — good quality, not too large
        image_url  = photo["urls"]["regular"]
        # Attribution data (required by Unsplash guidelines)
        photographer_name = photo["user"]["name"]
        photographer_username = photo["user"]["username"]
        photographer_url = (
            "https://unsplash.com/@" + photographer_username +
            "?utm_source=mare_mediterraneo&utm_medium=referral"
        )
        unsplash_url = "https://unsplash.com/?utm_source=mare_mediterraneo&utm_medium=referral"

        # Trigger download endpoint (required by Unsplash guidelines)
        try:
            dl_url = "https://api.unsplash.com/photos/" + photo_id + "/download"
            dl_req = urllib.request.Request(dl_url)
            dl_req.add_header("Authorization", "Client-ID " + UNSPLASH_ACCESS_KEY)
            dl_req.add_header("User-Agent", "MareMediterraneo-BlogBot/1.0")
            urllib.request.urlopen(dl_req, timeout=10)
            log("Unsplash download event triggered for photo: " + photo_id)
        except Exception as e:
            log("Unsplash download trigger failed (non-fatal): " + str(e))

        log("Unsplash image found: " + image_url[:80])
        return {
            "url": image_url,
            "photographer_name": photographer_name,
            "photographer_url": photographer_url,
            "unsplash_url": unsplash_url,
            "caption": (
                'Photo by <a href="' + photographer_url + '" target="_blank" rel="noopener">'
                + photographer_name + '</a> on '
                + '<a href="' + unsplash_url + '" target="_blank" rel="noopener">Unsplash</a>'
            )
        }

    except urllib.error.HTTPError as e:
        log("Unsplash HTTP error " + str(e.code) + ": " + e.read().decode("utf-8", errors="replace")[:200])
        return None
    except Exception as e:
        log("Unsplash error: " + str(e))
        return None


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

def build_article_html(template, article_data, lang, slug, topic_info, today, image_url, image_alt, image_caption=None):
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
        "{{HERO_IMAGE_CAPTION}}": image_caption or "Mare Mediterraneo — Torre Chianca, Salento · 400m from the sea · 15 min from Lecce",
        # OG/Twitter/Schema images use {{HERO_IMAGE_URL}} placeholder — handled above
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


# ── BLOG INDEX STATIC LINKS (SEO) ────────────────────────────

def rebuild_blog_index():
    """
    Injects a hidden <div> with static <a href> links to every article
    into blog/index.html, replacing any previous injection.
    This makes all article URLs visible to Google without JS execution,
    while leaving the existing JS-rendered card layout completely untouched.
    """
    index_path = os.path.join(BLOG_DIR, "index.html")
    if not os.path.exists(index_path):
        log("blog/index.html not found — skipping static link injection")
        return

    articles = load_json(ARTICLES_JSON, [])
    if not articles:
        log("articles.json empty — skipping static link injection")
        return

    # Build one <a> per article
    links = []
    for a in articles:
        slug  = a.get("slug", "")
        title = a.get("title", slug)
        lang  = a.get("lang_label", "")
        if not slug:
            continue
        url = "https://maremediterraneo.com/blog/" + slug + ".html"
        links.append('    <a href="' + url + '">' + title + ' (' + lang + ')</a>')

    static_block = (
        '\n<!-- SEO_STATIC_LINKS_START -->\n'
        '<div style="position:absolute;width:1px;height:1px;overflow:hidden;'
        'clip:rect(0,0,0,0);white-space:nowrap;" aria-hidden="true">\n'
        + "\n".join(links) + "\n"
        "</div>\n"
        "<!-- SEO_STATIC_LINKS_END -->\n"
    )

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove any previous injection
    content = re.sub(
        r"\n<!-- SEO_STATIC_LINKS_START -->.*?<!-- SEO_STATIC_LINKS_END -->\n",
        "",
        content,
        flags=re.DOTALL
    )

    # Inject just before </body>
    if "</body>" in content:
        content = content.replace("</body>", static_block + "</body>")
    else:
        # Fallback: append at end of file
        content = content + static_block

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)

    log("blog/index.html updated with " + str(len(links)) + " static SEO links")


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

    # ── STEP 2: Fetch image from Unsplash using search keywords from master article
    image_search   = master_data.get("image_search", topic["topic"])
    fallback_image = "https://maremediterraneo.com/hero.jpg"
    image_caption  = "Mare Mediterraneo — Torre Chianca, Salento · 400m from the sea · 15 min from Lecce"

    if image_search:
        # Try full search first, then progressively simpler queries
        search_queries = [
            image_search,
            image_search.split(",")[0].strip(),  # just first keyword group
            topic["topic"].split("—")[0].strip() + " Italy",  # topic name + Italy
        ]
        unsplash_result = None
        for sq in search_queries:
            if not sq or len(sq) < 3:
                continue
            log("Searching Unsplash: " + sq)
            unsplash_result = fetch_unsplash_image(sq)
            if unsplash_result:
                break
    else:
        unsplash_result = None

    if unsplash_result:
        final_image_url = unsplash_result["url"]
        image_caption   = unsplash_result["caption"]
        log("Unsplash image URL: " + final_image_url[:80])
    else:
        # Fallback: try topic name as search query
        # Fallback: use generic Puglia/Salento travel terms instead of specific topic
        fallback_queries = [
            "Puglia Italy coast beach",
            "Salento Italy sea",
            "Puglia travel Italy",
            "Italian coast mediterranean"
        ]
        fallback_result = None
        for fq in fallback_queries:
            log("Trying fallback Unsplash search: " + fq)
            fallback_result = fetch_unsplash_image(fq)
            if fallback_result:
                break
        if fallback_result:
            final_image_url = fallback_result["url"]
            image_caption   = fallback_result["caption"]
            log("Fallback Unsplash image found")
        else:
            final_image_url = fallback_image
            log("No Unsplash image found — using hero.jpg")

    image_alt = master_data.get("title", topic["topic"]) + " — Mare Mediterraneo, Salento"
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
            final_image_url, image_alt, image_caption
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
        rebuild_blog_index()
        log("Done. Generated " + str(len(new_articles)) + "/4 articles.")
        if errors:
            log("WARNING: Failed languages (non-fatal): " + ", ".join(errors))
    else:
        log("ERROR: No articles generated at all.")
        sys.exit(1)


if __name__ == "__main__":
    main()
