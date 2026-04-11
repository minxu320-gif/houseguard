from django.urls import path
from . import views

urlpatterns = [
    path('', views.house_list, name='house_list'),
    path('<int:house_id>/', views.house_detail, name='house_detail'),
    path('my/', views.my_dashboard, name='my_dashboard'),
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('sitter/', views.sitter_dashboard, name='sitter_dashboard'),
    path('statistics/', views.statistics_view, name='statistics'),
    path('risk-alerts/', views.risk_alerts_view, name='risk_alerts'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('my/add_house/', views.add_house, name='add_house'),
    path('my/add_pet/', views.add_pet, name='add_pet'),
    path('request/<int:request_id>/<str:action>/', views.handle_request, name='handle_request'),
    path('agreement/<int:agreement_id>/', views.agreement_detail, name='agreement_detail'),
    path('agreement/sign/<int:agreement_id>/', views.sign_agreement, name='sign_agreement'),
    path('checkin/<int:request_id>/', views.daily_checkin, name='daily_checkin'),
    path('task-checkin/<int:request_id>/<int:task_id>/', views.task_checkin, name='task_checkin'),
    path('ai/score/<int:request_id>/', views.ai_score_assist, name='ai_score_assist'),
    path('rate/<int:request_id>/', views.submit_rating, name='submit_rating'),
]