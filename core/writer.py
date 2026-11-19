import os
import re
import json
import time
import base64
import requests
import trafilatura
from ddgs import DDGS
from dotenv import load_dotenv
from core.wordpress import get_existing_posts, upload_image, create_post

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _or_headers() -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def gather_web_context(keyword: str) -> str:
    """Pull top search snippets and extract clean text from top organic pages."""
    try:
        results = DDGS().text(keyword, max_results=5)
    except Exception:
        return ""

    if not results:
        return ""

    snippets = []
    urls = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        snippets.append(f"- {title}: {body}")
        if href:
            urls.append(href)

    extracted_chunks = []
    for url in urls[:2]:
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.ok:
                text = trafilatura.extract(resp.text)
                if text:
                    extracted_chunks.append(text[:1500])
        except Exception:
            continue

    combined = "SERP SNIPPETS:\n" + "\n".join(snippets)
    if extracted_chunks:
        combined += "\n\nCOMPETITOR EXCERPTS:\n" + "\n---\n".join(extracted_chunks)
    return combined[:4500]


def _chat_completion(model: str, messages: list[dict], json_mode: bool = False) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    res = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=_or_headers(),
        json=payload,
        timeout=90,
    )
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()


def generate_seedream_image(subject: str, site_style: dict, out_path: str) -> str:
    """Generate a single image via OpenRouter Seedream 5.0 Lite using site visual DNA."""
    base_style = site_style.get("base_style", "editorial photography, natural lighting")
    palette = site_style.get("color_palette", "balanced natural tones")
    negative = site_style.get("negative_rules", "no text, no watermarks")
    aspect = site_style.get("aspect_ratio", "16:9")

    full_prompt = (
        f"{subject}. Style: {base_style}. Color palette: {palette}. "
        f"Aspect ratio {aspect}. Important constraints: {negative}."
    )

    res = requests.post(
        f"{OPENROUTER_BASE}/images/generations",
        headers=_or_headers(),
        json={
            "model": "bytedance-seed/seedream-5-0-lite",
            "prompt": full_prompt,
        },
        timeout=90,
    )
    res.raise_for_status()
    img_data = res.json()["data"][0]

    if img_data.get("b64_json"):
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(img_data["b64_json"]))
    elif img_data.get("url"):
        dl = requests.get(img_data["url"], timeout=30)
        dl.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(dl.content)

    return out_path


