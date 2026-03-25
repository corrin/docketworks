"""
ASGI config for docketworks project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

try:
    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter

    from apps.chatbot import routing

    application = ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AuthMiddlewareStack(URLRouter(routing.websocket_urlpatterns)),
        }
    )
except ImportError:
    # Fallback to Django ASGI app if chatbot app doesn't exist yet
    application = django_asgi_app
