import os
import re
import json
import time
import base64
import requests
import trafilatura
import markdown
from ddgs import DDGS
from dotenv import load_dotenv
from core.wordpress import get_existing_posts, upload_image, create_post, ensure_category, ensure_tag

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
    """Fix double-escaped literal \n characters from JSON."""
    if not text:
        return ""
    return text.replace("\\n", "\n").replace("\\r", "")

def gather_web_context(keyword: str) -> str:
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

def expand_table_column(column: str, rows: list[dict], settings: dict) -> list[dict]:
    # (Leaving this unchanged from your previous working v1.1 build)
    model = settings.get("model", "nvidia/nemotron-3.5-lightning")
    language = settings.get("language", "English")
    tone = settings.get("tone", "Informative & Engaging")
    size = settings.get("article_size", "Medium")
    use_web = bool(settings.get("connect_to_web", False))
    target_h2s = {"Small": 4, "Medium": 6, "Large": 9}.get(size, 6)

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
        prompt = f'Write compelling, click-worthy SEO article titles (H1) in {language} with a "{tone}" tone for each item below.\nItems:\n{json.dumps(targets, indent=2)}\nReturn JSON:\n{{"items": [{{"id": "...", "title": "..."}}]}}'
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
        targets = [{"id": r["id"], "main_keyword": r["main_keyword"].strip(), "title": r.get("title", "").strip(), "keywords": r.get("keywords", "").strip()} for r in rows if r.get("main_keyword", "").strip() and not r.get("outline", "").strip()]
        if not targets: raise ValueError("No rows need an Outline.")
        prompt = f'Create a {target_h2s}-section H2 outline in {language} for each item.\nFormat: "H2: Intro | H2: Factor 1 | H2: Cost".\nItems:\n{json.dumps(targets, indent=2)}\nReturn JSON:\n{{"items": [{{"id": "...", "outline": "..."}}]}}'
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

    model = settings.get("model", "nvidia/nemotron-3.5-lightning")
    language = settings.get("language", "English")
    size = settings.get("article_size", "Medium")
    tone = settings.get("tone", "Informative & Engaging")
    pov = settings.get("pov", "Second Person (You)")
    hook_style = settings.get("hook_style", "Question")
    main_cat_name = settings.get("main_category", "Auto-Detect")

    target_h2s = {"Small": 4, "Medium": 6, "Large": 9}.get(size, 6)
    words_per_h2 = {"Small": 250, "Medium": 350, "Large": 380}.get(size, 350)

    web_context = ""
    if settings.get("connect_to_web"):
        update("Researching SERPs...")
        web_context = gather_web_context(keyword)

    update("Building blueprint & taxonomy...")
    plan_system = "You are an expert SEO content architect. Respond ONLY with valid JSON. Do not wrap the JSON in markdown fences."
    plan_user = f"""Create a structured SEO article blueprint in {language}.
Main Keyword: {keyword}
Title Hint: {title_hint or "None"}
Secondary Keywords: {extra_keywords or "None"}
User Outline Guidance: {outline_hint or "None"}
Tone: {tone} | POV: {pov} | Hook Style: {hook_style} | Target H2s: {target_h2s}
{f"LIVE WEB CONTEXT:{chr(10)}{web_context}" if web_context else ""}

Return a JSON object with these exact keys:
- "title": string (compelling SEO H1)
- "slug": string (url-friendly)
- "meta_description": string (max 155 chars)
- "main_category_suggestion": string (If '{main_cat_name}' is 'Auto-Detect', suggest a broad top-level pillar category. Otherwise, repeat '{main_cat_name}')
- "subcategories": array of 1-2 string names for child categories
- "tags": array of 3-5 string tags
- "intro_markdown": string (2 engaging paragraphs in Markdown starting with a {hook_style} hook)
- "key_takeaways": array of 4 concise summary bullet strings
- "h2_sections": array of {target_h2s} objects: {{"heading": "H2 title", "brief": "what to cover", "image_subject": "visual scene description (NO text)"}}
- "faq": array of 4 objects: {{"question": "...", "answer": "..."}}
- "conclusion_markdown": string (1-2 wrapping paragraphs in Markdown)
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

    # STRICT SILO INTERNAL LINKING
    existing_posts = []
    silo_links = []
    if settings.get("internal_linking"):
        update("Fetching internal links...")
        existing_posts = get_existing_posts(site)
        for p in existing_posts:
            if any(c in post_cat_ids for c in p.get("categories", [])) or any(t in post_tag_ids for t in p.get("tags", [])):
                silo_links.append(p)

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

    # ASSEMBLE MARKDOWN
    md_parts = [sanitize_json_text(plan.get("intro_markdown", ""))]

    if settings.get("key_takeaways") and plan.get("key_takeaways"):
        md_parts.append("### Key Takeaways\n" + "\n".join(f"- {item}" for item in plan["key_takeaways"]))

    formatting_rules = []
    if settings.get("h3s"): formatting_rules.append("Use ### subheadings to break up paragraphs.")
    if settings.get("lists"): formatting_rules.append("Include bullet lists where appropriate.")
    if settings.get("tables"): formatting_rules.append("Include a Markdown table if comparing options or specs.")
    rules_str = " ".join(formatting_rules)

    links_context = ""
    if silo_links:
        sample_links = "\n".join(f'- "{p["title"]}": {p["link"]}' for p in silo_links[:15])
        links_context = f"Internal Linking Options:\n{sample_links}\nINSTRUCTION: Include a Markdown link [anchor](url) ONLY if it fits naturally into a sentence. Skipping links completely is preferred over forcing an unnatural link."

    for idx, sec in enumerate(h2_sections):
        update(f"Writing section {idx + 1}/{len(h2_sections)}...")
        sec_heading = sec.get("heading", f"Section {idx + 1}")
        
        sec_prompt = f"""Write the body content (do NOT repeat the H2 heading itself) for this section of an article titled "{final_title}" in {language}.
Section Topic: {sec_heading}
Section Notes: {sec.get("brief", "")}
Target Length: ~{words_per_h2} words
Tone: {tone} | POV: {pov}
Secondary Keywords: {extra_keywords or "None"}
Formatting Rules: {rules_str}
{links_context}
{f"Factual Context:{chr(10)}{web_context[:2000]}" if web_context else ""}

Output pure Markdown ONLY (no HTML tags)."""

        sec_md = _chat_completion(model, [
            {"role": "system", "content": "You are a skilled SEO writer outputting clean, highly readable Markdown content only."},
            {"role": "user", "content": sec_prompt},
        ])
        sec_md = re.sub(r"^```(?:markdown)?|```$", "", sec_md.strip(), flags=re.MULTILINE).strip()

        md_parts.append(f"## {sec_heading}\n\n{sec_md}")
        
        if idx in in_body_urls:
            img_url, img_alt = in_body_urls[idx]
            md_parts.append(f"![{img_alt}]({img_url})")

    if settings.get("faq") and plan.get("faq"):
        md_parts.append("## Frequently Asked Questions")
        for qa in plan["faq"]:
            md_parts.append(f"### {sanitize_json_text(qa.get('question', ''))}\n{sanitize_json_text(qa.get('answer', ''))}")

    if settings.get("conclusion") and plan.get("conclusion_markdown"):
        md_parts.append(f"## Conclusion\n\n{sanitize_json_text(plan['conclusion_markdown'])}")

    final_markdown = "\n\n".join(md_parts)
    
    # CONVERT TO CLEAN HTML
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

    update("Done")
    return {
        "title": final_title,
        "post_id": post_result["id"],
        "post_url": post_result["link"],
        "status": post_status,
    }
