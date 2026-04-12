from .models import User


def hg_session_user(request):
    """Expose minimal session user for templates (custom auth, not Django auth)."""
    uid = request.session.get("user_id")
    if not uid:
        return {"hg_user": None}
    try:
        u = User.objects.get(user_id=uid)
        return {"hg_user": u}
    except User.DoesNotExist:
        return {"hg_user": None}
