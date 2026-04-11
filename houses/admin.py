from django.contrib import admin

from .models import (
    House,
    HouseTask,
    Pet,
    Rating,
    RiskAlert,
    SensorData,
    Statistics,
    StayAgreement,
    StayCheckinLog,
    StayMatchScore,
    StayRequest,
    StayStatus,
    StayTaskProgress,
    SystemLog,
    User,
    UserCredit,
    UserProfile,
)

admin.site.site_header = "HouseGuard 后台"
admin.site.site_title = "HouseGuard"
admin.site.index_title = "数据管理"


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("user_id", "username", "role", "create_time")
    list_filter = ("role",)
    search_fields = ("username",)
    ordering = ("-create_time",)
    readonly_fields = ("user_id", "create_time")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user_id", "real_name", "phone", "email", "gender", "experience_level")
    search_fields = ("real_name", "phone", "email", "user_id")
    ordering = ("user_id",)


@admin.register(UserCredit)
class UserCreditAdmin(admin.ModelAdmin):
    list_display = ("log_id", "user_id", "score_change", "reason", "create_time")
    list_filter = ("create_time", "score_change")
    search_fields = ("user_id", "reason")
    ordering = ("-create_time",)
    readonly_fields = ("log_id", "create_time")
    date_hierarchy = "create_time"


@admin.register(House)
class HouseAdmin(admin.ModelAdmin):
    list_display = ("house_id", "owner_id", "address", "has_pet", "available_from", "available_to", "create_time")
    list_filter = ("has_pet", "available_from", "create_time")
    search_fields = ("address", "house_id", "owner_id")
    ordering = ("-create_time",)
    readonly_fields = ("house_id", "create_time")
    date_hierarchy = "create_time"


@admin.register(HouseTask)
class HouseTaskAdmin(admin.ModelAdmin):
    list_display = ("task_id", "house_id", "task_type", "frequency", "description")
    list_filter = ("task_type", "frequency")
    search_fields = ("task_id", "house_id", "description")
    ordering = ("house_id", "task_id")


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = ("pet_id", "house_id", "name", "type", "age")
    list_filter = ("type",)
    search_fields = ("name", "house_id", "pet_id")
    ordering = ("house_id",)


@admin.register(StayRequest)
class StayRequestAdmin(admin.ModelAdmin):
    list_display = ("request_id", "house_id", "sitter_id", "start_date", "end_date", "status", "create_time")
    list_filter = ("status", "start_date", "create_time")
    search_fields = ("request_id", "house_id", "sitter_id", "reason")
    ordering = ("-create_time",)
    readonly_fields = ("request_id", "create_time")
    date_hierarchy = "create_time"


@admin.register(StayAgreement)
class StayAgreementAdmin(admin.ModelAdmin):
    list_display = (
        "agreement_id",
        "request_id",
        "status",
        "signed_by_host",
        "signed_by_sitter",
        "sitter_signed_at",
        "owner_signed_at",
        "sign_time",
    )
    list_filter = ("status", "sign_time", "sitter_signed_at")
    search_fields = ("agreement_id", "request_id", "pdf_path")
    ordering = ("-agreement_id",)
    readonly_fields = ("agreement_id",)


@admin.register(StayStatus)
class StayStatusAdmin(admin.ModelAdmin):
    list_display = (
        "status_id",
        "request_id",
        "current_status",
        "checkin_required",
        "last_checkin_time",
        "aborrmal_flag",
        "update_time",
    )
    list_filter = ("current_status", "checkin_required", "aborrmal_flag")
    search_fields = ("request_id", "status_id")
    ordering = ("-update_time",)


@admin.register(StayCheckinLog)
class StayCheckinLogAdmin(admin.ModelAdmin):
    list_display = ("check_id", "request_id", "checkin_time", "location", "remark")
    list_filter = ("checkin_time",)
    search_fields = ("request_id", "location", "remark")
    ordering = ("-checkin_time",)
    date_hierarchy = "checkin_time"


@admin.register(StayTaskProgress)
class StayTaskProgressAdmin(admin.ModelAdmin):
    list_display = ("progress_id", "request_id", "task_id", "status", "update_time", "remark")
    list_filter = ("status", "update_time")
    search_fields = ("request_id", "task_id", "remark")
    ordering = ("-update_time",)


@admin.register(StayMatchScore)
class StayMatchScoreAdmin(admin.ModelAdmin):
    list_display = (
        "score_id",
        "request_id",
        "total_score",
        "experience_score",
        "credit_score",
        "time_match_score",
        "remark",
    )
    search_fields = ("request_id", "remark")
    ordering = ("-total_score",)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("rating_id", "request_id", "rater_id", "target_id", "score", "create_time")
    list_filter = ("score", "create_time")
    search_fields = ("request_id", "rater_id", "target_id", "comment")
    ordering = ("-create_time",)
    date_hierarchy = "create_time"


@admin.register(RiskAlert)
class RiskAlertAdmin(admin.ModelAdmin):
    list_display = ("alert_id", "house_id", "request_id", "alert_type", "level", "message", "create_time")
    list_filter = ("level", "alert_type", "create_time")
    search_fields = ("message", "house_id", "request_id", "alert_id")
    ordering = ("-create_time",)
    date_hierarchy = "create_time"


@admin.register(SensorData)
class SensorDataAdmin(admin.ModelAdmin):
    list_display = ("data_id", "house_id", "sensor_type", "value", "record_time")
    list_filter = ("sensor_type", "record_time")
    search_fields = ("house_id", "value")
    ordering = ("-record_time",)
    date_hierarchy = "record_time"


@admin.register(Statistics)
class StatisticsAdmin(admin.ModelAdmin):
    list_display = ("stat_id", "stat_type", "target_id", "metric", "metric_value", "stat_date", "create_time")
    list_filter = ("stat_type", "stat_date", "metric")
    search_fields = ("target_id", "metric")
    ordering = ("-create_time",)
    date_hierarchy = "stat_date"


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ("log_id", "create_time", "log_level", "user_id", "role", "action", "target_type", "target_id", "ip_address")
    list_filter = ("log_level", "role", "action", "create_time")
    search_fields = ("action", "user_id", "target_id", "ip_address", "target_type")
    ordering = ("-create_time",)
    readonly_fields = ("log_id", "create_time")
    date_hierarchy = "create_time"
