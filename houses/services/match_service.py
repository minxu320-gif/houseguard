"""
看护请求匹配度评分计算模块
根据看护人经验、信用记录和时间匹配度综合评估请求适配程度
"""

from decimal import Decimal

from django.db.models import Avg, Sum
from django.utils import timezone

from houses.models import House, Rating, StayMatchScore, StayRequest, UserCredit, UserProfile


def _clamp_value(value, min_val, max_val):
    """
    将数值限制在指定区间内
    """
    return max(min_val, min(value, max_val))


def _calc_experience_score(sitter_id):
    """
    计算看护人经验分（0-100）
    基于用户资料中的经验等级（0-10）线性映射
    """
    # 获取看护人资料
    user_profile = UserProfile.objects.filter(user_id=sitter_id).first()
    if user_profile and user_profile.experience_level is not None:
        experience_level = user_profile.experience_level
    else:
        experience_level = 0

    # 经验等级0-10映射到0-100分，超出范围则钳位
    clamped_level = _clamp_value(experience_level, 0, 10)
    score = Decimal(clamped_level * 10)
    return score


def _calc_credit_score(user_id):
    """
    计算信用分（0-100）
    综合信用流水（60%权重）和历史评价均分（40%权重）
    """
    # 1. 信用流水总分
    credit_result = UserCredit.objects.filter(user_id=user_id).aggregate(
        total_credit=Sum("score_change")
    )
    total_credit = credit_result.get("total_credit") or 0

    # 2. 历史评价均分（默认3.0分）
    rating_result = Rating.objects.filter(target_id=user_id).aggregate(
        avg_rating=Avg("score")
    )
    avg_rating = rating_result.get("avg_rating")
    if avg_rating is None:
        avg_rating = 3.0
    else:
        avg_rating = float(avg_rating)

    # 评价均分从1-5映射到0-100
    rating_score = (avg_rating - 1.0) / 4.0 * 100.0

    # 信用流水归一化：假设信用分大致在-50到+50区间，映射到0-100
    credit_norm = (total_credit + 50) / 100 * 100
    credit_norm = _clamp_value(credit_norm, 0, 100)

    # 加权计算：信用流水占60%，评价均分占40%
    final_score = 0.6 * credit_norm + 0.4 * rating_score
    return Decimal(round(final_score, 2))


def _calc_time_match_score(house_obj, request_obj):
    """
    计算时间匹配分（0-100）
    基于请求日期与房源可用日期的重叠比例
    """
    # 请求总天数
    request_days = (request_obj.end_date - request_obj.start_date).days + 1

    # 计算重叠日期区间
    overlap_start = max(request_obj.start_date, house_obj.available_from)
    overlap_end = min(request_obj.end_date, house_obj.available_to)

    if overlap_end >= overlap_start:
        overlap_days = (overlap_end - overlap_start).days + 1
    else:
        overlap_days = 0

    # 重叠比例
    if request_days > 0:
        overlap_ratio = overlap_days / request_days
    else:
        overlap_ratio = 0

    clamped_ratio = _clamp_value(overlap_ratio, 0, 1)
    score = Decimal(round(clamped_ratio * 100, 2))
    return score


def calculate_match_score(request_id):
    """
    计算或更新指定看护请求的匹配得分记录

    参数:
        request_id: 看护请求的ID

    返回:
        StayMatchScore 对象，若请求或房源不存在则返回 None
    """
    # 获取请求对象
    stay_request = StayRequest.objects.filter(request_id=request_id).first()
    if not stay_request:
        return None

    # 获取关联的房源对象
    house = House.objects.filter(house_id=stay_request.house_id).first()
    if not house:
        return None

    # 计算三个维度的得分
    exp_score = _calc_experience_score(stay_request.sitter_id)
    credit_score = _calc_credit_score(stay_request.sitter_id)
    time_score = _calc_time_match_score(house, stay_request)

    # 加权计算总分：经验分40% + 信用分40% + 时间匹配分20%
    weight_exp = Decimal("0.4")
    weight_credit = Decimal("0.4")
    weight_time = Decimal("0.2")

    total_score = (exp_score * weight_exp) + (credit_score * weight_credit) + (time_score * weight_time)
    total_score = Decimal(round(float(total_score), 2))

    # 生成备注信息，便于追溯
    remark_message = (
        f"experience_score={exp_score}（经验等级映射）; "
        f"credit_score={credit_score}（信用流水+平均评分）; "
        f"time_match_score={time_score}（时间覆盖比例）; "
        f"total_score={total_score}（0.4/0.4/0.2 加权）"
    )

    # 创建或更新匹配得分记录
    match_score_obj, created = StayMatchScore.objects.get_or_create(
        request_id=request_id,
        defaults={
            "total_score": total_score,
            "experience_score": exp_score,
            "credit_score": credit_score,
            "time_match_score": time_score,
            "remark": remark_message,
        },
    )

    # 如果是已存在的记录，更新各字段值
    if not created:
        match_score_obj.total_score = total_score
        match_score_obj.experience_score = exp_score
        match_score_obj.credit_score = credit_score
        match_score_obj.time_match_score = time_score
        match_score_obj.remark = remark_message
        match_score_obj.save()

    return match_score_obj