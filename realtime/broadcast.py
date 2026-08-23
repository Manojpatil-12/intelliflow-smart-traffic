"""Helpers to broadcast updates over WebSocket."""

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def broadcast_prediction(payload):
    """Send a prediction update to all connected map clients."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "traffic_updates",
        {
            "type": "traffic_update",
            "data": {
                "type": "prediction_update",
                **payload,
            },
        },
    )


def broadcast_emergency(payload):
    """Send an emergency update to all connected clients."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "traffic_updates",
        {
            "type": "emergency_update",
            "data": {
                "type": "emergency_update",
                **payload,
            },
        },
    )
