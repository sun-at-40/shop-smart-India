"""
Tool: Price Scraper — extracts the price (INR) from a product URL.

Extraction strategies (in priority order, stops at the first that yields a price):
  1. Official site API adapters (none registered by default for Indian stores).
  2. JSON-LD (schema.org Product) — standard, supported by many stores.
  3. Meta tags (Open Graph / product:price).
  4. JSON embedded in <script> — rescues JavaScript-rendered pages
     (Flipkart/Amazon/Croma embed their initial state as JSON).
  5. Site-specific CSS selectors.
  6. Generic CSS selectors.
"""
import json
import re
import traceback
from agent.tools import safe_http as requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.6",
}

REQUEST_TIMEOUT = 15
MAX_RETRIES = 2  # total attempts = 1 + MAX_RETRIES

# Reasonable bounds for an INR product price. Anything outside is treated as noise
# (e.g. installment months, percentages, product codes, ratings).
MIN_VALID_PRICE = 100
MAX_VALID_PRICE = 100_000_000  # 10 crore INR

# Site-specific price selectors (checked before generic ones). Best-effort:
# these class names change often, so JSON-LD/meta/embedded JSON run first.
SITE_SELECTORS = {
    "amazon.in": ["span.a-price span.a-offscreen", "#corePrice_feature_div .a-offscreen", ".a-price-whole"],
    "flipkart.com": ["div.Nx9bqj", "div._30jeq3", "div.hZ3P6w"],
    "croma.com": ["#pdp-product-price", "[data-testid='new-price']", ".amount"],
    "reliancedigital.in": [".pdp__offerPrice", ".pdp__priceSection__priceListText"],
    "vijaysales.com": [".product__price--offer", ".offer-price", ".price"],
    "tatacliq.com": ["[class*='ProductDescription__discount']", "h3[class*='price']"],
    "myntra.com": [".pdp-price strong", ".pdp-price"],
    "snapdeal.com": [".payBlkBig", ".pdp-final-price"],
}

# JSON keys that commonly hold a product's selling price across Indian e-commerce
# embedded state. Ordered by preference (current/sale price before list price).
_PRICE_JSON_KEYS = [
    "price_min", "salePrice", "sale_price", "finalPrice", "final_price",
    "current_price", "currentPrice", "special_price", "specialPrice",
    "displayPrice", "display_price", "price", "lowPrice", "list_price",
    "price_max",
]


def _parse_inr(raw) -> float | None:
    """
    Parse an INR amount from a string/number, validating a sane range.

    Handles '₹1,29,999', 'Rs. 79,999.00', '24999.50', '1,299' or a raw number.
    Commas are thousands separators (Indian lakh grouping included); '.' is
    the decimal point.
    """
    if raw is None or isinstance(raw, bool):
        return None

    # Numeric input (from embedded JSON / API) — use directly.
    if isinstance(raw, (int, float)):
        price = float(raw)
        return price if MIN_VALID_PRICE <= price <= MAX_VALID_PRICE else None

    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(raw))
    if not match:
        return None

    try:
        price = float(match.group().replace(",", ""))
    except ValueError:
        return None

    if MIN_VALID_PRICE <= price <= MAX_VALID_PRICE:
        return round(price, 2)
    return None


def _extract_price_from_text(text) -> float | None:
    """Try to extract a valid INR price from arbitrary text."""
    return _parse_inr(text)


def _title_of(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    return title_tag.get_text().strip() if title_tag else ""


# ── Strategy 1: Official site APIs ──────────────────────────
# Map of domain -> adapter(url) returning {"name", "price"} or None.
# Indian stores have no stable public product APIs, so none are registered.
_SITE_API_ADAPTERS = {}


def _extract_price_site_api(url: str) -> dict | None:
    for domain, adapter in _SITE_API_ADAPTERS.items():
        if domain in url:
            result = adapter(url)
            if result:
                return result
    return None


# ── Strategy 2: JSON-LD ─────────────────────────────────────
def _extract_price_jsonld(soup: BeautifulSoup) -> dict | None:
    """Extract price from JSON-LD structured data (most reliable in-page)."""
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") == "Product":
                    offers = item.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    raw_price = offers.get("price") or offers.get("lowPrice")
                    name = item.get("name", "")
                    if raw_price is not None:
                        price = _parse_inr(raw_price)
                        if price:
                            return {"name": name, "price": price}
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            continue
    return None


# ── Strategy 3: Meta tags ───────────────────────────────────
def _extract_price_meta(soup: BeautifulSoup) -> dict | None:
    """Extract price from Open Graph / meta tags."""
    meta_props = ["product:price:amount", "og:price:amount"]
    for prop in meta_props:
        tag = soup.find("meta", {"property": prop})
        if tag and tag.get("content"):
            price = _parse_inr(tag["content"])
            if price:
                og_title = soup.find("meta", {"property": "og:title"})
                name = og_title["content"] if og_title and og_title.get("content") else ""
                return {"name": name, "price": price}
    return None


# ── Strategy 4: Embedded JSON in <script> (JS-render sites) ─
def _walk_json_for_price(obj) -> float | None:
    """
    Recursively walk a decoded JSON structure looking for a price-bearing key.

    Tries preferred keys first across the whole tree, returning the first valid
    INR value found. This rescues sites that ship their state as JSON and render
    the price client-side (Flipkart/Amazon/Croma/etc.).
    """
    # Breadth-first collection of all dict nodes.
    nodes = []
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            nodes.append(cur)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)

    for key in _PRICE_JSON_KEYS:
        for node in nodes:
            if key in node:
                price = _parse_inr(node[key])
                if price:
                    return price
    return None


