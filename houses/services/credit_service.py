"""
用户信用积分管理模块
提供信用分增减规则、总分查询及信用流水记录功能
"""

from django.db.models import Sum
from django.utils import timezone

from houses.models import UserCredit

# 信用分变动规则映射表
# 键为操作类型，值为对应的信用分变化值（正数为加分，负数为扣分）
CREDIT_ACTION_RULES = {
    "task_completed": 5,  # 完成任务奖励5分
    "daily_checkin": 2,  # 每日签到奖励2分
    "missed_checkin": -10,  # 漏签扣10分
}


def get_credit_total(user_id):
    """
    查询指定用户的当前信用总分
    通过聚合 UserCredit 表中所有该用户的 score_change 字段求和得到
    若用户尚无任何信用记录，返回 0
    """
    # 使用 aggregate 求和，结果可能是 None（无记录时），所以用 or 0 处理
    result = UserCredit.objects.filter(user_id=user_id).aggregate(
        total_score=Sum("score_change")
    )
    total = result.get("total_score") or 0
    return total


def update_user_credit(user_id, action, reason, idempotency_key=None):
    """
    增加一条信用变动记录，并返回本次变动的分数值

    参数:
        user_id: 用户ID
        action: 操作类型，必须在 CREDIT_ACTION_RULES 中定义
        reason: 变动原因说明
        idempotency_key: 幂等键（可选），用于防止重复提交。
                        若提供此参数，会先检查该用户是否存在 reason 字段包含该键的记录，
                        若已存在则直接返回0，避免重复记录。
    """
    # 校验操作类型是否合法
    if action not in CREDIT_ACTION_RULES:
        raise ValueError(f"未知的信用操作类型: {action}")

    # 获取本次变动的分数差值
    score_delta = CREDIT_ACTION_RULES[action]

    # 幂等性检查：如果传入了幂等键，则查询是否已存在包含该键的记录
    if idempotency_key is not None:
        already_exists = UserCredit.objects.filter(
            user_id=user_id,
            reason__contains=idempotency_key
        ).exists()
        if already_exists:
            # 已处理过相同请求，直接返回 0，不重复记录
            return 0

    # 构造最终的变动原因文本，如果存在幂等键则追加标识
    final_reason = reason
    if idempotency_key is not None:
        final_reason = f"{reason} [{idempotency_key}]"

    # 创建信用流水记录
    UserCredit.objects.create(
        user_id=user_id,
        score_change=score_delta,
        reason=final_reason,
        create_time=timezone.now(),
    )

    return score_delta