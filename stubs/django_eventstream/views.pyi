# Upstream signature is events(request, **kwargs); the keywords are read by the
# channel manager (`channels`, `channel`, `format-channels`), so they are typed
# loosely on purpose rather than narrowed to this codebase's one call.
from django.http import HttpRequest
from django.http.response import HttpResponseBase

def events(request: HttpRequest, **kwargs: object) -> HttpResponseBase: ...
