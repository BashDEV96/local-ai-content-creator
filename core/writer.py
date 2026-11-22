import os
import re
import json
import time
import base64
import random
import datetime
import requests
import trafilatura
import markdown
from ddgs import DDGS
from dotenv import load_dotenv
from core.wordpress import upload_image, create_post, ensure_category, ensure_tag

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

def _or_headers() -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

def _parse_json_response(raw: str) -> dict:
    clean = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    return json.loads(clean)

def sanitize_json_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("\\n", "\n").replace("\\r", "")

def gather_web_context(keyword: str) -> dict:
    try:
        results = DDGS().text(keyword, max_results=5)
    except Exception:
        return {"text": "", "status": "Web search failed or blocked."}
    if not results:
        return {"text": "", "status": "No SERP results found."}
    snippets = []
    urls = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        snippets.append(f"- {title}: {body}")
        if href:
            urls.append(href)
    extracted = []
    for url in urls[:2]:
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.ok:
                text = trafilatura.extract(resp.text)
                if text:
                    extracted.append(text[:1500])
        except Exception:
            continue
    combined = "SERP SNIPPETS:\n" + "\n".join(snippets)
    if extracted:
        combined += "\n\nCOMPETITOR EXCERPTS:\n" + "\n---\n".join(extracted)
    return {
        "text": combined[:4500],
        "status": f"Scraped {len(snippets)} SERPs + {len(extracted)} pages"
    }

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
        timeout=180,
    )
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()

def expand_table_column(column: str, rows: list[dict], settings: dict) -> list[dict]:
    model = settings.get("model", "nvidia/nemotron-3.5-lightning")
    language = settings.get("language", "English")
    tone = settings.get("tone", "Informative & Engaging")
    use_web = bool(settings.get("connect_to_web", False))
    current_year = datetime.datetime.now().year
    
    sys_msg = "You are an expert SEO strategist. Respond ONLY with valid JSON. Do not wrap the JSON in markdown fences."

    if column == "main_keyword":
        existing_kws = [r["main_keyword"].strip() for r in rows if r.get("main_keyword", "").strip()]
        if not existing_kws: raise ValueError("Enter at least one seed Main Keyword first.")
        empty_indices = [i for i, r in enumerate(rows) if not r.get("main_keyword", "").strip()]
        if not empty_indices: raise ValueError("No empty rows found. Click '+ Add Row' first.")
        seed = existing_kws[0]
        needed = len(empty_indices)
        serp_hint = ""
        if use_web:
            try:
                hits = DDGS().text(seed, max_results=5)
                if hits: serp_hint = "Live search topics:\n" + "\n".join(f"- {h.get('title', '')}" for h in hits)
            except Exception: pass
        prompt = f'Generate {needed} distinct, high-intent SEO main keywords related to the seed topic "{seed}" in {language}.\nDo NOT repeat any of these: {json.dumps(existing_kws)}\n{serp_hint}\nReturn JSON:\n{{"keywords": ["...", "..."]}}'
        raw = _chat_completion(model, [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}], json_mode=True)
        generated = _parse_json_response(raw).get("keywords", [])
        for idx, kw in zip(empty_indices, generated):
            rows[idx]["main_keyword"] = str(kw).strip()
        return rows

    if column == "title":
        targets = [{"id": r["id"], "main_keyword": r["main_keyword"].strip(), "keywords": r.get("keywords", "").strip()} for r in rows if r.get("main_keyword", "").strip() and not r.get("title", "").strip()]
        if not targets: raise ValueError("No rows need a Title.")
        
        article_type = settings.get("article_type", "Blog")
        prompt = f'Write compelling, click-worthy SEO article titles (H1) for a "{article_type}" in {language} with a "{tone}" tone for each item below.\nCurrent Year: {current_year} (Use this if including a date).\nCRITICAL TITLE RULES: NEVER use colons (:), em dashes (—), en dashes (–), or hyphens (-) anywhere in the title.\n(Good: "How to Make ISK Fast in Eve Online for Beginners", Bad: "Eve Online: How to Make ISK Fast - Beginners Guide")\nItems:\n{json.dumps(targets, indent=2)}\nReturn JSON:\n{{"items": [{{"id": "...", "title": "..."}}]}}'
        
        raw = _chat_completion(model, [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}], json_mode=True)
        result_map = {item["id"]: item["title"] for item in _parse_json_response(raw).get("items", []) if "id" in item}
        for r in rows:
            if r["id"] in result_map: r["title"] = str(result_map[r["id"]]).strip()
        return rows

    if column == "keywords":
        targets = []
        for r in rows:
            kw = r.get("main_keyword", "").strip()
            if kw and not r.get("keywords", "").strip():
                serp_terms = ""
                if use_web:
                    try:
                        hits = DDGS().text(kw, max_results=3)
                        serp_terms = " | ".join(h.get("body", "")[:120] for h in hits)
                    except Exception: pass
                targets.append({"id": r["id"], "main_keyword": kw, "title": r.get("title", "").strip(), "serp_context": serp_terms})
        if not targets: raise ValueError("No rows need Secondary Keywords.")
        prompt = f'For each item, generate 8 to 12 comma-separated semantic/NLP keywords in {language}.\nItems:\n{json.dumps(targets, indent=2)}\nReturn JSON:\n{{"items": [{{"id": "...", "keywords": "..."}}]}}'
        raw = _chat_completion(model, [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}], json_mode=True)
        result_map = {item["id"]: item["keywords"] for item in _parse_json_response(raw).get("items", []) if "id" in item}
        for r in rows:
            if r["id"] in result_map: r["keywords"] = str(result_map[r["id"]]).strip()
        return rows

    if column == "outline":
        size = settings.get("article_size", "Medium")
        article_type = settings.get("article_type", "Blog")
        h2_ranges = {"X-Small": (2, 5), "Small": (5, 8), "Medium": (9, 12), "Large": (13, 16)}
        min_h2, max_h2 = h2_ranges.get(size, (9, 12))
        target_h2s = random.randint(min_h2, max_h2)

        targets = [{"id": r["id"], "main_keyword": r["main_keyword"].strip(), "title": r.get("title", "").strip(), "keywords": r.get("keywords", "").strip()} for r in rows if r.get("main_keyword", "").strip() and not r.get("outline", "").strip()]
        if not targets: raise ValueError("No rows need an Outline.")
        
        prompt = f'Create a {target_h2s}-section H2 outline for a {article_type} in {language} for each item.\nFormat: "H2: Core Topic One | H2: Key Factors | H2: Costs and Pricing".\nCRITICAL: Do NOT include an "Introduction" or "Overview" heading. Start directly with the first topical section.\nItems:\n{json.dumps(targets, indent=2)}\nReturn JSON:\n{{"items": [{{"id": "...", "outline": "..."}}]}}'
        
        raw = _chat_completion(model, [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}], json_mode=True)
        result_map = {item["id"]: item["outline"] for item in _parse_json_response(raw).get("items", []) if "id" in item}
        for r in rows:
            if r["id"] in result_map: r["outline"] = str(result_map[r["id"]]).strip()
        return rows

    raise ValueError(f"Unsupported column: {column}")

