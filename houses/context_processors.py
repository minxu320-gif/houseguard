from .models import User


def hg_session_user(request):
    """向模板暴露最小会话用户信息（自定义认证，非 Django 内置认证）。"""
    uid = request.session.get("user_id")
    if not uid:
        return {"hg_user": None}
    try:
        u = User.objects.get(user_id=uid)
        return {"hg_user": u}
    except User.DoesNotExist:
        return {"hg_user": None}
