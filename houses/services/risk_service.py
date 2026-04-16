"""
寄养订单风险检测模块
定时检测签到状态和任务完成情况，生成风险告警并更新订单异常标识
"""

from datetime import timedelta

from django.utils import timezone

from houses.constants import RISK_LEVEL_CRITICAL, RISK_LEVEL_HIGH, RISK_LEVEL_MEDIUM
from houses.models import (
    HouseTask,
    RiskAlert,
    StayCheckinLog,
    StayRequest,
    StayStatus,
    StayTaskProgress,
)
from houses.services.credit_service import update_user_credit


def _check_alert_exists_today(request_id, alert_type, level):
    """
    检查指定请求在今天是否已经生成过相同类型和等级的风险告警
    用于防止同一天内重复生成告警
    """
    today_date = timezone.now().date()
    exists = RiskAlert.objects.filter(
        request_id=request_id,
        alert_type=alert_type,
        level=level,
        create_time__date=today_date,
    ).exists()
    return exists


def check_risk(request_id):
    """
    对指定的寄养请求进行风险检测

    检测规则：
    1. 超过24小时未签到 -> 生成高风险告警，超过48小时升级为严重告警
    2. 当日有房屋任务未完成 -> 生成中风险告警

    检测后会：
    - 创建相应的 RiskAlert 记录
    - 更新 StayStatus 的异常标识
    - 对超时未签到情况扣除看护人信用分

    返回本次新创建的告警对象列表
    """
    created_alert_list = []
    current_time = timezone.now()

    # 获取寄养请求，仅处理状态为 approved（已批准）的请求
    stay_request = StayRequest.objects.filter(request_id=request_id).first()
    if not stay_request or stay_request.status != "approved":
        return created_alert_list

    # 检查当前日期是否在寄养时间范围内，不在范围内则无需检测
    if not (stay_request.start_date <= current_time.date() <= stay_request.end_date):
        return created_alert_list

    # 获取或创建寄养状态记录
    stay_status, _ = StayStatus.objects.get_or_create(
        request_id=request_id,
        defaults={
            "current_status": "active",
            "checkin_required": 1,
            "last_checkin_time": None,
            "aborrmal_flag": 0,
            "update_time": current_time,
        },
    )

    # ---------- 规则1：签到超时检测 ----------
    # 获取最近一次签到时间，优先使用 StayStatus 中记录的，若无则从签到日志表查询
    last_checkin_time = stay_status.last_checkin_time
    if last_checkin_time is None:
        # 查询该请求最近的一条签到记录时间
        latest_checkin = StayCheckinLog.objects.filter(request_id=request_id).order_by(
            "-checkin_time"
        ).values_list("checkin_time", flat=True).first()
        last_checkin_time = latest_checkin

    # 判断是否超时：从未签到 或 距离上次签到超过24小时
    is_overdue = (last_checkin_time is None) or (
        (current_time - last_checkin_time) > timedelta(hours=24)
    )

    if is_overdue:
        # 计算具体超时时长，用于分级
        if last_checkin_time is None:
            hours_since_last = 999  # 从未签到的极端情况
        else:
            seconds_diff = (current_time - last_checkin_time).total_seconds()
            hours_since_last = seconds_diff / 3600

        # 根据超时时长确定告警等级和类型
        if hours_since_last >= 48:
            alert_level = RISK_LEVEL_CRITICAL
            alert_msg = "超过48小时未签到（严重）"
            alert_type = "checkin_overdue_critical"
        else:
            alert_level = RISK_LEVEL_HIGH
            alert_msg = "超过24小时未签到"
            alert_type = "checkin_overdue"

        # 检查今天是否已生成过同类告警，避免重复
        already_exists = _check_alert_exists_today(request_id, alert_type, alert_level)
        if not already_exists:
            new_alert = RiskAlert.objects.create(
                house_id=stay_request.house_id,
                request_id=stay_request.request_id,
                alert_type=alert_type,
                level=alert_level,
                message=alert_msg,
                create_time=current_time,
            )
            created_alert_list.append(new_alert)

        # 更新寄养状态为异常
        stay_status.aborrmal_flag = 1
        stay_status.update_time = current_time
        stay_status.save()

        # 扣除信用分，使用幂等键确保同一天内不会重复扣分
        update_user_credit(
            user_id=stay_request.sitter_id,
            action="missed_checkin",
            reason=f"请求{request_id} 超过24小时未签到",
            idempotency_key=f"missed_checkin:{request_id}:{current_time.date()}",
        )

    # ---------- 规则2：当日任务完成情况检测 ----------
    # 获取该房源关联的所有任务
    task_list = list(HouseTask.objects.filter(house_id=stay_request.house_id))
    if task_list:
        today_date = current_time.date()
        # 查询当日已完成的任务ID
        done_task_ids = set(
            StayTaskProgress.objects.filter(
                request_id=request_id,
                status="done",
                update_time__date=today_date,
            ).values_list("task_id", flat=True)
        )

        # 筛选出未完成的任务
        incomplete_tasks = [
            task for task in task_list if task.task_id not in done_task_ids
        ]

        if incomplete_tasks:
            # 检查今天是否已生成过任务未完成告警
            already_exists = _check_alert_exists_today(
                request_id, "task_incomplete", RISK_LEVEL_MEDIUM
            )
            if not already_exists:
                incomplete_count = len(incomplete_tasks)
                total_count = len(task_list)
                new_alert = RiskAlert.objects.create(
                    house_id=stay_request.house_id,
                    request_id=stay_request.request_id,
                    alert_type="task_incomplete",
                    level=RISK_LEVEL_MEDIUM,
                    message=f"任务未完成：{incomplete_count}/{total_count}",
                    create_time=current_time,
                )
                created_alert_list.append(new_alert)

            # 更新异常标识
            stay_status.aborrmal_flag = 1
            stay_status.update_time = current_time
            stay_status.save()

    return created_alert_list