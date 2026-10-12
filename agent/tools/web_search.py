"""
Tool: Web Search — finds products on Indian e-commerce sites.
Uses DuckDuckGo search with site-specific queries for Indian e-commerce.
"""
import json
import os
import re
import traceback
from ddgs import DDGS

from agent.tools.cache_util import TTLCache, RateLimiter


# Cache search results for a short while so repeated/identical queries don't
# re-hit DuckDuckGo, and rate-limit outbound calls to avoid HTTP 429 blocks.
_SEARCH_TTL = float(os.environ.get("SEARCH_CACHE_TTL", "300"))      # 5 minutes
_SEARCH_MAX_CALLS = int(os.environ.get("SEARCH_RATE_MAX_CALLS", "8"))
_SEARCH_PERIOD = float(os.environ.get("SEARCH_RATE_PERIOD", "60"))   # per 60s

_search_cache = TTLCache(ttl=_SEARCH_TTL, max_entries=256)
_rate_limiter = RateLimiter(max_calls=_SEARCH_MAX_CALLS, period=_SEARCH_PERIOD)


# Indian e-commerce sites to search
ECOMMERCE_SITES = [
    {"name": "Amazon India", "domain": "amazon.in", "icon": "amazon"},
    {"name": "Flipkart", "domain": "flipkart.com", "icon": "flipkart"},
    {"name": "Croma", "domain": "croma.com", "icon": "croma"},
    {"name": "Reliance Digital", "domain": "reliancedigital.in", "icon": "reliance"},
    {"name": "Vijay Sales", "domain": "vijaysales.com", "icon": "vijaysales"},
    {"name": "Tata CLiQ", "domain": "tatacliq.com", "icon": "tatacliq"},
    {"name": "Myntra", "domain": "myntra.com", "icon": "myntra"},
    {"name": "Snapdeal", "domain": "snapdeal.com", "icon": "snapdeal"},
]

# Snippets to filter out (useless descriptions)
_BAD_SNIPPETS = [
    "we cannot provide a description for this page right now",
    "we can't provide a description for this page right now",
]


def _clean_title(title: str) -> str:
    """Clean up product title from search results."""
    removals = [
        r'\s*[-|–:]\s*Amazon\.in.*$',
        r'^Amazon\.in\s*:\s*',
        r'\s*[-|–]\s*Flipkart.*$',
        r'\s*[-|–]\s*Croma.*$',
        r'\s*[-|–]\s*Reliance\s*Digital.*$',
        r'\s*[-|–]\s*Vijay\s*Sales.*$',
        r'\s*[-|–]\s*Tata\s*CLiQ.*$',
        r'\s*[-|–]\s*Myntra.*$',
        r'\s*[-|–]\s*Snapdeal.*$',
        r'^Buy\s+',
        r'\s*Online\s+at\s+Best\s+Price.*$',
        r'\s*Online\s+in\s+India.*$',
        r'\s*[-|–]\s*$',  # Remove trailing dash
    ]
    for pattern in removals:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    return title.strip().rstrip('-–|').strip()


def _clean_snippet(snippet: str) -> str:
    """Clean snippet, remove useless descriptions."""
    if not snippet:
        return ""
    snippet_lower = snippet.lower().strip()
    for bad in _BAD_SNIPPETS:
        if bad in snippet_lower:
            return ""
    return snippet.strip()


def _identify_source(url: str) -> str:
    """Identify the e-commerce source from URL."""
    for site in ECOMMERCE_SITES:
        if site["domain"] in url:
            return site["name"]
    return "Web"


# Path fragments that signal a non-product page (blog/news/help/promo listing).
# These pages have no price, so scraping them always fails — drop them early.
_NON_PRODUCT_PATTERNS = [
    "/blog", "/news", "/wiki", "/offers", "/deals", "/help", "/faq",
    "/review", "/reviews", "/compare", "/guide", "/buying-guide",
    "/contact", "/about", "/policy", "/policies", "/tag/", "/video",
    "/stories", "/lp/", "/gp/help", "/b/", "/s?", "/search",
    "/c/", "/collections", "/category",
]

# Positive signals that a URL is a real product page on known Indian e-commerce sites.
_PRODUCT_URL_HINTS = [
    re.compile(r"/dp/[a-z0-9]{10}"),   # Amazon: /dp/ASIN
    re.compile(r"/gp/product/"),       # Amazon legacy
    re.compile(r"/p/itm[a-z0-9]+"),    # Flipkart: /p/itm...
    re.compile(r"/p/\d+"),             # Croma / Tata CLiQ: /p/123456
    re.compile(r"/p-mp\d+"),           # Tata CLiQ: /p-mp000000...
    re.compile(r"/product/"),          # Snapdeal / Vijay Sales / Reliance Digital
    re.compile(r"/products?/"),        # generic /product/ or /products/
    re.compile(r"/buy$"),              # Myntra: .../buy
    re.compile(r"/\d{5,}/buy"),
    re.compile(r"/p/"),
]


