"""
Tool: Price Tracker — Track product prices in the database.
"""
import json
import traceback
from agent.tools.currency import format_inr
from database.models import Product, Notification
from agent.context import get_current_user_id


def track_price(product_name: str, url: str = None,
                current_price: float = None, target_price: float = None,
                source: str = None) -> str:
    """
    Add a product to the price watchlist.

    Args:
        product_name: Product name
        url: Product URL (optional)
        current_price: Current price (optional)
        target_price: Desired price for receiving an alert (optional)
        source: Retailer (Amazon India, Flipkart, Croma, etc.; optional)

    Returns:
        A JSON string confirming the product was added to the watchlist
    """
    try:
        user_id = get_current_user_id()
        product_id = Product.create(
            name=product_name,
            url=url,
            source=source,
            current_price=current_price,
            target_price=target_price,
            user_id=user_id,
        )

        # Create notification
        price_str = format_inr(current_price)
        Notification.create(
            title="📌 Product added to your watchlist",
            message=f"'{product_name}' was added to your watchlist. Current price: {price_str}",
            product_id=product_id,
            ntype="tracking",
            user_id=user_id,
        )

        return json.dumps({
            "success": True,
            "product_id": product_id,
            "message": f"'{product_name}' was added to your price watchlist.",
            "product": {
                "id": product_id,
                "name": product_name,
                "url": url,
                "current_price": current_price,
                "target_price": target_price,
                "source": source
            }
        }, ensure_ascii=False)

    except Exception as e:
        traceback.print_exc()
        return json.dumps({
            "success": False,
            "message": f"Error adding product: {str(e)}"
        }, ensure_ascii=False)


def get_tracked_products() -> str:
    """
    Get all products currently on the watchlist.

    Returns:
        A JSON string containing the product list
    """
    try:
        products = Product.get_all(user_id=get_current_user_id())
        return json.dumps({
            "success": True,
            "total": len(products),
            "products": products
        }, ensure_ascii=False)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({
            "success": False,
            "message": f"Error: {str(e)}"
        }, ensure_ascii=False)


TOOL_DEFINITIONS = [
    {
        "name": "track_price",
        "description": "Add a product to the price watchlist when the user wants an alert if its price drops.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Name of the product to track"
                },
                "url": {
                    "type": "string",
                    "description": "Product page URL, if available"
                },
                "current_price": {
                    "type": "number",
                    "description": "Current product price in INR"
                },
                "target_price": {
                    "type": "number",
                    "description": "Desired price threshold in INR for receiving a price-drop alert"
                },
                "source": {
                    "type": "string",
                    "description": "Retailer (e.g. 'amazon', 'flipkart', 'croma', 'reliance digital', 'vijay sales', 'tata cliq', 'snapdeal')"
                }
            },
            "required": ["product_name"]
        }
    },
    {
        "name": "get_tracked_products",
        "description": "Get all products on the price watchlist when the user wants to review tracked products.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]
