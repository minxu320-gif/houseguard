from django.utils import timezone

from houses.models import SystemLog, User


def log_action(*, request=None, user_id=None, action="", target_id=None, target_type=None, log_level="INFO"):
    """
    写入一条用于审计的 SystemLog 日志记录。
    - request：可选的 Django request（用于推断 IP 地址和用户角色）
    - user_id：当 request 为 None 时必填
    """
    ip = None
    if request is not None:
        ip = request.META.get("REMOTE_ADDR") or request.META.get("HTTP_X_FORWARDED_FOR")
        if not user_id:
            user_id = request.session.get("user_id")

    role = None
    if user_id:
        u = User.objects.filter(user_id=user_id).first()
        role = u.role if u else None

    SystemLog.objects.create(
        user_id=user_id,
        role=role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip,
        log_level=log_level,
        create_time=timezone.now(),
    )

