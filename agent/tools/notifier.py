"""
Tool: Notifier — Send a notification to the user.
"""
import json
import traceback
from database.models import Notification


def send_notification(title: str, message: str, ntype: str = "info") -> str:
    """
    Create a notification for the user.

    Args:
        title: Notification title
        message: Notification body
        ntype: Notification type (info, deal, alert, tracking)

    Returns:
        A JSON string confirming the result
    """
    try:
        nid = Notification.create(title=title, message=message, ntype=ntype)
        return json.dumps({
            "success": True,
            "notification_id": nid,
            "message": "Notification sent successfully."
        }, ensure_ascii=False)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({
            "success": False,
            "message": f"Error sending notification: {str(e)}"
        }, ensure_ascii=False)


TOOL_DEFINITION = {
    "name": "send_notification",
    "description": "Send a notification to the user about a good deal, price drop, or important update.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Notification title"
            },
            "message": {
                "type": "string",
                "description": "Detailed notification body"
            },
            "ntype": {
                "type": "string",
                "description": "Notification type: 'info', 'deal', 'alert', or 'tracking'",
                "enum": ["info", "deal", "alert", "tracking"]
            }
        },
        "required": ["title", "message"]
    }
}
