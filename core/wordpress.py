import os
import html
import requests

def get_categories(site: dict) -> list[dict]:
    """Fetch existing categories from LocalWP."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    try:
        res = requests.get(
            f"{wp_url}/wp-json/wp/v2/categories",
            auth=auth,
            params={"per_page": 100, "_fields": "id,name,parent"},
            timeout=15,
        )
        res.raise_for_status()
        return [{"id": c["id"], "name": html.unescape(c.get("name", "")), "parent": c.get("parent", 0)} for c in res.json()]
    except Exception:
        return []

def ensure_category(site: dict, name: str, parent_id: int = 0) -> int:
    """Find or create a category, optionally nesting it under a parent."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    
    existing = get_categories(site)
    for c in existing:
        if c["name"].lower() == name.lower() and c["parent"] == parent_id:
            return c["id"]
    
    try:
        res = requests.post(f"{wp_url}/wp-json/wp/v2/categories", auth=auth, json={"name": name, "parent": parent_id}, timeout=15)
        if res.status_code == 201:
            return res.json()["id"]
        elif res.status_code == 400 and "term_exists" in res.text:
            return res.json().get("data", {}).get("term_id", 0)
    except Exception:
        pass
    return 0

def ensure_tag(site: dict, name: str) -> int:
    """Find or create a tag."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    try:
        res = requests.post(f"{wp_url}/wp-json/wp/v2/tags", auth=auth, json={"name": name}, timeout=15)
        if res.status_code == 201:
            return res.json()["id"]
        elif res.status_code == 400 and "term_exists" in res.text:
            return res.json().get("data", {}).get("term_id", 0)
    except Exception:
        pass
    
    try:
        res = requests.get(f"{wp_url}/wp-json/wp/v2/tags", auth=auth, params={"search": name, "_fields": "id,name"}, timeout=15)
        if res.ok and len(res.json()) > 0:
            return res.json()[0]["id"]
    except Exception:
        pass
    return 0

def get_existing_posts(site: dict, limit: int = 100) -> list[dict]:
    """Fetch existing post titles, URLs, and taxonomy IDs for strict silo internal linking."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    try:
        res = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            auth=auth,
            params={"per_page": limit, "status": "publish", "_fields": "title,link,categories,tags"},
            timeout=15,
        )
        res.raise_for_status()
        posts = []
        for item in res.json():
            raw_title = item.get("title", {}).get("rendered", "")
            link = item.get("link", "")
            if raw_title and link:
                posts.append({
                    "title": html.unescape(raw_title), 
                    "link": link,
                    "categories": item.get("categories", []),
                    "tags": item.get("tags", [])
                })
        return posts
    except Exception:
        return []

def upload_image(site: dict, image_path: str, alt_text: str = "") -> dict:
    """Upload a local image to LocalWP Media Library and attach SEO alt-text."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    filename = os.path.basename(image_path)

    with open(image_path, "rb") as f:
        media_res = requests.post(
            f"{wp_url}/wp-json/wp/v2/media",
            auth=auth,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "image/png",
            },
            data=f.read(),
            timeout=45,
        )
    media_res.raise_for_status()
    data = media_res.json()
    media_id = data["id"]
    source_url = data["source_url"]

    if alt_text:
        requests.post(
            f"{wp_url}/wp-json/wp/v2/media/{media_id}",
            auth=auth,
            json={"alt_text": alt_text},
            timeout=15,
        )

    return {"id": media_id, "url": source_url}

def create_post(
    site: dict,
    title: str,
    html_content: str,
    status: str = "draft",
    featured_media_id: int | None = None,
    slug: str | None = None,
    excerpt: str | None = None,
    categories: list[int] | None = None,
    tags: list[int] | None = None,
) -> dict:
    """Create a post on LocalWP, assigning it to its siloed categories and tags."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])

    payload = {
        "title": title,
        "content": html_content,
        "status": status,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    if slug:
        payload["slug"] = slug
    if excerpt:
        payload["excerpt"] = excerpt
    if categories:
        payload["categories"] = categories
    if tags:
        payload["tags"] = tags

    res = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts",
        auth=auth,
        json=payload,
        timeout=30,
    )
    res.raise_for_status()
    data = res.json()
    return {"id": data["id"], "link": data.get("link", "")}
