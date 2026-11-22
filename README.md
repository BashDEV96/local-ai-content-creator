# Local SEO Bulk Engine (v1.7)

A robust, Python-based SEO content automation pipeline designed to generate highly-structured, mobile-optimized blog articles for WordPress (via LocalWP) while simultaneously archiving enriched, Obsidian-ready Markdown files locally. 

Built around OpenRouter and visual generation APIs, this engine handles the heavy lifting of content architecture, taxonomy, and visual generation.

---

## 🛑 Real Talk: The "AI Slop" Disclaimer

Let’s be brutally honest: if you fire up this tool, generate 50 articles, publish them blindly, and expect to dominate Google, you are going to be disappointed. 

Relying on this (or any AI tool right now) as your *sole* content creation strategy without a **human in the loop** is ludicrous. Here is the reality of AI SEO in its current state:

* **The "Human in the Loop" Requirement:** Without human editing, fact-checking, and manual SEO tweaking, pure AI output often degrades into generic "AI slop." AI cannot fully replace a real human writer—the tech just isn't there yet.
* **E-E-A-T & YMYL:** AI has no real-world Experience, Expertise, Authoritativeness, or Trustworthiness. If you are writing in a "Your Money or Your Life" (YMYL) niche, publishing unedited AI drafts is a massive risk.
* **The "Helpful Content" Hit Rate:** We all know Google’s stance on AI generated content is *"as long as it is helpful and adds value."* But realistically, straight out of the box, maybe 1 or 2 out of 10 generated articles actually hit that bar on their own. The rest require your editorial touch.
* **Model Drift:** Quality will vary wildly depending on what model you plug into the **Core Generation Settings -> Openrouter Model**. If you are constantly switching between different free-tier models every month to save credits, your site's tone and formatting will drift noticeably.

### So, what is this actually good for?

This tool is incredibly powerful when used for the right reasons:

1. **Curing Writer's Block:** It is the ultimate "I'm stuck and don't know what to write" cure. It builds the structure, taxonomy, and baseline draft so you have a solid foundation to manually edit and SEO yourself.
2. **Website Flipping:** If you build and sell "starter" or ready-made websites on marketplaces like eBay or Flippa, this is a fantastic way to populate the site with baseline content before putting it on the market.
3. **Theme & Agency Demo Content:** If you build WordPress themes or client sites, this generates beautifully structured, niche-relevant demo content that looks a million times better than *Lorem Ipsum* or random movie quotes.

---

## Core Features

* **LLM & Vision Integration:** Powered by OpenRouter for text generation and API-based image models for automated featured and inline graphics. You can use free-tier LLMs to test the waters, but keep in mind that generating images will cost money.
* **Smart Content Structuring:** Dynamic toggles for Key Takeaways, nested H3s, Markdown Tables, Bullet Lists, FAQs, and Conclusions. Enforces mobile-ready micro-paragraphs (2–3 sentences) and bans robotic "Introduction" headers.
* **Automated Taxonomy & Publishing:** Connects directly to WordPress via the REST API. Automatically maps and creates parent/pillar categories, subcategories, and tags before publishing.
* **Obsidian Knowledge Base Integration:** Every generated article is saved locally to `workspace/articles/` as a clean `.md` file, complete with enriched YAML frontmatter linked directly to the live WordPress footprint.
* **Live SERP Context:** Integrates DuckDuckGo search and Trafilatura to scrape live competitor headings and snippets, feeding factual context into the AI writer.

---

## Prerequisites

1. **Python 3.10+** installed on your machine.
2. **LocalWP** running a local WordPress environment. 
3. **WordPress Application Passwords** enabled on your local site (Users > Profile > Application Passwords).
4. **OpenRouter API Key** (Funded account recommended to bypass free-tier rate limits during bulk runs).

---

## Installation

1. **Clone the repository and navigate to the directory:**
   ```bash
   git clone https://github.com/BashDEV96/local-ai-content-creator
   cd local-seo-engine
   ```

2. **Create and activate a virtual environment:**
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python3 -m venv venv
source venv/bin/activate
```

3. **Install required dependencies:**
```bash
pip install -r requirements.txt
```

4. **Environment Setup:**
Create a `.env` file in the root directory and add your OpenRouter API key:
```env
OPENROUTER_API_KEY="sk-or-v1-..."
```

---

## Configuration & Usage

The application relies on a UI/Queue system to process keywords into full articles.

### 1. Generating Blueprints

Enter a seed keyword (e.g., `Google`). The system can automatically expand this by querying the LLM to generate:

* **Distinct Main Keywords** (deduplicated against existing rows).
* **Click-Worthy Titles (H1)** (Formatted for SEO, dynamically banning colons/dashes).
* **NLP Keywords** (8-12 semantic terms per topic).
* **H2 Outlines** (Scaled by article size: X-Small [2-5 H2s] up to Large [13-16 H2s]).

### 2. Processing the Queue

When a row is processed, the engine executes the following pipeline:

1. **Taxonomy Sync:** Creates parent and child categories in LocalWP.
2. **Visual Generation:** Generates a Featured Image + 1 inline body image per 3 H2s (avoiding hallucinated `![...]` markdown tags). Uploads them directly to the WP Media Library.
3. **Drafting:** Writes the full article in a one-shot markdown draft adhering to strict strict structural and tone rules.
4. **Publishing:** Converts Markdown to HTML (preserving tables/lists) and publishes to LocalWP.
5. **Local Archiving:** Saves the final Markdown file to `workspace/articles/` with enriched YAML data.

---

## Output Architecture

### Obsidian-Ready Markdown

Files are saved natively to your workspace, structured perfectly for Obsidian Dataview or property databases:

```yaml
---
title: "Google Local Search Strategies That Win More Traffic"
slug: "google-local-search"
description: "Master local SEO with these actionable Google search strategies..."
category: "Google"
subcategories: 
  - "Local SEO"
  - "Business Profiles"
tags: 
  - "local search"
  - "map pack"
date: 2026-11-21
article-type: "Blog"
word-count: 1450
status: "draft"
site: "http://localhost:10004"
post-id: 142
post-url: "http://localhost:10004/?p=142"
---

The opening hook begins right here...
```
