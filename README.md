# Local SEO Bulk Engine

A self-hosted, open-source bulk SEO content generator and WordPress auto-publisher built with **Flask**, **Tailwind CSS**, **Alpine.js**, **OpenRouter**, and **LocalWP**.

Designed to run smoothly on modest local hardware by offloading LLM and image generation to OpenRouter while keeping orchestration, SERP scraping, and multi-site WordPress publishing 100% local on your machine.

## Features

- **Bulk Article Queue:** Interactive spreadsheet table with `.csv` and `.xlsx` import support.
- **Live Web Grounding:** Optional DuckDuckGo SERP search + `trafilatura` competitor page extraction before outlining.
- **Multi-Section Long-Form Drafting:** Generates a structured JSON blueprint first, then writes each H2 section individually via OpenRouter (defaulting to `nvidia/nemotron-3.5-lightning`).
- **Cohesive Per-Site Visual DNA:** Generates **1 Featured Image + 1 body image per 3 H2s** via `bytedance-seed/seedream-5-0-lite`, automatically styled using each site's visual look-and-feel rules in `sites.json`.
- **Direct LocalWP Publishing:** Uploads images with SEO alt-text to the Media Library, and creates drafts or published posts via the WordPress REST API.

## Quickstart Setup

### 1. Clone & Install Dependencies

    git clone https://github.com/YOUR-USERNAME/local-seo-engine.git
    cd local-seo-engine
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

### 2. Configure API Keys & LocalWP Sites

    cp .env.example .env
    cp sites.example.json sites.json

1. Add your `OPENROUTER_API_KEY` inside `.env`.
2. Spin up a site in **LocalWP**, open **WP Admin -> Users -> Profile -> Application Passwords**, generate a password, and paste your site URL, username, and Application Password into `sites.json` (or configure them directly in the web UI under **Sites & Visual Styles**).

### 3. Run the App

    python app.py

Open `http://127.0.0.1:5050` in your browser.

## License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)** — see the `LICENSE` file for details.
