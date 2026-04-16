from .models import User


def hg_session_user(request):
    """向模板暴露最小会话用户信息（自定义认证，非 Django 内置认证）。"""
    uid = request.session.get("user_id")
    if not uid:
        return {"hg_user": None}
    try:
        u = User.objects.get(user_id=uid)
        # 仅向模板暴露基础字段，避免把完整 ORM 对象放入全局模板上下文。
        return {
            "hg_user": {
                "user_id": u.user_id,
                "username": u.username,
                "role": u.role,
            }
        }
    except (User.DoesNotExist, TypeError, ValueError):
        return {"hg_user": None}
    except Exception:
        return {"hg_user": None}
