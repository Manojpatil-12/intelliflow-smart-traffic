from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def role_required(*roles):
    """Decorator that restricts view access to users with specified roles."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("accounts:login")
            if request.user.role not in roles:
                return HttpResponseForbidden(
                    "You do not have permission to access this page."
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
