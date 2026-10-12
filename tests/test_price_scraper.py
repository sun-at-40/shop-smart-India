"""
Tests for price extraction — the most fragile part of the app.
We test the pure parsing helpers (no network) plus JSON-LD / meta extraction.
"""
from bs4 import BeautifulSoup

from agent.tools import price_scraper as ps


class TestExtractPriceFromText:
    def test_rupee_symbol_indian_grouping(self):
        assert ps._extract_price_from_text("₹1,29,999") == 129999.0

    def test_rs_prefix_with_decimals(self):
        assert ps._extract_price_from_text("Rs. 79,999.00") == 79999.0

    def test_plain_number_text(self):
        assert ps._extract_price_from_text("24999") == 24999.0

    def test_rejects_emi_zero_percent(self):
        assert ps._extract_price_from_text("No Cost EMI 0%") is None

    def test_rejects_month_count(self):
        assert ps._extract_price_from_text("12 months") is None

    def test_rejects_discount_percent(self):
        assert ps._extract_price_from_text("Save 50%") is None

    def test_rejects_too_small(self):
        assert ps._extract_price_from_text("99") is None

    def test_rejects_too_large(self):
        assert ps._extract_price_from_text("₹20,00,00,000") is None

    def test_rejects_rating(self):
        assert ps._extract_price_from_text("rating 4.5") is None

    def test_empty(self):
        assert ps._extract_price_from_text("") is None
        assert ps._extract_price_from_text(None) is None


class TestExtractJsonLd:
    def test_product_offer_price(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type":"Product","name":"iPhone 16","offers":{"price":"22990000"}}
        </script>
        </head><body></body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        result = ps._extract_price_jsonld(soup)
        assert result is not None
        assert result["price"] == 22990000.0
        assert result["name"] == "iPhone 16"

    def test_offers_as_list(self):
        html = """
        <script type="application/ld+json">
        {"@type":"Product","name":"X","offers":[{"price":"1500000"}]}
        </script>
        """
        soup = BeautifulSoup(html, "lxml")
        result = ps._extract_price_jsonld(soup)
        assert result["price"] == 1500000.0

    def test_no_jsonld(self):
        soup = BeautifulSoup("<html><body>nothing</body></html>", "lxml")
        assert ps._extract_price_jsonld(soup) is None

    def test_malformed_jsonld_is_ignored(self):
        html = '<script type="application/ld+json">{not valid json}</script>'
        soup = BeautifulSoup(html, "lxml")
        assert ps._extract_price_jsonld(soup) is None
