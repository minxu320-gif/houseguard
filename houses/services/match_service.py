from decimal import Decimal

from django.utils import timezone

from houses.models import StayMatchScore, StayRequest, House, UserProfile, Rating, UserCredit
from django.db.models import Avg, Sum


def _clamp(num, lo, hi):
    return max(lo, min(hi, num))


def _experience_score(sitter_id):
    profile = UserProfile.objects.filter(user_id=sitter_id).first()
    level = profile.experience_level if profile and profile.experience_level is not None else 0
    # map 0-10 to 0-100
    return Decimal(_clamp(level, 0, 10) * 10)


def _credit_score(user_id):
    credit_total = UserCredit.objects.filter(user_id=user_id).aggregate(total=Sum("score_change"))["total"] or 0
    avg_rating = Rating.objects.filter(target_id=user_id).aggregate(avg=Avg("score"))["avg"]
    avg_rating = float(avg_rating) if avg_rating is not None else 3.0
    # rating 1-5 => 0-100
    rating_score = (avg_rating - 1.0) / 4.0 * 100.0
    # credit_total roughly normalized (-50..+50) => 0..100
    credit_norm = _clamp((credit_total + 50) / 100 * 100, 0, 100)
    return Decimal(round(0.6 * credit_norm + 0.4 * rating_score, 2))


def _time_match_score(house, req):
    # overlap ratio between requested range and house availability, mapped to 0..100
    req_days = (req.end_date - req.start_date).days + 1
    start = max(req.start_date, house.available_from)
    end = min(req.end_date, house.available_to)
    overlap_days = (end - start).days + 1 if end >= start else 0
    ratio = overlap_days / req_days if req_days > 0 else 0
    return Decimal(round(_clamp(ratio, 0, 1) * 100, 2))


def calculate_match_score(request_id):
    """
    Create or update StayMatchScore for a StayRequest and return it.
    """
    req = StayRequest.objects.filter(request_id=request_id).first()
    if not req:
        return None
    house = House.objects.filter(house_id=req.house_id).first()
    if not house:
        return None

    exp = _experience_score(req.sitter_id)
    credit = _credit_score(req.sitter_id)
    time_score = _time_match_score(house, req)

    # weights: exp 0.4, credit 0.4, time 0.2
    total = (exp * Decimal("0.4")) + (credit * Decimal("0.4")) + (time_score * Decimal("0.2"))
    total = Decimal(round(float(total), 2))

    remark = (
        f"experience_score={exp}（经验等级映射）; "
        f"credit_score={credit}（信用流水+平均评分）; "
        f"time_match_score={time_score}（时间覆盖比例）; "
        f"total_score={total}（0.4/0.4/0.2 加权）"
    )

    obj, _ = StayMatchScore.objects.get_or_create(
        request_id=request_id,
        defaults={
            "total_score": total,
            "experience_score": exp,
            "credit_score": credit,
            "time_match_score": time_score,
            "remark": remark,
        },
    )
    # update on recalculation
    obj.total_score = total
    obj.experience_score = exp
    obj.credit_score = credit
    obj.time_match_score = time_score
    obj.remark = remark
    obj.save()
    return obj

