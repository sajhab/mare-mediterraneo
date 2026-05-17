#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch-blog-articles.py
Mare Mediterraneo — One-time script to add responsive image CSS to all existing blog articles.

Run from your repo root:
    python patch-blog-articles.py

What it does:
- Scans all HTML files in blog/ (skips index.html and template.html)
- Injects responsive image CSS into the <style> block
- Ensures property photo section exists with correct markup
- Reports how many files were patched
"""

import os
import re

BLOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog")

# ── Responsive CSS to inject ──────────────────────────────────────────────────
RESPONSIVE_CSS = """
    /* ── RESPONSIVE IMAGES — patched by patch-blog-articles.py ── */
    .hero-image-placeholder {
      width: 100%;
      aspect-ratio: 16 / 7;
      overflow: hidden;
      display: block;
      background: linear-gradient(135deg, #0F0F1A 0%, rgba(200,150,62,0.06) 100%);
      border: 1px solid rgba(200,185,154,0.15);
      border-radius: 2px;
    }
    .hero-image-placeholder img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center 30%;
      display: block;
    }
    .property-photo-section {
      margin: 48px 0 0;
    }
    .property-photo-section img {
      width: 100%;
      height: auto;
      object-fit: contain;
      object-position: center center;
      display: block;
      border-radius: 2px;
      background: #0F0F1A;
    }
    .property-photo-caption {
      font-size: 0.75rem;
      color: rgba(232,221,208,0.5);
      margin-top: 8px;
      letter-spacing: 0.06em;
      text-align: center;
    }
    /* Desktop — full bleed cinematic */
    @media (min-width: 900px) {
      .hero-area { max-width: 100%; padding: 0; margin-bottom: 56px; }
      .hero-image-placeholder {
        aspect-ratio: 21 / 7;
        border-radius: 0;
        border-left: none;
        border-right: none;
      }
      .property-photo-section {
        max-width: 700px;
        margin-left: auto;
        margin-right: auto;
      }
      .property-photo-section img {
        aspect-ratio: auto;
        width: 100%;
        height: auto;
        object-fit: contain;
        object-position: center center;
        border-radius: 2px;
        max-height: 480px;
      }
    }
    /* Tablet */
    @media (max-width: 899px) {
      .hero-image-placeholder { aspect-ratio: 4 / 3; }
      .property-photo-section img { aspect-ratio: 3 / 2; }
    }
    /* Mobile */
    @media (max-width: 580px) {
      .hero-image-placeholder { aspect-ratio: 1 / 1; }
      .property-photo-section img { aspect-ratio: 4 / 3; }
    }
"""

# ── Property photo HTML (added if missing) ────────────────────────────────────
PROPERTY_PHOTO_HTML = """
    <!-- PROPERTY PHOTO — always shows the house -->
    <div class="property-photo-section">
      <img src="https://maremediterraneo.com/hero.jpg"
           alt="Mare Mediterraneo — Suite Pietra and Suite Cielo, Torre Chianca, Salento"
           loading="lazy">
      <p class="property-photo-caption">Mare Mediterraneo — Torre Chianca, Salento · Suite Pietra &amp; Suite Cielo · 400m from the sea</p>
    </div>
"""

MARKER = "/* ── RESPONSIVE IMAGES — patched"

def patch_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    changed = False

    # 1. Inject responsive CSS if not already patched
    if MARKER not in html:
        # Find last </style> before </head>
        head_end = html.find("</head>")
        style_close = html.rfind("</style>", 0, head_end if head_end > 0 else len(html))
        if style_close > 0:
            html = html[:style_close] + RESPONSIVE_CSS + html[style_close:]
            changed = True

    # 2. Fix old hero-image-placeholder inline style if present
    # Old: style="width:100%;height:100%;object-fit:cover;border-radius:2px;"
    # New: remove inline style — let CSS handle it
    old_img_style = 'style="width:100%;height:100%;object-fit:cover;border-radius:2px;"'
    new_img_style = 'style="width:100%;height:100%;object-fit:cover;object-position:center 30%;display:block;"'
    if old_img_style in html:
        html = html.replace(old_img_style, new_img_style)
        changed = True

    # 3. Fix old hero-image-placeholder that uses fixed height instead of aspect-ratio
    # Replace height:280px with aspect-ratio via CSS (already done via injected CSS above)
    # Also fix the container div if it has inline height
    html = re.sub(
        r'(class="hero-image-placeholder"[^>]*style=")[^"]*(")',
        r'\1width:100%;\2',
        html
    )

    # 4. Add property photo section if missing (before booking-cta)
    if 'property-photo-section' not in html and 'booking-cta' in html:
        html = html.replace(
            '<!-- BOOKING CTA -->',
            PROPERTY_PHOTO_HTML + '\n    <!-- BOOKING CTA -->'
        )
        changed = True

    # 5. Fix old property photo inline style if already there
    old_prop_style = 'style="width:100%;height:100%;object-fit:cover;border-radius:2px;"'
    if old_prop_style in html:
        html = html.replace(old_prop_style, '')
        changed = True

    if changed:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    return changed


def main():
    if not os.path.isdir(BLOG_DIR):
        print("ERROR: blog/ directory not found. Run from repo root.")
        return

    skip = {"index.html", "template.html"}
    files = [
        f for f in os.listdir(BLOG_DIR)
        if f.endswith(".html") and f not in skip
    ]

    if not files:
        print("No article HTML files found in blog/")
        return

    print(f"Found {len(files)} article files to patch...\n")

    patched = 0
    skipped = 0

    for filename in sorted(files):
        filepath = os.path.join(BLOG_DIR, filename)
        try:
            changed = patch_file(filepath)
            if changed:
                print(f"  ✅ Patched: {filename}")
                patched += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  ❌ ERROR on {filename}: {e}")

    print(f"\nDone. Patched {patched} files, {skipped} already up to date.")
    print("Now run: python push_to_github.py (if blog/ articles are in FILES_TO_PUSH)")
    print("Or commit manually: git add blog/ && git commit -m 'patch: responsive images on all articles' && git push")


if __name__ == "__main__":
    main()
