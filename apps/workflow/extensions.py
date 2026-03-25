from drf_spectacular.extensions import OpenApiAuthenticationExtension

from .authentication import JWTAuthentication


class CookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = JWTAuthentication
    name = "cookieAuth"
    match_subclasses = True
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "access_token",
        }