def process_article_job(row: dict, settings: dict, site: dict, status_cb=None) -> dict:
    """End-to-end generation + publishing pipeline for one bulk table row."""
    def update(msg: str):
        if status_cb:
            status_cb(msg)

    keyword = row["main_keyword"].strip()
    title_hint = row.get("title", "").strip()
    extra_keywords = row.get("keywords", "").strip()
    outline_hint = row.get("outline", "").strip()

    model = settings.get("model", "nvidia/nemotron-3.5-lightning")
    language = settings.get("language", "English")
    size = settings.get("article_size", "Medium")
    tone = settings.get("tone", "Informative & Engaging")
    pov = settings.get("pov", "Second Person (You)")
    hook_style = settings.get("hook_style", "Question")

    h2_count_map = {"Small": 4, "Medium": 6, "Large": 9}
    words_per_h2_map = {"Small": 250, "Medium": 350, "Large": 380}
    target_h2s = h2_count_map.get(size, 6)
    words_per_h2 = words_per_h2_map.get(size, 350)

    # 1. Optional Web Grounding & Internal Links
    web_context = ""
    if settings.get("connect_to_web"):
        update("Researching SERPs...")
        web_context = gather_web_context(keyword)

    existing_posts = []
    if settings.get("internal_linking"):
        update("Fetching internal links...")
        existing_posts = get_existing_posts(site)

    # 2. Generate Article Blueprint (JSON)
    update("Building outline...")
    plan_system = (
        "You are an expert SEO content architect. Respond ONLY with valid JSON. "
        "Do not wrap the JSON in markdown fences."
    )
    plan_user = f"""Create a structured SEO article blueprint in {language}.
Main Keyword: {keyword}
Title Hint (use or improve if provided): {title_hint or "None"}
Secondary Keywords to weave in: {extra_keywords or "None"}
User Outline Guidance: {outline_hint or "None"}
Tone: {tone}
Point of View: {pov}
Introductory Hook Style: {hook_style}
Target Number of H2 Sections: {target_h2s}

{f"LIVE WEB RESEARCH CONTEXT:{chr(10)}{web_context}" if web_context else ""}

Return a JSON object with these exact keys:
- "title": string (compelling SEO H1 title containing the main keyword)
- "slug": string (url-friendly lowercase hyphenated slug)
- "meta_description": string (max 155 characters)
- "intro_html": string (2 engaging paragraphs in <p> tags starting with a {hook_style} hook)
- "key_takeaways": array of 4 concise summary bullet strings
- "h2_sections": array of {target_h2s} objects, each with:
    - "heading": string (H2 title)
    - "brief": string (what to cover in this section)
    - "image_subject": string (a concrete, visual scene description for an editorial illustration/photo representing this section, with NO text in the scene)
- "faq": array of 4 objects with {{"question": "...", "answer": "..."}}
- "conclusion_html": string (1-2 wrapping paragraphs in <p> tags)
"""
    raw_plan = _chat_completion(model, [
        {"role": "system", "content": plan_system},
        {"role": "user", "content": plan_user},
    ], json_mode=True)

    # Clean potential markdown fences just in case
    clean_json = re.sub(r"^```(?:json)?|```$", "", raw_plan.strip(), flags=re.MULTILINE).strip()
    plan = json.loads(clean_json)

    final_title = plan.get("title") or title_hint or keyword.title()
    h2_sections = plan.get("h2_sections", [])

    # 3. Generate Images (1 Featured + 1 per 3 H2s)
    featured_media_id = None
    in_body_urls = {}  # maps H2 index -> uploaded WP image URL
    site_style = site.get("image_style", {})
    run_stamp = int(time.time())
    safe_slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")[:30]

    if settings.get("auto_images"):
        update("Generating featured image...")
        feat_path = f"workspace/{safe_slug}-{run_stamp}-featured.png"
        generate_seedream_image(f"Hero visual representing: {final_title}", site_style, feat_path)
        alt_text = keyword if settings.get("keyword_alt_text", True) else final_title
        uploaded_feat = upload_image(site, feat_path, alt_text=alt_text)
        featured_media_id = uploaded_feat["id"]

        # 1 image per 3 H2s (placed after H2 #3 [idx 2], H2 #6 [idx 5], H2 #9 [idx 8], etc.)
        target_indices = [i for i in range(2, len(h2_sections), 3)]
        for idx_num, h2_idx in enumerate(target_indices, start=1):
            update(f"Generating body image {idx_num}/{len(target_indices)}...")
            sec = h2_sections[h2_idx]
            img_subject = sec.get("image_subject") or sec.get("heading", final_title)
            body_img_path = f"workspace/{safe_slug}-{run_stamp}-sec{h2_idx}.png"
            generate_seedream_image(img_subject, site_style, body_img_path)
            uploaded_body = upload_image(site, body_img_path, alt_text=sec.get("heading", keyword))
            in_body_urls[h2_idx] = (uploaded_body["url"], sec.get("heading", keyword))

    # 4. Assemble HTML & Draft Sections
    html_parts = [plan.get("intro_html", "")]

    if settings.get("key_takeaways") and plan.get("key_takeaways"):
        items = "".join(f"<li>{item}</li>" for item in plan["key_takeaways"])
        html_parts.append(
            f'<div class="key-takeaways"><h3>Key Takeaways</h3><ul>{items}</ul></div>'
        )

    formatting_rules = []
    if settings.get("h3s"):
        formatting_rules.append("Use descriptive <h3> subheadings to break up long paragraphs.")
    if settings.get("lists"):
        formatting_rules.append("Include clean <ul> or <ol> bulleted lists where appropriate.")
    if settings.get("tables"):
        formatting_rules.append("Include a clean HTML <table> if comparing options, specs, or steps.")
    rules_str = " ".join(formatting_rules)

    links_context = ""
    if existing_posts:
        sample_links = "\n".join(f'- "{p["title"]}": {p["link"]}' for p in existing_posts[:25])
        links_context = (
            "If naturally relevant to a phrase in this section, weave in 1 internal link using "
            f'<a href="URL">anchor text</a> from this list:\n{sample_links}'
        )

    for idx, sec in enumerate(h2_sections):
        update(f"Writing section {idx + 1}/{len(h2_sections)}...")
        sec_heading = sec.get("heading", f"Section {idx + 1}")
        sec_brief = sec.get("brief", "")

        sec_prompt = f"""Write the body content (do NOT repeat the H2 heading itself) for this section of an article titled "{final_title}" in {language}.
Section H2 Topic: {sec_heading}
Section Notes: {sec_brief}
Target Length: ~{words_per_h2} words
Tone: {tone} | Point of View: {pov}
Secondary Keywords (use naturally if relevant): {extra_keywords or "None"}
Formatting Instructions: {rules_str}
{links_context}
{f"Factual Reference Context:{chr(10)}{web_context[:2000]}" if web_context else ""}

Output clean semantic HTML (<p>, <h3>, <ul>, <li>, <table>, <strong>) ONLY. No markdown, no code fences."""

        sec_html = _chat_completion(model, [
            {"role": "system", "content": "You are a skilled SEO writer outputting clean HTML body paragraphs only."},
            {"role": "user", "content": sec_prompt},
        ])
        sec_html = re.sub(r"^```(?:html)?|```$", "", sec_html.strip(), flags=re.MULTILINE).strip()

        html_parts.append(f"<h2>{sec_heading}</h2>\n{sec_html}")

        if idx in in_body_urls:
            img_url, img_alt = in_body_urls[idx]
            html_parts.append(
                f'<figure class="wp-block-image"><img src="{img_url}" alt="{img_alt}"/></figure>'
            )

    if settings.get("faq") and plan.get("faq"):
        faq_items = ["<h2>Frequently Asked Questions</h2>"]
        for qa in plan["faq"]:
            faq_items.append(f"<h3>{qa.get('question', '')}</h3><p>{qa.get('answer', '')}</p>")
        html_parts.append("\n".join(faq_items))

    if settings.get("conclusion") and plan.get("conclusion_html"):
        html_parts.append(f"<h2>Conclusion</h2>\n{plan['conclusion_html']}")

    final_html = "\n\n".join(html_parts)

    # 5. Publish to LocalWP
    update("Publishing to LocalWP...")
    post_status = settings.get("post_status") or site.get("default_status", "draft")
    post_result = create_post(
        site=site,
        title=final_title,
        html_content=final_html,
        status=post_status,
        featured_media_id=featured_media_id,
        slug=plan.get("slug"),
        excerpt=plan.get("meta_description"),
    )

    update("Done")
    return {
        "title": final_title,
        "post_id": post_result["id"],
        "post_url": post_result["link"],
        "status": post_status,
    }
