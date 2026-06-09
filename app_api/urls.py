from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView

from app_api.views import *

urlpatterns = [
    # ── Misc ──────────────────────────────────────────────────
    path("", welcome_page, name="welcome"),
    path("api/test/", test_api, name="test-api"),

    # ── Auth ──────────────────────────────────────────────────
    path("api/auth/login/", login_view, name="auth-login"),
    path("api/auth/register/", register_view, name="auth-register"),
    path("api/auth/logout/", logout_view, name="auth-logout"),
    path("api/auth/me/", me, name="auth-me"),

    # Real-time availability checks (called while user types)
    path("api/auth/check-username/", check_username, name="auth-check-username"),
    path("api/auth/check-email/", check_email, name="auth-check-email"),
 
    # JWT token refresh (built-in SimpleJWT view)
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),

    # ── Entry Test Record Endpoints ────────────────────────────────────────────────
    path('api/admitted-patients-basic/', admitted_patients_basic, name='admitted-patients-basic'),
    path('api/account-heads/', account_heads_list, name='account-heads-list'),
    path('api/patient-test-entry/', patient_test_entry, name='patient-test-entry'),
    # ── Edit Test Record  Endpoints ────────────────────────────────────────────────
    path("api/test-records/", test_records_list,   name="test-records-list"),
    path("api/test-records/<int:pk>/", test_record_detail, name="test-record-detail"),

    # ── Admit Patient Endpoints ────────────────────────────────────────────────
    path("api/doctors/", doctor_list, name="doctor-list"),
    path("api/get-doctors-name/", get_doctor_name, name="doctor-name-list"),
    path("api/available-cabin-ward-details/", available_cabin_ward_details, name="available-cabin-ward-details"),
    path("api/all-cabin-ward-details/", all_cabin_ward_details, name="all-cabin-ward-details"),
    path("api/entry-admit-patient/", entry_admit_patient, name="entry-admit-patient"),
    path("api/view-admit-patient/", view_admit_patient, name="view-admit-patient"),
    path("api/edit-admit-patient/<int:patient_id>/", edit_admit_patient, name="edit-admit-patient"),

    # ── Discharge Processing Endpoints ───────────────────────────────
    path('api/admitted-list-for-discharged/', admitted_list_for_discharged, name='admitted_list_for_discharged'),
    path('api/discharge-patient/<str:patient_id>/', discharge_patient, name='discharge_patient'),
    path('api/preview-pdf-with-discharge-summary/<str:patient_id>/', pdf_discharge_summary, name='pdf_discharge_summary'),

    # ── Discharge Record Endpoints ───────────────────────────────
    path("api/discharged-records/", get_discharged_records,name="discharged_records_list"),
    path("api/discharged-record/<str:patient_id>/", get_discharged_record_detail, name="discharged_record_detail"),
    path("api/update-discharge-payment/<str:patient_id>/", update_discharge_payment, name="update_discharge_payment"),
    path("api/discharge-stats/", get_discharge_stats, name="discharge_stats"),

    # ── Administrative: Cabin Ward Endpoints ───────────────────────────────
    path('api/cabin-ward/', cabin_ward_list, name='cabin-ward-list'),
    path('api/cabin-ward/<int:pk>/', cabin_ward_detail, name='cabin-ward-detail'),
    
    # ── Administrative: Test Management Endpoints ──────────────────────────────────────────────────────────
    path('api/test-groups-list/', test_groups_list, name='test-group-list'),
    path('api/test-details/', TestDetailsListCreateView.as_view(), name='test-details-list'),
    path('api/test-details/<int:pk>/', TestDetailsDetailView.as_view(), name='test-details-detail'),

    # ── Report Endpoints ───────────────────────────────
    path('api/generate-admit-patient-pdf/', generate_admit_patient_pdf, name='generate_admit_patient_pdf'),
    path('api/discharge-report-pdf/', DischargeReportPdfView.as_view(), name='discharge_report_pdf'),
    path('api/available-cabin-ward-for-report/', available_cabin_ward_for_report, name='available_cabin_ward_for_report'),

    path('api/voucher-records/', get_voucher_records, name='get_voucher_records'),

    # ── Dashboard Endpoints ───────────────────────────────
    # path('api/dashboard/total-patients/', dashboard_total_patients, name='dashboard_total_patients'),
    # path('api/dashboard/total-doctors/', dashboard_total_doctors, name='dashboard_total_doctors'),
    # path('api/dashboard/total-cabin-wards/', dashboard_total_cabin_wards, name='dashboard_total_cabin_wards'),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