def _extract_price_embedded_json(soup: BeautifulSoup) -> dict | None:
    """Scan <script> blocks for embedded JSON state and mine a price from it."""
    name = _title_of(soup)
    for script in soup.find_all("script"):
        raw = script.string
        if not raw or ("price" not in raw.lower()):
            continue

        # Whole-script JSON (e.g. <script type="application/json">…</script>).
        candidates = []
        stripped = raw.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            candidates.append(stripped)

        # Inline assignments like `window.__DATA__ = {…};`.
        m = re.search(r"=\s*(\{.*\})\s*;?\s*$", stripped, re.DOTALL)
        if m:
            candidates.append(m.group(1))

        for cand in candidates:
            try:
                data = json.loads(cand)
            except (json.JSONDecodeError, ValueError):
                continue
            price = _walk_json_for_price(data)
            if price:
                return {"name": name, "price": price}
    return None


# ── Strategy 5: Site-specific selectors ─────────────────────
def _extract_price_site_specific(soup: BeautifulSoup, url: str) -> dict | None:
    """Extract price using selectors tuned for known Indian e-commerce sites."""
    for domain, selectors in SITE_SELECTORS.items():
        if domain not in url:
            continue
        for selector in selectors:
            for el in soup.select(selector):
                price = _parse_inr(el.get_text())
                if price:
                    return {"name": _title_of(soup), "price": price}
    return None


# ── Strategy 6: Generic selectors ───────────────────────────
def _extract_price_selectors(soup: BeautifulSoup) -> dict | None:
    """Extract price using common generic CSS selectors."""
    price_selectors = [
        "[itemprop='price']",
        "[class*='price'] [class*='current']",
        "[class*='product-price']",
        "[class*='price-current']",
        "[class*='sale-price']",
        "[class*='final-price']",
        ".price",
        "#price",
    ]
    for selector in price_selectors:
        for el in soup.select(selector):
            price = _parse_inr(el.get("content", "")) or _parse_inr(el.get_text())
            if price:
                return {"name": _title_of(soup), "price": price}
    return None


def _fetch(url: str):
    """GET a URL with a small retry/backoff. Returns Response or raises."""
    import time
    last_exc = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            # Only retry on transient errors (timeout / 429 / 5xx).
            transient = isinstance(e, requests.Timeout) or status in (429, 500, 502, 503, 504)
            if attempt < MAX_RETRIES and transient:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_exc


def scrape_price(url: str) -> str:
    """
    Extract the product price (in INR) from a URL.

    Args:
        url: product page URL to fetch the price from

    Returns:
        JSON string with the product price information
    """
    if not url or not re.match(r"^https?://", url.strip(), re.IGNORECASE):
        return json.dumps({
            "success": False,
            "url": url,
            "message": "Invalid URL. The URL must start with http:// or https://"
        }, ensure_ascii=False)

    url = url.strip()

    # Strategy 1: official site API (works even for JS-render pages).
    try:
        api_result = _extract_price_site_api(url)
        if api_result:
            return json.dumps({
                "success": True,
                "url": url,
                "product_name": api_result["name"],
                "price": api_result["price"],
                "currency": "INR",
                "method": "site_api",
            }, ensure_ascii=False)
    except Exception:
        traceback.print_exc()

    try:
        resp = _fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")

        # For known stores we trust structured data + site-tuned selectors only.
        # The generic selector scans the whole page and frequently grabs an
        # accessory price or a "Save ₹3,000" promo number, returning a wrong
        # (too-low) price — worse than returning nothing. So we only fall back
        # to generic selectors on UNKNOWN sites.
        is_known_site = any(domain in url for domain in SITE_SELECTORS)

        strategies = [
            ("jsonld", lambda: _extract_price_jsonld(soup)),
            ("meta", lambda: _extract_price_meta(soup)),
            ("embedded_json", lambda: _extract_price_embedded_json(soup)),
            ("site_css", lambda: _extract_price_site_specific(soup, url)),
        ]
        if not is_known_site:
            strategies.append(("generic_css", lambda: _extract_price_selectors(soup)))
        for method, fn in strategies:
            result = fn()
            if result:
                return json.dumps({
                    "success": True,
                    "url": url,
                    "product_name": result["name"],
                    "price": result["price"],
                    "currency": "INR",
                    "method": method,
                }, ensure_ascii=False)

        title = _title_of(soup) or "Unknown"
        return json.dumps({
            "success": False,
            "url": url,
            "message": f"Could not extract a price from this page (it may render prices with JavaScript). Page: {title}",
        }, ensure_ascii=False)

    except requests.Timeout:
        return json.dumps({
            "success": False,
            "url": url,
            "message": f"Timed out while accessing the URL (timeout {REQUEST_TIMEOUT}s)."
        }, ensure_ascii=False)
    except requests.RequestException as e:
        return json.dumps({
            "success": False,
            "url": url,
            "message": f"Could not access the URL: {str(e)}"
        }, ensure_ascii=False)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({
            "success": False,
            "url": url,
            "message": f"Error while scraping the price: {str(e)}"
        }, ensure_ascii=False)


TOOL_DEFINITION = {
    "name": "scrape_price",
    "description": "Extract the product price (INR) from a specific URL. Use when you need the exact price from a given product page.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full product page URL (e.g. 'https://www.flipkart.com/apple-iphone-16/p/itm123')"
            }
        },
        "required": ["url"]
    }
}
