import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from html import escape

from jinja2 import Environment, FileSystemLoader

# --- System Configuration ---
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
TEMPLATES_DIR: Path = BASE_DIR / "shared_templates"
PUBLIC_DIR: Path = BASE_DIR / "public"
SITE_URL: str = "https://www.withdrawalguide.com"

# --- Studio Console Colors ---
class CLI:
    OK = '\033[92m'
    WARN = '\033[93m'
    FAIL = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def validate_ymyl_schema(data: Dict[str, Any], slug: str) -> None:
    """Strict assertion validation. If it fails, the build physically halts."""
    assert "audit" in data, f"{CLI.FAIL}[{slug}] Missing E-E-A-T 'audit' block.{CLI.RESET}"
    assert "authorship" in data, f"{CLI.FAIL}[{slug}] Missing E-E-A-T 'authorship' block.{CLI.RESET}"
    
    try:
        datetime.strptime(data["audit"]["last_verified"], "%Y-%m-%d")
    except ValueError:
        raise AssertionError(f"{CLI.FAIL}[{slug}] audit.last_verified must be exact YYYY-MM-DD.{CLI.RESET}")
        
    for method in data.get("withdrawal_methods", []):
        assert isinstance(method.get("fee_amount"), (int, float)), f"{CLI.FAIL}[{slug}] {method['slug']} fee_amount must be a computable float.{CLI.RESET}"
        assert isinstance(method.get("processing_hours"), (int, float)), f"{CLI.FAIL}[{slug}] {method['slug']} processing_hours must be a computable float.{CLI.RESET}"

def generate_schema_graph(data: Dict[str, Any], url: str, iso_date: str) -> str:
    """Constructs a deterministic, minified JSON-LD @graph."""
    graph: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{SITE_URL}/#organization",
                "name": "WithdrawalGuide Data Desk",
                "url": SITE_URL,
                "logo": { "@type": "ImageObject", "url": f"{SITE_URL}/logo.png" }
            },
            {
                "@type": "WebPage",
                "@id": f"{url}#webpage",
                "url": url,
                "name": data["seo"]["title"],
                "description": data["seo"]["description"],
                "inLanguage": "en-US",
                "isPartOf": { "@id": f"{SITE_URL}/#website" }
            },
            {
                "@type": "Article",
                "@id": f"{url}#article",
                "isPartOf": { "@id": f"{url}#webpage" },
                "mainEntityOfPage": { "@id": f"{url}#webpage" },
                "headline": data["seo"]["title"],
                "dateModified": iso_date,
                "author": { 
                    "@type": "Organization", 
                    "name": data["authorship"].get("author_name", "Data Desk"),
                    "@id": f"{SITE_URL}/#organization" 
                },
                "reviewedBy": { 
                    "@type": "Person", 
                    "name": data["authorship"]["reviewer_name"] 
                },
                "publisher": { "@id": f"{SITE_URL}/#organization" }
            },
            {
                "@type": "FAQPage",
                "@id": f"{url}#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": { "@type": "Answer", "text": faq["answer"] }
                    } for faq in data.get("faqs", [])
                ]
            }
        ]
    }
    # sort_keys=True guarantees deterministic byte-output for identical data
    return json.dumps(graph, separators=(',', ':'), sort_keys=True) 

def main() -> None:
    print(f"\n{CLI.BOLD}🎛️  === Mastering Static Build ==={CLI.RESET}\n")
    
    if PUBLIC_DIR.exists():
        shutil.rmtree(PUBLIC_DIR)
    PUBLIC_DIR.mkdir(parents=True)
    
    # Copy external CSS to public root (CSP: style-src 'self' requires external file)
    css_source: Path = TEMPLATES_DIR / "platform-hub.css"
    shutil.copy2(css_source, PUBLIC_DIR / "platform-hub.css")
    
    # Strip Jinja whitespace to minimize wire payload
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True, trim_blocks=True, lstrip_blocks=True)
    
    try:
        hub_template = env.get_template("platform-hub.html")
    except Exception as e:
        print(f"{CLI.FAIL}Template Error: {e}{CLI.RESET}")
        sys.exit(1)
    
    sitemap_urls: List[Dict[str, str]] = []

    for json_file in sorted(DATA_DIR.glob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        validate_ymyl_schema(data, data["slug"])
        
        slug: str = data["slug"]
        page_url: str = f"{SITE_URL}/{slug}/"
        
        # ISO-8601 Temporal strictness
        verify_date = datetime.strptime(data["audit"]["last_verified"], "%Y-%m-%d")
        iso_modified: str = verify_date.replace(tzinfo=timezone.utc).isoformat()
        sitemap_urls.append({"loc": page_url, "lastmod": iso_modified})
        
        # Mathematical derivation for UI
        methods = data["withdrawal_methods"]
        data["computed"] = {
            "fastest": min(methods, key=lambda x: x.get("processing_hours", 999.0)),
            "lowest_fee": min(methods, key=lambda x: x.get("fee_amount", 999.0)),
            "iso_date_time": iso_modified,
            "json_ld_graph": generate_schema_graph(data, page_url, iso_modified),
            "canonical_url": page_url
        }
        
        platform_dir = PUBLIC_DIR / slug
        platform_dir.mkdir(exist_ok=True)
        
        try:
            html_output = hub_template.render(**data)
            with open(platform_dir / "index.html", "w", encoding="utf-8") as out_f:
                out_f.write(html_output)
            print(f"  {CLI.OK}✔ Mastered:{CLI.RESET} /{slug}/")
        except Exception as e:
            print(f"  {CLI.FAIL}❌ Render Failed:{CLI.RESET} /{slug}/ -> {e}")

    # XML Generation (Perfectly Escaped)
    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in sitemap_urls:
        safe_loc = escape(u["loc"])
        sitemap_xml += f'  <url>\n    <loc>{safe_loc}</loc>\n    <lastmod>{u["lastmod"]}</lastmod>\n    <changefreq>weekly</changefreq>\n  </url>\n'
    sitemap_xml += '</urlset>'
    
    with open(PUBLIC_DIR / "sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_xml)
        
    with open(PUBLIC_DIR / "robots.txt", "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
        
    print(f"\n{CLI.BOLD}{CLI.OK}💿 === Build complete. Ready for Edge. ==={CLI.RESET}\n")

if __name__ == "__main__":
    main()
