"""
Tests for web_search URL filtering — keep real product pages, drop blog/news/promo.
"""
from agent.tools import web_search as ws


def test_rejects_blog_and_news_urls():
    assert ws._is_product_url("https://www.croma.com/blog/best-iphone-15-tips") is False
    assert ws._is_product_url("https://www.flipkart.com/offers/mobiles-deals") is False
    assert ws._is_product_url("https://www.amazon.in/gp/help/customer/display.html") is False
    assert ws._is_product_url("https://www.reliancedigital.in/news/abc") is False


def test_accepts_product_urls():
    assert ws._is_product_url("https://www.amazon.in/Apple-iPhone-15-128GB/dp/B0CHX1W1XY") is True
    assert ws._is_product_url("https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4") is True
    assert ws._is_product_url("https://www.croma.com/apple-iphone-15/p/300822") is True
    assert ws._is_product_url("https://www.snapdeal.com/product/boat-rockerz/6917529") is True


def test_identify_source():
    assert ws._identify_source("https://www.amazon.in/dp/B0CHX1W1XY") == "Amazon India"
    assert ws._identify_source("https://www.flipkart.com/x/p/itm1") == "Flipkart"
    assert ws._identify_source("https://example.com/x") == "Web"


def test_rejects_empty_and_bare_domain():
    assert ws._is_product_url("") is False
    assert ws._is_product_url("https://www.apple.com/iphone/") is False
