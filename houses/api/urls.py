from django.urls import path

from houses.api import views

urlpatterns = [
    path("v1/health/", views.api_health, name="api_health"),
    path("v1/risk/summary/", views.api_risk_summary, name="api_risk_summary"),
]