def _is_product_url(url: str) -> bool:
    """
    Heuristic filter: keep likely product pages, drop blog/news/promo pages.

    Search engines often return articles ('/blog/', '/offers/', '/guide/')
    which have no price. Scraping those always fails, so we exclude them here.
    """
    if not url:
        return False
    low = url.lower()

    # Reject obvious non-product sections.
    for bad in _NON_PRODUCT_PATTERNS:
        if bad in low:
            return False

    # If we recognise a positive product-URL signal, keep it.
    for pat in _PRODUCT_URL_HINTS:
        if pat.search(low):
            return True

    # Otherwise: keep only if the path looks like a product slug (has a path
    # segment beyond the domain root, e.g. a long hyphenated name).
    try:
        path = re.sub(r"^https?://[^/]+", "", low).strip("/")
    except Exception:
        path = ""
    # A bare domain or a single short segment is unlikely to be a product page.
    return bool(path) and ("-" in path or "/" in path) and len(path) > 8


def search_product(query: str, max_results: int = 10) -> str:
    """
    Search for products on Indian e-commerce sites.
    Returns a list of products with name, link and seller source.

    Args:
        query: Product to search for (e.g. "iPhone 16 128GB")
        max_results: Maximum number of results

    Returns:
        JSON string containing the search results
    """
    query = (query or "").strip()
    if not query:
        return json.dumps({
            "success": False,
            "message": "Please enter a search keyword.",
            "results": []
        }, ensure_ascii=False)

    # 1) Serve from cache when possible (keyed by normalized query + max_results).
    cache_key = f"{query.lower()}::{max_results}"
    cached = _search_cache.get(cache_key)
    if cached is not None:
        return cached

    # 2) Rate-limit outbound search calls to avoid being blocked (HTTP 429).
    if not _rate_limiter.acquire():
        retry_after = round(_rate_limiter.time_until_next(), 1)
        # If we have a stale cached entry, prefer returning it over an error.
        stale = _search_cache.get(cache_key, allow_stale=True)
        if stale is not None:
            return stale
        return json.dumps({
            "success": False,
            "query": query,
            "rate_limited": True,
            "message": f"Searching too fast. Please try again in {retry_after}s.",
            "results": []
        }, ensure_ascii=False)

    result_json = _do_search(query, max_results)

    # 3) Only cache successful, non-empty responses.
    try:
        parsed = json.loads(result_json)
        if parsed.get("success") and parsed.get("total_results", 0) > 0:
            _search_cache.set(cache_key, result_json)
    except (json.JSONDecodeError, TypeError):
        pass

    return result_json


def _do_search(query: str, max_results: int = 10) -> str:
    """Perform the actual DuckDuckGo search (no caching/rate-limiting)."""
    try:
        all_results = []
        seen_urls = set()

        # Strategy 1: Search on specific e-commerce sites
        site_queries = [
            f"{query} site:amazon.in OR site:flipkart.com OR site:croma.com",
            f"{query} site:reliancedigital.in OR site:vijaysales.com OR site:tatacliq.com OR site:snapdeal.com",
        ]

        with DDGS() as ddgs:
            for sq in site_queries:
                try:
                    results = list(ddgs.text(sq, region="in-en", max_results=8))
                    for r in results:
                        url = r.get("href", "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)

                        title = r.get("title", "")
                        snippet = r.get("body", "")

                        source = _identify_source(url)
                        clean_name = _clean_title(title)
                        clean_snip = _clean_snippet(snippet)

                        # Skip article/blog/news URLs — they have no price and
                        # make the "View price" button fail. Only keep real product
                        # pages from a known store.
                        if clean_name and source != "Web" and _is_product_url(url):
                            all_results.append({
                                "product_name": clean_name,
                                "url": url,
                                "source": source,
                                "snippet": clean_snip[:160] if clean_snip else None,
                                "is_product": True,
                            })
                except Exception:
                    continue

            # Strategy 2: General search if not enough results
            if len(all_results) < 4:
                try:
                    general = list(ddgs.text(
                        f"{query} buy online India price",
                        region="in-en",
                        max_results=6
                    ))
                    for r in general:
                        url = r.get("href", "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)

                        title = r.get("title", "")
                        snippet = r.get("body", "")

                        source = _identify_source(url)
                        clean_name = _clean_title(title)
                        clean_snip = _clean_snippet(snippet)

                        if clean_name:
                            all_results.append({
                                "product_name": clean_name,
                                "url": url,
                                "source": source,
                                "snippet": clean_snip[:160] if clean_snip else None,
                                "is_product": _is_product_url(url),
                            })
                except Exception:
                    pass

        # Prioritise real product pages over anything left in (stable sort keeps
        # original order within each group), then cap the count.
        all_results.sort(key=lambda r: not r.get("is_product", False))
        final_results = all_results[:max_results]

        if not final_results:
            return json.dumps({
                "success": True,
                "query": query,
                "total_results": 0,
                "results": [],
                "message": f"No results found for '{query}'. Try different keywords."
            }, ensure_ascii=False)

        return json.dumps({
            "success": True,
            "query": query,
            "total_results": len(final_results),
            "sources_found": list(set(r["source"] for r in final_results)),
            "results": final_results,
        }, ensure_ascii=False)

    except Exception as e:
        traceback.print_exc()
        return json.dumps({
            "success": False,
            "message": f"Search error: {str(e)}",
            "results": []
        }, ensure_ascii=False)


# Tool definition for Gemini function calling
TOOL_DEFINITION = {
    "name": "search_product",
    "description": "Search for products on Indian e-commerce sites (Amazon India, Flipkart, Croma, Reliance Digital, Vijay Sales, Tata CLiQ, Snapdeal). Returns a list of products with purchase links and seller sources.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Product name or search keywords"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default 10)"
            }
        },
        "required": ["query"]
    }
}