def generate_seedream_image(subject: str, site_style: dict, out_path: str) -> str:
    base_style = site_style.get("base_style", "editorial photography, natural lighting")
    palette = site_style.get("color_palette", "balanced natural tones")
    negative = site_style.get("negative_rules", "no text, no watermarks")
    aspect = site_style.get("aspect_ratio", "16:9")
    full_prompt = f"{subject}. Style: {base_style}. Color palette: {palette}. Aspect ratio {aspect}. Constraints: {negative}."
    res = requests.post(f"{OPENROUTER_BASE}/images/generations", headers=_or_headers(), json={"model": "bytedance-seed/seedream-5-0-lite", "prompt": full_prompt}, timeout=90)
    res.raise_for_status()
    img_data = res.json()["data"][0]
    if img_data.get("b64_json"):
        with open(out_path, "wb") as f: f.write(base64.b64decode(img_data["b64_json"]))
    elif img_data.get("url"):
        dl = requests.get(img_data["url"], timeout=30)
        dl.raise_for_status()
        with open(out_path, "wb") as f: f.write(dl.content)
    return out_path

def process_article_job(row: dict, settings: dict, site: dict, status_cb=None) -> dict:
    def update(msg: str):
        if status_cb: status_cb(msg)

    keyword = row["main_keyword"].strip()
    title_hint = row.get("title", "").strip()
    extra_keywords = row.get("keywords", "").strip()
    outline_hint = row.get("outline", "").strip()
    current_year = datetime.datetime.now().year
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")

    model = settings.get("model", "nvidia/nemotron-3.5-lightning")
    language = settings.get("language", "English")
    size = settings.get("article_size", "Medium")
    article_type = settings.get("article_type", "Blog")
    tone = settings.get("tone", "Informative & Engaging")
    pov = settings.get("pov", "Second Person (You)")
    hook_style = settings.get("hook_style", "Question")
    main_cat_name = settings.get("main_category", "Auto-Detect")

    h2_ranges = {"X-Small": (2, 5), "Small": (5, 8), "Medium": (9, 12), "Large": (13, 16)}
    min_h2, max_h2 = h2_ranges.get(size, (9, 12))
    target_h2s = random.randint(min_h2, max_h2)

    web_context = ""
    if settings.get("connect_to_web"):
        update("Researching SERPs...")
        wc_data = gather_web_context(keyword)
        web_context = wc_data["text"]
        update(wc_data["status"])

    update("Building blueprint & taxonomy...")
    plan_system = "You are an expert SEO content architect. Respond ONLY with valid JSON. Do not wrap the JSON in markdown fences."
    
    schema_lines = [
        '- "title": string (compelling SEO H1. NEVER use colons (:), dashes (—/–), or hyphens (-) anywhere in the title)',
        '- "slug": string (url-friendly)',
        '- "meta_description": string (max 155 chars)',
        f'- "main_category_suggestion": string (If \'{main_cat_name}\' is \'Auto-Detect\', suggest a broad top-level pillar category. Otherwise, repeat \'{main_cat_name}\')',
        '- "subcategories": array of 1-2 string names for child categories',
        '- "tags": array of 3-5 string tags',
    ]
    if settings.get("key_takeaways"):
        schema_lines.append('- "key_takeaways": array of 4 concise summary bullet strings')
    
    schema_lines.append(f'- "h2_sections": array of {target_h2s} objects: {{"heading": "H2 title (NO \'Introduction\' or \'Overview\')", "brief": "what to cover", "image_subject": "visual scene description (NO text)"}}')
    
    if settings.get("faq"):
        schema_lines.append('- "faq": array of 4 objects: {"question": "...", "answer": "..."}')
        
    schema_str = "\n".join(schema_lines)

    plan_user = f"""Create a structured SEO article blueprint for a '{article_type}' in {language}.
Main Keyword: {keyword}
Title Hint: {title_hint or "None"}
Secondary Keywords: {extra_keywords or "None"}
User Outline Guidance: {outline_hint or "None"}
Tone: {tone} | POV: {pov} | Hook Style: {hook_style} | Target H2s: {target_h2s}
Current Year: {current_year} (Use this if including dates/years)
{f"LIVE WEB CONTEXT:{chr(10)}{web_context}" if web_context else ""}

Return a JSON object with these exact keys:
{schema_str}
"""
    raw_plan = _chat_completion(model, [{"role": "system", "content": plan_system}, {"role": "user", "content": plan_user}], json_mode=True)
    plan = _parse_json_response(raw_plan)

    final_title = plan.get("title") or title_hint or keyword.title()
    h2_sections = plan.get("h2_sections", [])

    update("Syncing Taxonomy to WP...")
    cat_to_use = plan.get("main_category_suggestion", keyword) if main_cat_name == "Auto-Detect" else main_cat_name
    main_cat_id = ensure_category(site, cat_to_use)
    
    post_cat_ids = [main_cat_id] if main_cat_id else []
    for sub in plan.get("subcategories", []):
        sid = ensure_category(site, sub, parent_id=main_cat_id)
        if sid: post_cat_ids.append(sid)
        
    post_tag_ids = []
    for tag in plan.get("tags", []):
        tid = ensure_tag(site, tag)
        if tid: post_tag_ids.append(tid)

    featured_media_id = None
    in_body_urls = {}
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

        target_indices = [i for i in range(2, len(h2_sections), 3)]
        for idx_num, h2_idx in enumerate(target_indices, start=1):
            update(f"Generating body image {idx_num}/{len(target_indices)}...")
            sec = h2_sections[h2_idx]
            img_subject = sec.get("image_subject") or sec.get("heading", final_title)
            body_img_path = f"workspace/{safe_slug}-{run_stamp}-sec{h2_idx}.png"
            generate_seedream_image(img_subject, site_style, body_img_path)
            uploaded_body = upload_image(site, body_img_path, alt_text=sec.get("heading", keyword))
            in_body_urls[h2_idx] = (uploaded_body["url"], sec.get("heading", keyword))

    update("Writing full article (One-Shot Draft)...")
    
    writer_plan = {k: v for k, v in plan.items()}
    writer_plan["h2_sections"] = [{k: v for k, v in sec.items() if k != "image_subject"} for sec in plan.get("h2_sections", [])]

    formatting_rules = []
    if settings.get("h3s"): formatting_rules.append("Use 2-3 `###` subheadings inside EVERY `##` section to ensure deep coverage.")
    if settings.get("lists"): formatting_rules.append("Include bullet lists where appropriate.")
    if settings.get("tables"): formatting_rules.append("Include Markdown tables when comparing options, specs, or timelines. ALWAYS leave a blank line before and after every table so it formats correctly.")
    
    formatting_rules.append("Write short, engaging paragraphs for mobile readability (mostly 2 to 3 sentences). Do NOT make every single sentence its own paragraph. Separate paragraphs with a blank line.")
    formatting_rules.append("NEVER output Markdown image tags (`![...]`), HTML `<img>` tags, or image placeholders. Images are injected automatically by the system.")
    
    rules_str = " ".join(formatting_rules)

    article_flow = ["Intro hook"]
    if settings.get("key_takeaways"): article_flow.append("Key Takeaways")
    article_flow.append("all H2s")
    if settings.get("faq"): article_flow.append("FAQ")
    if settings.get("conclusion"): article_flow.append("Conclusion")
    flow_str = ", ".join(article_flow)

    body_prompt = f"""Write the complete, highly detailed Markdown article for "{final_title}" in {language}.

Article Type: {article_type}
Tone: {tone} | POV: {pov} | Hook Style: {hook_style}
Secondary Keywords: {extra_keywords or "None"}
Formatting Rules: {rules_str}
Current Year: {current_year}

Here is the EXACT structural blueprint you MUST follow from start to finish:
{json.dumps(writer_plan, indent=2)}

INSTRUCTIONS:
1. Write the ENTIRE article in one go ({flow_str}).
2. DO NOT output JSON. Output pure Markdown ONLY.
3. DO NOT pad with fluff. Use actionable details, examples, and deep expertise.
4. Use exactly `## ` (two hashes and a space) for all main sections to ensure correct parsing.
5. NEVER start the article with an H1 (# Title) or an 'Introduction' heading. WordPress adds the title automatically. Start directly with the opening hook paragraphs BEFORE the first topical H2.

{f"Factual Context:{chr(10)}{web_context[:3000]}" if web_context else ""}"""

    raw_markdown = _chat_completion(model, [
        {"role": "system", "content": "You are a master SEO content writer. You output clean, highly readable Markdown content only."},
        {"role": "user", "content": body_prompt},
    ])
    
    final_markdown = re.sub(r"^```(?:markdown)?|```$", "", raw_markdown.strip(), flags=re.MULTILINE).strip()
    final_markdown = re.sub(r'^#\s+.*?\n+', '', final_markdown.lstrip(), count=1)

    if in_body_urls:
        blocks = re.split(r'(^##\s+.*$)', final_markdown, flags=re.MULTILINE)
        for h2_idx, (img_url, img_alt) in in_body_urls.items():
            block_idx = (h2_idx * 2) + 2
            if block_idx < len(blocks):
                blocks[block_idx] = f"\n\n![{img_alt}]({img_url})\n\n" + blocks[block_idx].lstrip()
        final_markdown = "".join(blocks)
    
    # CONVERT TO HTML & PUBLISH FIRST
    final_html = markdown.markdown(final_markdown, extensions=['tables', 'fenced_code'])

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
        categories=list(set(post_cat_ids)),
        tags=list(set(post_tag_ids))
    )

    # SAVE ENRICHED MARKDOWN TO DISK
    update("Saving Enriched Markdown locally...")
    os.makedirs("workspace/articles", exist_ok=True)
    md_file_path = f"workspace/articles/{safe_slug}-{run_stamp}.md"
    
    tags_yaml = "\n  - " + "\n  - ".join(plan.get("tags", [])) if plan.get("tags") else "[]"
    subcats_yaml = "\n  - " + "\n  - ".join(plan.get("subcategories", [])) if plan.get("subcategories") else "[]"
    word_count = len(final_markdown.split())
    site_url = site.get("url", "unknown")
    post_id = post_result.get("id", "")
    post_url = post_result.get("link", "")

    frontmatter = f"""---
title: "{final_title}"
slug: "{plan.get('slug', safe_slug)}"
description: "{plan.get('meta_description', '')}"
category: "{cat_to_use}"
subcategories: {subcats_yaml}
tags: {tags_yaml}
date: {current_date}
article-type: "{article_type}"
word-count: {word_count}
status: "{post_status}"
site: "{site_url}"
post-id: {post_id}
post-url: "{post_url}"
---

"""
    with open(md_file_path, "w", encoding="utf-8") as md_file:
        md_file.write(frontmatter + final_markdown)

    update("Done")
    return {
        "title": final_title,
        "post_id": post_id,
        "post_url": post_url,
        "status": post_status,
    }
