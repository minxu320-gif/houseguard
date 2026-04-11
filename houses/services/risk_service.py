from datetime import timedelta

from django.utils import timezone

from houses.models import RiskAlert, StayCheckinLog, StayRequest, StayStatus, StayTaskProgress, HouseTask
from houses.services.credit_service import update_user_credit


def _alert_exists_today(request_id, alert_type, level):
    today = timezone.now().date()
    return RiskAlert.objects.filter(
        request_id=request_id,
        alert_type=alert_type,
        level=level,
        create_time__date=today,
    ).exists()


def check_risk(request_id):
    """
    Risk rules:
    - 超过24小时未签到 -> high
    - 任务未完成 -> medium（仅在入住期间、且当日有任务时）
    Writes RiskAlert and updates StayStatus. Returns list of created alerts.
    """
    created = []
    now = timezone.now()

    req = StayRequest.objects.filter(request_id=request_id).first()
    if not req or req.status != "approved":
        return created

    if not (req.start_date <= now.date() <= req.end_date):
        return created

    stay_status, _ = StayStatus.objects.get_or_create(
        request_id=request_id,
        defaults={
            "current_status": "active",
            "checkin_required": 1,
            "last_checkin_time": None,
            "aborrmal_flag": 0,
            "update_time": now,
        },
    )

    # Rule 1: checkin overdue
    last_checkin = stay_status.last_checkin_time
    if last_checkin is None:
        last_checkin = StayCheckinLog.objects.filter(request_id=request_id).order_by("-checkin_time").values_list("checkin_time", flat=True).first()
    if last_checkin is None or (now - last_checkin) > timedelta(hours=24):
        if not _alert_exists_today(request_id, "checkin_overdue", "high"):
            alert = RiskAlert.objects.create(
                house_id=req.house_id,
                request_id=req.request_id,
                alert_type="checkin_overdue",
                level="high",
                message="超过24小时未签到",
                create_time=now,
            )
            created.append(alert)

        stay_status.aborrmal_flag = 1
        stay_status.update_time = now
        stay_status.save()

        # credit penalty idempotent per day per request
        update_user_credit(
            user_id=req.sitter_id,
            action="missed_checkin",
            reason=f"请求{request_id} 超过24小时未签到",
            idempotency_key=f"missed_checkin:{request_id}:{now.date()}",
        )

    # Rule 2: tasks incomplete today
    tasks = list(HouseTask.objects.filter(house_id=req.house_id))
    if tasks:
        today = now.date()
        done_task_ids = set(
            StayTaskProgress.objects.filter(
                request_id=request_id,
                status="done",
                update_time__date=today,
            ).values_list("task_id", flat=True)
        )
        incomplete = [t for t in tasks if t.task_id not in done_task_ids]
        if incomplete:
            if not _alert_exists_today(request_id, "task_incomplete", "medium"):
                alert = RiskAlert.objects.create(
                    house_id=req.house_id,
                    request_id=req.request_id,
                    alert_type="task_incomplete",
                    level="medium",
                    message=f"任务未完成：{len(incomplete)}/{len(tasks)}",
                    create_time=now,
                )
                created.append(alert)

            stay_status.aborrmal_flag = 1
            stay_status.update_time = now
            stay_status.save()

    return created

