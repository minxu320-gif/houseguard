"""Dashboard-related business logic (keeps views thin)."""

from __future__ import annotations

from django.conf import settings
from django.db.models import Sum

from houses.models import House, StayAgreement, StayRequest, UserCredit


def build_agreements_with_perms(agreements, user_id: int):
    """
    Attach signing permissions without N+1 queries on StayRequest/House.
    agreements: queryset or list of StayAgreement.
    """
    agreements = list(agreements)
    if not agreements:
        return []

    request_ids = [a.request_id for a in agreements]
    reqs = StayRequest.objects.filter(request_id__in=request_ids)
    req_map = {r.request_id: r for r in reqs}
    house_ids = {r.house_id for r in req_map.values()}
    house_map = {h.house_id: h for h in House.objects.filter(house_id__in=house_ids)}

    out = []
    for a in agreements:
        req = req_map.get(a.request_id)
        if not req:
            continue
        house = house_map.get(req.house_id)
        if not house:
            continue
        out.append(
            {
                "agreement": a,
                "can_sign_by_sitter": (user_id == req.sitter_id and not a.signed_by_sitter),
                "can_sign_by_host": (user_id == house.owner_id and not a.signed_by_host),
            }
        )
    return out


def owner_credit_total(user_id: int) -> int:
    return UserCredit.objects.filter(user_id=user_id).aggregate(total=Sum("score_change"))["total"] or 0


def media_url() -> str:
    return settings.MEDIA_URL
