# client/app_api/views.py
import json
import logging
from django.utils import timezone
from datetime import timedelta
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q

from rest_framework.response import Response
from rest_framework.views import APIView, settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

# PDF generation imports: ReportLab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas as pdfgen_canvas
from reportlab.platypus.flowables import HRFlowable

from io import BytesIO
from datetime import datetime
import io
from django.utils.decorators import method_decorator


from app_model.models import *
from app_model.serializers import TestDetailsSerializer, TestGroupSerializer


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Misc
# ─────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def welcome_page(request):
    return HttpResponse("<h2>Congratulations, Django App Successfully run!</h2>")


@api_view(["GET"])
@permission_classes([AllowAny])
def test_api(request):
    return Response({"message": "Hello, this is from Django!"})



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """GET /api/auth/me/ — returns the currently authenticated user."""
    return Response({"user": user_payload(request.user)})


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
 
def get_tokens_for_user(user):
    """Return a fresh refresh + access token pair for the given user."""
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "token":   str(refresh.access_token),   # "token" matches your React code
    }
 
 
def user_payload(user):
    """
    Full user dict sent back to the frontend.
    Includes UserDetails fields when the related row exists.
    """
    payload = {
        "id":         user.id,
        "username":   user.username,
        "email":      user.email,
        "first_name": user.first_name,
        "last_name":  user.last_name,
        # UserDetails fields — safe defaults if row is missing
        "mobile_no":      None,
        "user_category":  "pending",
        "user_role":      "pending",
        "user_status":    "pending",
    }
 
    # OneToOneField reverse accessor — guard against missing row
    try:
        details = user.details          # related_name="details"
        payload.update({
            "mobile_no":     details.mobile_no,
            "user_category": details.user_category,
            "user_role":     details.user_role,
            "user_status":   details.user_status,
        })
    except UserDetails.DoesNotExist:
        pass                            # defaults already set above
 
    return payload
 
 
# ─────────────────────────────────────────────
#  Sign-In
# ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    """
    POST /api/auth/login/
    Body: { "username": "...", "password": "..." }
    Returns: { "token": "...", "refresh": "...", "user": {...} }
    """
    username = request.data.get("username", "").strip()
    password = request.data.get("password", "")
 
    if not username or not password:
        return Response(
            {"message": "Username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    # Allow login by email as well
    if "@" in username:
        try:
            user_obj = User.objects.get(email__iexact=username)
            username = user_obj.username
        except User.DoesNotExist:
            pass  # Fall through to authenticate() which will fail and return 401
 
    user = authenticate(request, username=username, password=password)
 
    if user is None:
        logger.warning("Failed login attempt for identifier: %s", username)
        return Response(
            {"message": "Invalid username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
 
    if not user.is_active:
        return Response(
            {"message": "This account has been disabled."},
            status=status.HTTP_403_FORBIDDEN,
        )
 
    tokens = get_tokens_for_user(user)
    logger.info("User logged in: %s", user.username)
 
    return Response(
        {**tokens, "user": user_payload(user)},
        status=status.HTTP_200_OK,
    )
 
# ─────────────────────────────────────────────
#  Sign-Up
# ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([AllowAny])
def signup_view(request):
    """
    POST /api/auth/signup/
    Body: {
        "username":   "...",
        "email":      "...",
        "password":   "...",
        "first_name": "...",   # optional
        "last_name":  "..."    # optional
    }
    Returns: { "token": "...", "refresh": "...", "user": {...} }
    """
    data       = request.data
    username   = data.get("username",   "").strip()
    email      = data.get("email",      "").strip().lower()
    password   = data.get("password",   "")
    first_name = data.get("first_name", "").strip()
    last_name  = data.get("last_name",  "").strip()
 
    # ── Basic validation ──────────────────────
    errors = {}
 
    if not username:
        errors["username"] = "Username is required."
    elif len(username) < 3:
        errors["username"] = "Username must be at least 3 characters."
    elif User.objects.filter(username__iexact=username).exists():
        errors["username"] = "That username is already taken."
 
    if not email:
        errors["email"] = "Email is required."
    elif User.objects.filter(email__iexact=email).exists():
        errors["email"] = "An account with that email already exists."
 
    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 6:
        errors["password"] = "Password must be at least 6 characters."
 
    if errors:
        return Response(
            {"message": "Validation failed.", "errors": errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    # ── Create User + UserDetails atomically ─
    from django.db import transaction
 
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
 
        # Companion UserDetails row — fields default to "pending" per model
        UserDetails.objects.create(
            user=user,
            user_name=username,
            mobile_no=data.get("mobile_no", "").strip() or None,
        )
 
    tokens = get_tokens_for_user(user)
    logger.info("New user registered: %s (%s)", user.username, user.email)
 
    return Response(
        {**tokens, "user": user_payload(user)},
        status=status.HTTP_201_CREATED,
    )
 
 
# ─────────────────────────────────────────────
#  Logout  (blacklists the refresh token)
# ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    POST /api/auth/logout/
    Header: Authorization: Bearer <access_token>
    Body:   { "refresh": "..." }   ← optional but recommended to blacklist it
    """
    refresh_token = request.data.get("refresh")
 
    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            logger.warning("Logout with invalid/expired refresh token: %s", e)
            # Still return 200 — the access token is gone from the client anyway
 
    logger.info("User logged out: %s", request.user.username)
    return Response({"message": "Logged out successfully."}, status=status.HTTP_200_OK)
 
 
# ─────────────────────────────────────────────
#  Username availability check
# ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([AllowAny])
def check_username(request):
    """
    POST /api/auth/check-username/
    Body: { "username": "..." }
    Returns: { "available": true | false, "message": "..." }
 
    Called by SignUp in real-time (debounced 500 ms) as the user types.
    """
    username = request.data.get("username", "").strip()
 
    if not username:
        return Response(
            {"available": False, "message": "Username is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    if len(username) < 3:
        return Response(
            {"available": False, "message": "Username must be at least 3 characters."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    if len(username) > 50:
        return Response(
            {"available": False, "message": "Username must be less than 50 characters."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return Response(
            {"available": False, "message": "Username can only contain letters, numbers, and underscores."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    exists = User.objects.filter(username__iexact=username).exists()
    return Response(
        {
            "available": not exists,
            "message": "Username is taken." if exists else "Username is available.",
        },
        status=status.HTTP_200_OK,
    )
 
 
# ─────────────────────────────────────────────
#  Email availability check
# ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([AllowAny])
def check_email(request):
    """
    POST /api/auth/check-email/
    Body: { "email": "..." }
    Returns: { "available": true | false, "message": "..." }
 
    Called by SignUp in real-time (debounced 500 ms) as the user types.
    """
    email = request.data.get("email", "").strip().lower()
 
    if not email:
        return Response(
            {"available": False, "message": "Email is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    import re
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return Response(
            {"available": False, "message": "Please enter a valid email address."},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    exists = User.objects.filter(email__iexact=email).exists()
    return Response(
        {
            "available": not exists,
            "message": "Email is already registered." if exists else "Email is available.",
        },
        status=status.HTTP_200_OK,
    )
 
 
# ─────────────────────────────────────────────
#  Register  (called by the SignUp form submit)
# ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    """
    POST /api/auth/register/
    Body: {
        "username": "...",
        "email":    "...",
        "password": "...",
        "role":     "user"      ← sent by your React form (stored in UserDetails)
        "isActive": true        ← sent by your React form
    }
    Returns: { "token": "...", "refresh": "...", "user": {...} }
 
    This is the endpoint your SignUp.tsx handleSubmit() POSTs to.
    It mirrors signup_view but accepts the extra fields React sends.
    """
    from django.db import transaction
 
    data     = request.data
    username = data.get("username", "").strip()
    email    = data.get("email",    "").strip().lower()
    password = data.get("password", "")
    role     = data.get("role",     "pending").strip()   # React sends "user"
    is_active_flag = data.get("isActive", True)          # React sends true
 
    # ── Validation ────────────────────────────
    errors = {}
 
    if not username:
        errors["username"] = "Username is required."
    elif len(username) < 3:
        errors["username"] = "Username must be at least 3 characters."
    elif len(username) > 50:
        errors["username"] = "Username must be less than 50 characters."
    elif User.objects.filter(username__iexact=username).exists():
        errors["username"] = "That username is already taken."
 
    if not email:
        errors["email"] = "Email is required."
    elif User.objects.filter(email__iexact=email).exists():
        errors["email"] = "An account with that email already exists."
 
    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 8:                              # SignUp page requires 8+
        errors["password"] = "Password must be at least 8 characters."
 
    if errors:
        return Response(
            {"message": "Validation failed.", "errors": errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    # ── Create User + UserDetails atomically ─
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=bool(is_active_flag),
        )
 
        UserDetails.objects.create(
            user=user,
            user_name=username,
            user_role=role,          # stores "user" sent from React
            # user_category and user_status stay "pending" (model defaults)
        )
 
    tokens = get_tokens_for_user(user)
    logger.info("New user registered via /register: %s (%s)", user.username, user.email)
 
    return Response(
        {**tokens, "user": user_payload(user)},
        status=status.HTTP_201_CREATED,
    )
 


@api_view(["GET"])
@permission_classes([AllowAny])
def doctor_list(request):
    doctors = DoctorDetails.objects.order_by("doctor_name").values(
        "id",
        "doctor_name",
        "specialization",
    )
    return Response({
        "message": "Doctors retrieved successfully.",
        "doctors": list(doctors),
        "success": True,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def get_doctor_name(request):
    doctors = DoctorDetails.objects.order_by("doctor_name").values(
        "id",
        "doctor_name",
    )
    return Response({
        "message": "Doctors retrieved successfully.",
        "doctors": list(doctors),
        "success": True,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def available_cabin_ward_details(request):
    details = CabinWardDetails.objects.order_by("cabin_ward_no").filter(is_available=True).values(
        "id",
        "cabin_ward_no",
        "cabin_ward_charge",
        "service_charge",
    )
    return Response({
        "message": "Cabin/Ward details retrieved successfully.",
        "cabin_ward_details": list(details),
        "success": True,
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def all_cabin_ward_details(request):
    details = CabinWardDetails.objects.order_by("cabin_ward_no").values(
        "id",
        "cabin_ward_no",
        "cabin_ward_charge",
        "service_charge",
        "is_available",
    )
    return Response({
        "message": "Cabin/Ward details retrieved successfully.",
        "cabin_ward_details": list(details),
        "success": True,
    })


# ─────────────────────────────────────────────
# Test Entry Api
# ─────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([AllowAny])
def admitted_patients_basic(request):
    try:
        patients = AdmitPatient.objects.select_related('admit_doctor_by').values(
            'id',
            'patient_id',
            'name',
            'age',
            'blood_group',
            'contact_number',
            'admit_doctor_by_id',   # FK id for doctor auto-fill
        ).order_by('name')
 
        patient_list = [
            {
                'id': p['id'],
                'patient_id': p['patient_id'],
                'name': p['name'],
                'age': p['age'],
                'blood_group': p['blood_group'],
                'contact_number': p['contact_number'],
                'admit_doctor_by': p['admit_doctor_by_id'],
            }
            for p in patients
        ]
        return JsonResponse({'success': True, 'patients': patient_list})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
 
 
# ─────────────────────────────────────────────
# GET /api/account-heads/
# Returns all account heads; frontend auto-selects the one named "Test"
# ─────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([AllowAny])
def account_heads_list(request):
    try:
        heads = AccountHead.objects.select_related('account_head_type').values(
            'id', 'account_head_code', 'account_head_name'
        ).order_by('account_head_name')
 
        return JsonResponse({'success': True, 'account_heads': list(heads)})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
 
 
# ─────────────────────────────────────────────
# POST /api/patient-test-entry/
# Save a new patient test record + create a voucher
# ─────────────────────────────────────────────
@api_view(["POST"])
@permission_classes([AllowAny])
def patient_test_entry(request):
    try:
        data = json.loads(request.body)

        # ── Resolve admitted patient (only for 'Admitted' type) ──
        admitted_patient = None
        if data.get('patient_type') == 'Admitted' and data.get('patient_id'):
            admitted_patient = AdmitPatient.objects.filter(
                patient_id=data['patient_id']
            ).first()
            if not admitted_patient:
                return JsonResponse(
                    {'success': False, 'error': 'Admitted patient not found'},
                    status=400
                )

        # ── Resolve doctor (optional) ──
        test_doctor = None
        if data.get('test_doctor_by'):
            test_doctor = DoctorDetails.objects.filter(
                id=data['test_doctor_by']
            ).first()

        # ── Resolve account head (optional) ──
        account_head_obj = None
        if data.get('account_head'):
            account_head_obj = AccountHead.objects.filter(
                id=data['account_head']
            ).first()

        # ── Validate tests list ──
        tests_payload = data.get('tests', [])   # [{id, price_at_entry}, ...]
        if not tests_payload:
            return JsonResponse(
                {'success': False, 'error': 'At least one test must be selected'},
                status=400
            )

        # Fetch all TestDetails objects up front to validate every id
        test_ids = [item['id'] for item in tests_payload]
        test_objs = {
            t.id: t
            for t in TestDetails.objects.filter(id__in=test_ids)
        }
        missing = [tid for tid in test_ids if tid not in test_objs]
        if missing:
            return JsonResponse(
                {'success': False, 'error': f'Invalid test id(s): {missing}'},
                status=400
            )

        # ── Create the parent TestsRecord ──
        discount = data.get('provided_discount')
        total    = data.get('total_test_amount')

        record = TestsRecord.objects.create(
            test_date        = data.get('test_date'),
            patient_type     = data.get('patient_type'),
            admitted_patient = admitted_patient,
            name             = data.get('name', '').strip(),
            age              = data.get('age') or None,
            blood_group      = data.get('blood_group') or None,
            mobile           = data.get('mobile', '').strip(),
            test_doctor_by   = test_doctor,
            provided_discount= int(discount) if discount is not None else None,
            total_test_amount= int(total)    if total    is not None else None,
            created_by       = data.get('created_by') or None,
        )

        # ── Create one TestsRecordItem per test ──
        items = [
            TestsRecordItem(
                tests_record = record,
                # test         = test_objs[item['id']],
                test_amount  = int(item.get('price_at_entry') or 0),
            )
            for item in tests_payload
        ]
        TestsRecordItem.objects.bulk_create(items)

        # ── Create a single voucher for the whole visit (if account head present) ──
        if account_head_obj and total:
            VoucherDetails.objects.create(
                account_head     = account_head_obj,
                amount           = int(total),
                transaction_type = 'credit',
                account_head_type = 'income',
                comments         = (
                    f"Test charges for {record.name} "
                    f"(Record #{record.test_id}) — "
                    f"{len(items)} test(s)"
                    + (f", {discount}% discount applied" if discount else "")
                ),
            )

        return JsonResponse({
            'success'  : True,
            'message'  : 'Test record saved successfully',
            'test_id'  : record.test_id,
            'entry_id' : record.id,
        }, status=201)

    except json.JSONDecodeError:
        return JsonResponse(
            {'success': False, 'error': 'Invalid JSON payload'},
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'success': False, 'error': str(e)},
            status=500
        )



@api_view(["GET"])
@permission_classes([AllowAny])
def test_records_list(request):
    """
    GET /api/test-records/
    Query params: page, page_size, search
    """
    search     = request.GET.get("search", "").strip()
    page_num   = int(request.GET.get("page", 1))
    page_size  = int(request.GET.get("page_size", 20))

    qs = TestsRecord.objects.select_related(
        "admitted_patient", "test_doctor_by"
    ).prefetch_related("items")

    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(test_id__icontains=search)
            | Q(voucher_number__icontains=search)
            | Q(mobile__icontains=search)
        )

    paginator = Paginator(qs, page_size)
    page_obj  = paginator.get_page(page_num)

    results = []
    for rec in page_obj.object_list:
        items       = rec.items.all()
        items_count = items.count()
        total_price = sum(
            (item.test_amount or 0) for item in items
        )

        results.append({
            "id":                    rec.id,
            "test_id":               rec.test_id,
            "test_date":             str(rec.test_date) if rec.test_date else None,
            "patient_type":          rec.patient_type,
            "admitted_patient_id":   rec.admitted_patient.patient_id if rec.admitted_patient else None,
            "admitted_patient_name": rec.admitted_patient.name       if rec.admitted_patient else None,
            "name":                  rec.name,
            "age":                   rec.age,
            "blood_group":           rec.blood_group,
            "mobile":                rec.mobile,
            "test_doctor_by_id":     rec.test_doctor_by.id          if rec.test_doctor_by else None,
            "test_doctor_by_name":   rec.test_doctor_by.doctor_name if rec.test_doctor_by else None,
            "provided_discount":     rec.provided_discount,
            # "total_test_amount":     total_price,
            "total_test_amount":     rec.total_test_amount,
            "voucher_number":        rec.voucher_number,
            "created_at":            rec.created_at.isoformat() if rec.created_at else None,
            "created_by":            rec.created_by,
            "updated_by":            rec.updated_by,
            "items_count":           items_count,
        })

    return JsonResponse({
        "count":   paginator.count,
        "pages":   paginator.num_pages,
        "results": results,
    })


@api_view(["PATCH", "DELETE"])
@permission_classes([AllowAny])
def test_record_detail(request, pk):
    """
    PATCH  /api/test-records/<pk>/  — update TestsRecord fields only
    DELETE /api/test-records/<pk>/  — delete record + cascade items
    """
    try:
        record = TestsRecord.objects.get(pk=pk)
    except TestsRecord.DoesNotExist:
        return JsonResponse({"error": "Record not found."}, status=404)

    # ── DELETE ──────────────────────────────────────────────────────
    if request.method == "DELETE":
        test_id = record.test_id
        record.delete()
        return JsonResponse({"success": True, "deleted_test_id": test_id})

    # ── PATCH ───────────────────────────────────────────────────────
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    # Scalar fields — update only what's present in the payload
    scalar_fields = [
        "test_date", "patient_type", "name",
        "age", "blood_group", "mobile",
        "provided_discount", "updated_by",
    ]
    for field in scalar_fields:
        if field in data:
            setattr(record, field, data[field])

    # FK: test_doctor_by
    if "test_doctor_by" in data:
        doctor_id = data["test_doctor_by"]
        if doctor_id is None:
            record.test_doctor_by = None
        else:
            try:
                record.test_doctor_by = DoctorDetails.objects.get(pk=doctor_id)
            except DoctorDetails.DoesNotExist:
                return JsonResponse({"error": f"Doctor {doctor_id} not found."}, status=400)

    # Recalculate total from items if discount changed
    if "provided_discount" in data:
        items      = record.items.all()
        subtotal   = sum((item.test_amount or 0) for item in items)
        discount   = record.provided_discount or 0
        disc_amt   = round(subtotal * discount / 100)
        record.total_test_amount = subtotal - disc_amt

    record.save()

    return JsonResponse({
        "success": True,
        "id":      record.id,
        "test_id": record.test_id,
        "total_test_amount": record.total_test_amount,
    })



# ─────────────────────────────────────────────
#  Entry Admit Patient (API endpoint for admitting a patient)
# ─────────────────────────────────────────────
@api_view(["POST"])
@permission_classes([AllowAny])
def entry_admit_patient(request):
    data = request.data
    try:
        # Helper function to safely get string values
        def get_string_value(value):
            if value is None:
                return ""
            return str(value).strip()
        
        # Validate required fields
        required_fields = ['name', 'age', 'sex', 'phone']
        for field in required_fields:
            if not data.get(field):
                return Response(
                    {
                        "message": f"{field} is required",
                        "success": False
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        
        # Validate age
        try:
            age = int(data.get("age", 0))
            if age < 0 or age > 150:
                raise ValueError("Invalid age")
        except (ValueError, TypeError):
            return Response(
                {
                    "message": "Valid age is required (0-150)",
                    "success": False
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Safely get and strip all string fields
        patient = AdmitPatient.objects.create(
            name=get_string_value(data.get("name")),
            age=age,
            gender=get_string_value(data.get("sex")),
            blood_group=get_string_value(data.get("bloodType")),
            email=get_string_value(data.get("email")) or None,
            contact_number=get_string_value(data.get("phone")),
            address=get_string_value(data.get("address")) or None,
            emergency_contact=get_string_value(data.get("emergencyContact")) or None,
            cause_of_admission=get_string_value(data.get("causeOfAdmission")) or None,
            admit_doctor_by_id=get_string_value(data.get("admitDoctorBy")) or None,
            cabin_ward_no_id=get_string_value(data.get("cabinWardNo")) or None,
            important_notes=get_string_value(data.get("importantNotes")) or None,
            created_by=get_string_value(data.get("createdBy")) or None,
        )

        cabin_ward = patient.cabin_ward_no
        if cabin_ward:
            cabin_ward.is_available = False
            cabin_ward.save()

        return Response(
            {
                "message": "Patient admitted successfully.",
                "patient_id": patient.patient_id,
                "success": True
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        logger.error("Error admitting patient: %s", e)
        return Response(
            {
                "message": f"An error occurred while admitting the patient: {str(e)}",
                "success": False
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

# ─────────────────────────────────────────────
#  View Admit Patients (API endpoint for retrieving all admitted patients)
# ─────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def view_admit_patient(request):
    try:
        patients = AdmitPatient.objects.all().order_by("-created_at")
        patient_list = []
        for patient in patients:
            patient_list.append({
                "patient_id": patient.patient_id,
                "name": patient.name,
                "age": patient.age,
                "gender": patient.gender,
                "blood_group": patient.blood_group,
                "email": patient.email,
                "contact_number": patient.contact_number,  
                "address": patient.address,
                "emergency_contact": patient.emergency_contact,
                "cause_of_admission": patient.cause_of_admission,
                "admit_doctor_by_id": patient.admit_doctor_by.id if patient.admit_doctor_by else None,
                "admit_doctor_by": patient.admit_doctor_by.doctor_name if patient.admit_doctor_by else None,
                "cabin_ward_no_id": patient.cabin_ward_no.id if patient.cabin_ward_no else None,
                "cabin_ward_no": patient.cabin_ward_no.cabin_ward_no if patient.cabin_ward_no else None,
                "important_notes": patient.important_notes,
                "created_at": patient.created_at,
            })
        return Response(
            {
                "message": "Patients retrieved successfully.",
                "patients": patient_list,
                "success": True
            },
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error("Error retrieving patients: %s", e)
        return Response(
            {
                "message": f"An error occurred while retrieving patients: {str(e)}",
                "success": False
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    

# ─────────────────────────────────────────────
#  Edit Admit Patient (API endpoint for editing a patient's details)
# ─────────────────────────────────────────────
@api_view(["PUT"])
@permission_classes([AllowAny])
def edit_admit_patient(request, patient_id):
    try:
        patient = AdmitPatient.objects.get(patient_id=patient_id)
        data = request.data
        
        # Field mappings: (form_field_name, model_field_name, is_foreign_key)
        field_mappings = [
            ('name', 'name', False),
            ('gender', 'gender', False),
            ('blood_group', 'blood_group', False),
            ('contact_number', 'contact_number', False),
            ('cause_of_admission', 'cause_of_admission', False),
            ('important_notes', 'important_notes', False),
        ]
        
        # Update simple fields
        for form_field, model_field, is_fk in field_mappings:
            if form_field in data:
                value = data[form_field]
                if value and value != "":
                    setattr(patient, model_field, str(value).strip())
                else:
                    setattr(patient, model_field, None if model_field in ['email', 'address', 'emergency_contact'] else "")
        
        # Handle email separately (should be None if empty)
        if 'email' in data:
            patient.email = data['email'].strip() if data['email'] and data['email'].strip() else None
        
        # Handle address separately
        if 'address' in data:
            patient.address = data['address'].strip() if data['address'] and data['address'].strip() else None
        
        # Handle emergency_contact separately
        if 'emergency_contact' in data:
            patient.emergency_contact = data['emergency_contact'].strip() if data['emergency_contact'] and data['emergency_contact'].strip() else None
        
        # Handle age with validation
        if 'age' in data and data['age'] and data['age'] != "":
            try:
                age = int(data['age'])
                if not (0 <= age <= 150):
                    raise ValueError
                patient.age = age
            except (ValueError, TypeError):
                return Response({"message": "Valid age (0-150) is required", "success": False}, 
                              status=status.HTTP_400_BAD_REQUEST)
        
        # Handle foreign key: admit_doctor_by
        if 'admit_doctor_by' in data:
            doctor_id = data['admit_doctor_by']
            if doctor_id and doctor_id != "":
                try:
                    patient.admit_doctor_by = DoctorDetails.objects.get(id=int(doctor_id))
                except (ValueError, DoctorDetails.DoesNotExist):
                    return Response({"message": "Invalid doctor selected", "success": False}, 
                                  status=status.HTTP_400_BAD_REQUEST)
            else:
                patient.admit_doctor_by = None
        
        # Handle foreign key: cabin_ward_no
        if 'cabin_ward_no' in data:
            cabin_id = data['cabin_ward_no']
            if cabin_id and cabin_id != "":
                try:
                    patient.cabin_ward_no = CabinWardDetails.objects.get(id=int(cabin_id))
                except (ValueError, CabinWardDetails.DoesNotExist):
                    return Response({"message": "Invalid cabin/ward selected", "success": False}, 
                                  status=status.HTTP_400_BAD_REQUEST)
            else:
                patient.cabin_ward_no = None
        
        patient.save()
        
        return Response({
            "message": "Patient details updated successfully.",
            "success": True
        }, status=status.HTTP_200_OK)
        
    except AdmitPatient.DoesNotExist:
        return Response({
            "message": "Patient not found.",
            "success": False
        }, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────
#  Discharge Patient (API endpoint for discharging a patient)
# ─────────────────────────────────────────────

# ─── Helper: no decorators ───────────────────────────────────────

def calculate_admit_duration(created_at):
    now = timezone.localtime(timezone.now())
    admit = timezone.localtime(created_at)

    days = 0
    cursor = admit.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    while cursor < today_start:
        cursor += timedelta(days=1)  # ← was timezone.timedelta
        days += 1

    if now.hour >= 12:
        days += 1

    total_hours = int((now - admit).total_seconds() // 3600)
    rem_hours = total_hours % 24

    if days <= 0:
        label = f"{rem_hours}h"
    elif rem_hours == 0:
        label = f"{days}d"
    else:
        label = f"{days}d {rem_hours}h"

    return days, total_hours, label


def calculate_admit_charge(patient, days):
    """Total charge = per-day final_charge × billable days (min 1)."""
    billable_days = max(days, 1)
    per_day = 0
    if patient.cabin_ward_no and patient.cabin_ward_no.final_charge:
        per_day = patient.cabin_ward_no.final_charge
    return per_day * billable_days, per_day


@api_view(["GET"])
@permission_classes([AllowAny])
def admitted_list_for_discharged(request):
    patients = AdmitPatient.objects.select_related(
        'admit_doctor_by', 'cabin_ward_no'
    ).order_by('-created_at')

    result = []
    for p in patients:
        days, total_hours, dur_label = calculate_admit_duration(p.created_at)
        total_charge, per_day_charge = calculate_admit_charge(p, days)

        result.append({
            'patient_id': p.patient_id,
            'name': p.name,
            'age': p.age,
            'gender': p.gender,
            'blood_group': p.blood_group,
            'email': p.email,
            'contact_number': p.contact_number,
            'address': p.address,
            'emergency_contact': p.emergency_contact,
            'cause_of_admission': p.cause_of_admission,
            'admit_doctor_by_id': p.admit_doctor_by_id,
            'admit_doctor_by': (
                f"{p.admit_doctor_by.doctor_name} ({p.admit_doctor_by.specialization})"
                if p.admit_doctor_by and p.admit_doctor_by.specialization
                else (p.admit_doctor_by.doctor_name if p.admit_doctor_by else None)
            ),
            'cabin_ward_no_id': p.cabin_ward_no_id,
            'cabin_ward_no': p.cabin_ward_no.cabin_ward_no if p.cabin_ward_no else None,
            'per_day_charge': per_day_charge,
            'total_charge': total_charge,
            'admit_duration_label': dur_label,
            'admit_duration_days': days,
            'admit_duration_hours': total_hours,
            'important_notes': p.important_notes,
            'admit_status': 'admitted',
            'created_at': p.created_at.isoformat() if p.created_at else None,
        })

    return JsonResponse({'success': True, 'patients': result})


@api_view(["GET"])
@permission_classes([AllowAny])
def pdf_discharge_summary(request, patient_id):
    """Returns discharge summary for PDF generation."""
    try:
        p = AdmitPatient.objects.select_related(
            'admit_doctor_by', 'cabin_ward_no'
        ).get(patient_id=patient_id)
    except AdmitPatient.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Patient not found'}, status=404)

    days, total_hours, dur_label = calculate_admit_duration(p.created_at)
    total_charge, per_day_charge = calculate_admit_charge(p, days)

    return JsonResponse({
        'success': True,
        'summary': {
            'patient_id':           p.patient_id,
            'name':                 p.name,
            'email':                p.email,
            'contact_number':       p.contact_number,
            'address':              p.address,
            'emergency_contact':    p.emergency_contact,
            'admit_doctor_by': (
                f"{p.admit_doctor_by.doctor_name} ({p.admit_doctor_by.specialization})"
                if p.admit_doctor_by and p.admit_doctor_by.specialization
                else (p.admit_doctor_by.doctor_name if p.admit_doctor_by else '—')
            ),
            'cabin_ward_no':        p.cabin_ward_no.cabin_ward_no if p.cabin_ward_no else '—',
            'per_day_charge':       per_day_charge,
            'total_charge':         total_charge,
            'admit_duration_label': dur_label,
            'admit_duration_days':  days,
            'important_notes':      p.important_notes,
            'admit_date':           p.created_at.isoformat() if p.created_at else None,
            'discharge_date':       timezone.now().isoformat(),
        }
    })



@api_view(["POST"])
@permission_classes([AllowAny])
def discharge_patient(request, patient_id):
    try:
        p = AdmitPatient.objects.select_related(
            'admit_doctor_by', 'cabin_ward_no'
        ).get(patient_id=patient_id)
    except AdmitPatient.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Patient not found'}, status=404)

    doctor_label = ''
    if p.admit_doctor_by:
        doc = p.admit_doctor_by
        doctor_label = (
            f"{doc.doctor_name} ({doc.specialization})"
            if doc.specialization else doc.doctor_name
        )

    cabin_label = p.cabin_ward_no.cabin_ward_no if p.cabin_ward_no else ''

    valid_statuses = {'Paid', 'Partial Paid', 'Due'}
    discharge_status = request.data.get('discharge_status', 'Undefined')
    if discharge_status not in valid_statuses:
        discharge_status = 'Undefined'

    provided_discount = request.data.get('provided_discount', 0)
    total_discharge_amount = request.data.get('total_discharge_amount', None)
    account_head_id = request.data.get('account_head_id', None)

    # Create voucher entry
    voucher = None
    if total_discharge_amount is not None:
        try:
            account_head = None
            if account_head_id:
                account_head = AccountHead.objects.get(id=account_head_id)
            voucher = VoucherDetails.objects.create(
                account_head=account_head,
                amount=total_discharge_amount,
                transaction_type='credit',
                account_head_type = 'income',
                comments=f"Discharge payment for patient {patient_id}",
            )
        except Exception:
            pass  # voucher creation failure is non-blocking

    discharge = DischargedRecord.objects.create(
        patient_id=p.patient_id,
        name=p.name,
        age=p.age,
        gender=p.gender,
        blood_group=p.blood_group,
        email=p.email,
        contact_number=p.contact_number,
        address=p.address,
        emergency_contact=p.emergency_contact,
        cause_of_admission=p.cause_of_admission,
        admit_doctor_by=doctor_label,
        cabin_ward_no=cabin_label,
        important_notes=p.important_notes,
        admit_date=p.created_at,
        discharge_date=timezone.now(),
        discharge_by=request.data.get('discharge_by', 'Unknown'),
        discharge_status=discharge_status,
        discharge_due_note=request.data.get('discharge_due_note', ''),
        provided_discount=provided_discount,
        total_discharge_amount=total_discharge_amount,
        voucher_number=voucher.voucher_number,
    )

    if p.cabin_ward_no:
        cabin = p.cabin_ward_no
        cabin.is_available = True
        cabin.save()

    patient_name = p.name
    patient_id_val = p.patient_id
    p.delete()

    return JsonResponse({
        'success': True,
        'message': f'{patient_name} discharged successfully.',
        'patient_id': patient_id_val,
        'discharge_date': discharge.discharge_date.isoformat(),
        'discharge_status': discharge.discharge_status,
        'voucher_number': voucher.voucher_number if voucher else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET  /api/discharged-records/
#   Returns all discharged patient records, newest discharge first.
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([AllowAny])
def get_discharged_records(request):
    try:
        records = DischargedRecord.objects.all().order_by("-discharge_date")

        data = []
        for r in records:
            data.append({
                "id":                  r.id,
                "patient_id":          r.patient_id,
                "name":                r.name,
                "age":                 r.age,
                "gender":              r.gender,
                "blood_group":         r.blood_group,
                "email":               r.email,
                "contact_number":      r.contact_number,
                "address":             r.address,
                "emergency_contact":   r.emergency_contact,
                "cause_of_admission":  r.cause_of_admission,
                "admit_doctor_by":     r.admit_doctor_by,
                "cabin_ward_no":       r.cabin_ward_no,
                "important_notes":     r.important_notes,
                "voucher_number":      r.voucher_number,
                # ISO strings so JS can parse them properly
                "discharge_date":      r.discharge_date.isoformat() if r.discharge_date else None,
                "discharge_by":        r.discharge_by,
                "discharge_status":    r.discharge_status,
                "discharge_due_note":  r.discharge_due_note,
                "admit_date":          r.admit_date.isoformat() if r.admit_date else None,
            })

        return JsonResponse({"success": True, "records": data}, status=200)

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET  /api/discharged-records/<patient_id>/
#   Returns a single discharge record by patient_id.
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([AllowAny])
def get_discharged_record_detail(request, patient_id):
    try:
        r = DischargedRecord.objects.get(patient_id=patient_id)

        data = {
            "id":                  r.id,
            "patient_id":          r.patient_id,
            "name":                r.name,
            "age":                 r.age,
            "gender":              r.gender,
            "blood_group":         r.blood_group,
            "email":               r.email,
            "contact_number":      r.contact_number,
            "address":             r.address,
            "emergency_contact":   r.emergency_contact,
            "cause_of_admission":  r.cause_of_admission,
            "admit_doctor_by":     r.admit_doctor_by,
            "cabin_ward_no":       r.cabin_ward_no,
            "important_notes":     r.important_notes,
            "discharge_date":      r.discharge_date.isoformat() if r.discharge_date else None,
            "discharge_by":        r.discharge_by,
            "discharge_status":    r.discharge_status,
            "discharge_due_note":  r.discharge_due_note,
            "admit_date":          r.admit_date.isoformat() if r.admit_date else None,
        }

        return JsonResponse({"success": True, "record": data}, status=200)

    except DischargedRecord.DoesNotExist:
        return JsonResponse({"success": False, "message": "Record not found"}, status=404)
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# PATCH  /api/update-discharge-payment/<patient_id>/
#   Updates only the payment-related fields:
#     - discharge_status   ("Paid" | "Due" | "Partial Paid")
#     - discharge_due_note (free-text note)
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["PATCH"])
@permission_classes([AllowAny])
def update_discharge_payment(request, patient_id):
    try:
        record = DischargedRecord.objects.get(patient_id=patient_id)
    except DischargedRecord.DoesNotExist:
        return JsonResponse({"success": False, "message": "Record not found"}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON body"}, status=400)

    # Validate discharge_status if provided
    allowed_statuses = {"Paid", "Due", "Partial Paid"}
    new_status = body.get("discharge_status", "").strip()

    if new_status and new_status not in allowed_statuses:
        return JsonResponse(
            {
                "success": False,
                "message": f"Invalid status '{new_status}'. Must be one of: {', '.join(allowed_statuses)}",
            },
            status=400,
        )

    try:
        if new_status:
            record.discharge_status = new_status

        # Always update the due note (can be cleared to empty string)
        if "discharge_due_note" in body:
            record.discharge_due_note = body["discharge_due_note"]

        record.save(update_fields=["discharge_status", "discharge_due_note"])

        return JsonResponse(
            {
                "success": True,
                "message": "Payment status updated successfully",
                "patient_id": record.patient_id,
                "discharge_status": record.discharge_status,
                "discharge_due_note": record.discharge_due_note,
            },
            status=200,
        )

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET  /api/discharged-records/stats/
#   Returns a summary count grouped by discharge_status.
#   Useful if you want server-side stats without fetching all records.
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([AllowAny])
def get_discharge_stats(request):
    try:
        from django.db.models import Count

        stats_qs = (
            DischargedRecord.objects
            .values("discharge_status")
            .annotate(count=Count("id"))
        )

        stats = {item["discharge_status"] or "Unknown": item["count"] for item in stats_qs}

        return JsonResponse(
            {
                "success": True,
                "total":        DischargedRecord.objects.count(),
                "paid":         stats.get("Paid", 0),
                "due":          stats.get("Due", 0),
                "partial_paid": stats.get("Partial Paid", 0),
                "breakdown":    stats,
            },
            status=200,
        )

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)
    



# ─── Helper ───────────────────────────────────────────────────────────────────
 
def cabin_to_dict(cabin: CabinWardDetails) -> dict:
    return {
        "id":                cabin.id,
        "cabin_ward_no":     cabin.cabin_ward_no,
        "cabin_ward_charge": cabin.cabin_ward_charge,
        "service_charge":    cabin.service_charge,
        "discount":          cabin.discount,
        "final_charge":      cabin.final_charge,
        "is_available":      cabin.is_available,
        "comments":          cabin.comments or "",
    }
 
 
# ─── List + Create ────────────────────────────────────────────────────────────
 
@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def cabin_ward_list(request):
    """
    GET  /api/cabin-ward/          → list all cabins/wards
    POST /api/cabin-ward/          → create a new cabin/ward
    """
    if request.method == "GET":
        qs = CabinWardDetails.objects.all().order_by("cabin_ward_no")
 
        # Optional query filters
        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(cabin_ward_no__icontains=search)
 
        availability = request.GET.get("is_available", "")
        if availability in ("true", "false"):
            qs = qs.filter(is_available=(availability == "true"))
 
        data = [cabin_to_dict(c) for c in qs]
        return JsonResponse({"results": data, "count": len(data)}, status=200)
 
    # POST – create
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
 
    cabin_ward_no = payload.get("cabin_ward_no", "").strip()
    if not cabin_ward_no:
        return JsonResponse({"error": "cabin_ward_no is required."}, status=400)
 
    cabin = CabinWardDetails(
        cabin_ward_no=cabin_ward_no,
        cabin_ward_charge=payload.get("cabin_ward_charge"),
        service_charge=payload.get("service_charge"),
        discount=payload.get("discount"),
        is_available=payload.get("is_available", True),
        comments=payload.get("comments", ""),
    )
    cabin.save()  # model.save() auto-calculates final_charge
    return JsonResponse({"message": "Created successfully.", "data": cabin_to_dict(cabin)}, status=201)
 
 
# ─── Retrieve + Update + Delete ───────────────────────────────────────────────
 
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([AllowAny])
def cabin_ward_detail(request, pk: int):
    """
    GET    /api/cabin-ward/<id>/   → retrieve single record
    PUT    /api/cabin-ward/<id>/   → full update
    PATCH  /api/cabin-ward/<id>/   → partial update
    DELETE /api/cabin-ward/<id>/   → delete
    """
    cabin = get_object_or_404(CabinWardDetails, pk=pk)
 
    if request.method == "GET":
        return JsonResponse(cabin_to_dict(cabin), status=200)
 
    if request.method == "DELETE":
        cabin.delete()
        return JsonResponse({"message": "Deleted successfully."}, status=200)
 
    # PUT / PATCH
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)
 
    is_partial = (request.method == "PATCH")
 
    if not is_partial or "cabin_ward_no" in payload:
        val = payload.get("cabin_ward_no", "").strip()
        if not val:
            return JsonResponse({"error": "cabin_ward_no cannot be empty."}, status=400)
        cabin.cabin_ward_no = val
 
    if not is_partial or "cabin_ward_charge" in payload:
        cabin.cabin_ward_charge = payload.get("cabin_ward_charge", cabin.cabin_ward_charge)
    if not is_partial or "service_charge" in payload:
        cabin.service_charge = payload.get("service_charge", cabin.service_charge)
    if not is_partial or "discount" in payload:
        cabin.discount = payload.get("discount", cabin.discount)
    if not is_partial or "is_available" in payload:
        cabin.is_available = payload.get("is_available", cabin.is_available)
    if not is_partial or "comments" in payload:
        cabin.comments = payload.get("comments", cabin.comments)
 
    cabin.save()  # recalculates final_charge
    return JsonResponse({"message": "Updated successfully.", "data": cabin_to_dict(cabin)}, status=200)
 


# ─── Test Group ──────────────────────────────────────────────────────────────
 
@api_view(["GET"])
@permission_classes([AllowAny])
def test_groups_list(request):
    """
    GET  /api/test-groups-list/   – list all groups (supports ?search=)
    POST /api/test-groups-list/   – create a new group
    """
    if request.method == "GET":
        qs = TestGroup.objects.all().order_by("id")
 
        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(group_name__icontains=search)
 
        serializer = TestGroupSerializer(qs, many=True)
        return Response({'results': serializer.data}, status=status.HTTP_200_OK)
 
    return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)   

 
# ─── Test Details ─────────────────────────────────────────────────────────────
 
class TestDetailsListCreateView(APIView):
    """
    GET  /api/test-details/   – list all tests (supports ?search= and ?group=)
    POST /api/test-details/   – create a new test
    """
    permission_classes = [AllowAny]
 
    def get(self, request):
        qs = TestDetails.objects.select_related('test_group').all().order_by('id')
 
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(test_name__icontains=search)
 
        group_id = request.query_params.get('group', '').strip()
        if group_id:
            qs = qs.filter(test_group_id=group_id)
 
        serializer = TestDetailsSerializer(qs, many=True)
        return Response({'results': serializer.data}, status=status.HTTP_200_OK)
 
    def post(self, request):
        serializer = TestDetailsSerializer(data=request.data)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
 
 
class TestDetailsDetailView(APIView):
    """
    GET    /api/test-details/<id>/  – retrieve a test
    PUT    /api/test-details/<id>/  – full update
    PATCH  /api/test-details/<id>/  – partial update
    DELETE /api/test-details/<id>/  – delete a test
    """
    permission_classes = [AllowAny]
 
    def get_object(self, pk):
        return get_object_or_404(TestDetails, pk=pk)
 
    def get(self, request, pk):
        serializer = TestDetailsSerializer(self.get_object(pk))
        return Response(serializer.data)
 
    def put(self, request, pk):
        serializer = TestDetailsSerializer(self.get_object(pk), data=request.data, partial=False)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
 
    def patch(self, request, pk):
        serializer = TestDetailsSerializer(self.get_object(pk), data=request.data, partial=True)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
 
    def delete(self, request, pk):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)





# ─────────────────────────────────────────────────────────────────────────────
# Admit Patient List PDF Generation
# ─────────────────────────────────────────────────────────────────────────────
@api_view(["POST"])
@permission_classes([AllowAny])
def generate_admit_patient_pdf(request):
    """
    Generate PDF report for admit patient list — full-width table + Bangla font support
    """
    try:
        # ── Register Bangla-capable font ──────────────────────────────────────
        # Place NotoSansBengali-Regular.ttf & NotoSansBengali-Bold.ttf
        # somewhere accessible, e.g. BASE_DIR/fonts/
        import os
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        font_dir  = os.path.join(BASE_DIR, 'fonts')

        REGULAR_FONT = 'NotoSansBengali'
        BOLD_FONT    = 'NotoSansBengali-Bold'

        try:
            pdfmetrics.registerFont(TTFont(REGULAR_FONT, os.path.join(font_dir, 'NotoSansBengali-Regular.ttf')))
            pdfmetrics.registerFont(TTFont(BOLD_FONT,    os.path.join(font_dir, 'NotoSansBengali-Bold.ttf')))
        except Exception as font_err:
            # Graceful fallback to Helvetica if font files are missing
            print(f"Font registration warning: {font_err}")
            REGULAR_FONT = 'Helvetica'
            BOLD_FONT    = 'Helvetica-Bold'

        # ── Parse request ─────────────────────────────────────────────────────
        data             = json.loads(request.body)
        patients_data    = data.get('patients', [])
        search_criteria  = data.get('searchCriteria', {})
        total_count      = data.get('totalCount', 0)

        # ── Page setup ───────────────────────────────────────────────────────
        buffer = BytesIO()

        LEFT_MARGIN  = 30
        RIGHT_MARGIN = 30
        TOP_MARGIN   = 50
        BOT_MARGIN   = 40

        PAGE_W, PAGE_H = landscape(A4)          # 841.89 x 595.27 pt
        USABLE_W = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN   # ≈ 781.89 pt

        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=RIGHT_MARGIN,
            leftMargin=LEFT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOT_MARGIN,
        )

        styles = getSampleStyleSheet()

        # ── Paragraph styles (Bangla-aware) ──────────────────────────────────
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Normal'],
            fontSize=22,
            textColor=colors.HexColor('#0f172a'),
            alignment=TA_CENTER,
            spaceAfter=6,
            fontName=BOLD_FONT,
        )
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=13,
            textColor=colors.HexColor('#475569'),
            alignment=TA_CENTER,
            spaceAfter=3,
            fontName=REGULAR_FONT,
        )
        date_style = ParagraphStyle(
            'DateStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#64748b'),
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName=REGULAR_FONT,
        )
        criteria_style = ParagraphStyle(
            'CriteriaStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#475569'),
            alignment=TA_LEFT,
            spaceAfter=15,
            leading=14,
            fontName=REGULAR_FONT,
        )
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=7,
            textColor=colors.HexColor('#94a3b8'),
            alignment=TA_CENTER,
            fontName=REGULAR_FONT,
        )

        # ── Story ─────────────────────────────────────────────────────────────
        story = []

        story.append(Paragraph("HOSPITAL MANAGEMENT SYSTEM", title_style))
        story.append(Paragraph("Admit Patient List Report", subtitle_style))
        story.append(Paragraph(
            f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            date_style,
        ))

        search_field_display = search_criteria.get('field', 'N/A').replace('_', ' ').title()
        search_term_display  = search_criteria.get('term', 'All') or 'All'

        criteria_text = (
            f"<b>Search Criteria:</b><br/>"
            f"<font color='#64748b'>Field:</font> {search_field_display}<br/>"
            f"<font color='#64748b'>Value:</font> {search_term_display}<br/>"
            f"<font color='#64748b'>Total Records:</font> {total_count}"
        )
        story.append(Paragraph(criteria_text, criteria_style))
        story.append(Spacer(1, 5))

        # ── Table headers ─────────────────────────────────────────────────────
        headers = [
            'S.No',
            'Patient ID',
            'Patient Name',
            'Admit Date',
            'Admit Time',
            'Cabin / Ward No',
            'Doctor Name',
        ]
        table_data = [headers]

        # Cell style for Bangla text inside table cells
        cell_para_style = ParagraphStyle(
            'CellPara',
            parent=styles['Normal'],
            fontSize=8,
            fontName=REGULAR_FONT,
            leading=11,
            wordWrap='CJK',   # enables proper wrapping for non-Latin scripts
        )
        cell_center_style = ParagraphStyle(
            'CellCenter',
            parent=cell_para_style,
            alignment=TA_CENTER,
        )

        # ── Rows ──────────────────────────────────────────────────────────────
        for idx, patient in enumerate(patients_data, start=1):
            admit_datetime = patient.get('created_at', '')
            admit_date = 'N/A'
            admit_time = 'N/A'
            if admit_datetime:
                try:
                    dt_obj     = datetime.fromisoformat(admit_datetime.replace('Z', '+00:00'))
                    admit_date = dt_obj.strftime('%d-%b-%Y')
                    admit_time = dt_obj.strftime('%I:%M %p').lstrip('0')
                except Exception:
                    pass

            serial_no   = patient.get('serial_no', idx)
            patient_id  = patient.get('patient_id', 'N/A') or 'N/A'
            name        = patient.get('name', 'N/A') or 'N/A'
            cabin_ward  = patient.get('cabin_ward_no', 'N/A') or 'N/A'
            doctor_name = (
                patient.get('admit_doctor_by_name')
                or patient.get('admit_doctor_by')
                or 'N/A'
            )

            # Wrap text in Paragraph so Bangla renders and long strings wrap
            table_data.append([
                Paragraph(str(serial_no),   cell_center_style),
                Paragraph(str(patient_id),  cell_center_style),
                Paragraph(str(name),        cell_para_style),
                Paragraph(str(admit_date),  cell_center_style),
                Paragraph(str(admit_time),  cell_center_style),
                Paragraph(str(cabin_ward),  cell_center_style),
                Paragraph(str(doctor_name), cell_para_style),
            ])

        # ── Full-width column widths (must sum to USABLE_W) ───────────────────
        # Proportions:  S.No  ID    Name   Date   Time  Cabin  Doctor
        proportions  = [0.05, 0.10, 0.20,  0.12,  0.10, 0.13,  0.30]
        col_widths   = [round(p * USABLE_W, 2) for p in proportions]
        # Fix any floating-point drift so sum == USABLE_W exactly
        col_widths[-1] += USABLE_W - sum(col_widths)

        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        table.setStyle(TableStyle([
            # ── Header row ──
            ('BACKGROUND',    (0, 0), (-1, 0),  colors.HexColor('#2563eb')),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
            ('ALIGN',         (0, 0), (-1, 0),  'CENTER'),
            ('VALIGN',        (0, 0), (-1, 0),  'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1, 0),  BOLD_FONT),
            ('FONTSIZE',      (0, 0), (-1, 0),  9),
            ('TOPPADDING',    (0, 0), (-1, 0),  8),
            ('BOTTOMPADDING', (0, 0), (-1, 0),  8),

            # ── Body ──
            ('FONTNAME',      (0, 1), (-1, -1), REGULAR_FONT),
            ('FONTSIZE',      (0, 1), (-1, -1), 8),
            ('VALIGN',        (0, 1), (-1, -1), 'MIDDLE'),

            # ── Alternating row colours ──
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f0f7ff')]),

            # ── Borders ──
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('BOX',  (0, 0), (-1, -1), 0.8, colors.HexColor('#2563eb')),

            # ── Padding ──
            ('TOPPADDING',    (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ]))

        story.append(table)
        story.append(Spacer(1, 20))
        story.append(Paragraph(
            f"* This is a system-generated report  •  Hospital Management System © {datetime.now().year}",
            footer_style,
        ))

        doc.build(story)

        pdf_data = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf_data, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="admit_patients_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        )
        return response

    except Exception as e:
        import traceback
        print(f"PDF Generation Error: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'message': f'PDF generation failed: {str(e)}'
        }, status=500)      
    



# ─────────────────────────────────────────────────────────────────────────────
# Colour palette (matches the frontend blue/teal theme)
# ─────────────────────────────────────────────────────────────────────────────
BRAND_DARK   = colors.HexColor('#0f172a')   # slate-900
BRAND_BLUE   = colors.HexColor('#1d4ed8')   # blue-700
BRAND_CYAN   = colors.HexColor('#0ea5e9')   # sky-500
HEADER_BG    = colors.HexColor('#1e3a5f')   # deep navy header
ACCENT_LIGHT = colors.HexColor('#eff6ff')   # blue-50 row alt
COL_HEAD_BG  = colors.HexColor('#1d4ed8')   # blue header row
COL_HEAD_FG  = colors.white
ROW_ALT      = colors.HexColor('#f0f7ff')   # subtle alternating row
ROW_PAID     = colors.HexColor('#ecfdf5')   # green tint
ROW_DUE      = colors.HexColor('#fef2f2')   # red tint
ROW_PARTIAL  = colors.HexColor('#fffbeb')   # amber tint
BORDER_COLOR = colors.HexColor('#e2e8f0')
MUTED_TEXT   = colors.HexColor('#64748b')
FOOTER_BG    = colors.HexColor('#f8fafc')
FOOTER_LINE  = colors.HexColor('#cbd5e1')

PAGE_W, PAGE_H = A4
MARGIN_LEFT  = 18 * mm
MARGIN_RIGHT = 18 * mm
MARGIN_TOP   = 22 * mm
MARGIN_BOT   = 20 * mm


# ─────────────────────────────────────────────────────────────────────────────
# Helper: format ISO datetime strings
# ─────────────────────────────────────────────────────────────────────────────
def _fmt_date(iso_str):
    if not iso_str:
        return '—'
    try:
        if isinstance(iso_str, str):
            # strip timezone offset for parsing
            iso_clean = iso_str[:19]
            dt = datetime.strptime(iso_clean, '%Y-%m-%dT%H:%M:%S')
        else:
            dt = iso_str  # already a datetime object
        return dt.strftime('%d %b %Y')
    except Exception:
        return str(iso_str)[:10] if iso_str else '—'


def _fmt_time(iso_str):
    if not iso_str:
        return '—'
    try:
        if isinstance(iso_str, str):
            iso_clean = iso_str[:19]
            dt = datetime.strptime(iso_clean, '%Y-%m-%dT%H:%M:%S')
        else:
            dt = iso_str
        return dt.strftime('%H:%M')
    except Exception:
        return '—'


def _fmt_date_from_model(dt_field):
    """Handle both string and datetime/date objects from Django model fields."""
    if dt_field is None:
        return '—', '—'
    if isinstance(dt_field, str):
        return _fmt_date(dt_field), _fmt_time(dt_field)
    # It's a datetime/date object
    try:
        return dt_field.strftime('%d %b %Y'), dt_field.strftime('%H:%M')
    except Exception:
        return str(dt_field), '—'


# ─────────────────────────────────────────────────────────────────────────────
# Canvas-level header & footer drawn on every page
# ─────────────────────────────────────────────────────────────────────────────
class _HeaderFooterCanvas(pdfgen_canvas.Canvas):
    """
    Wraps the PDF canvas to paint a branded header and footer on every page.
    Usage is transparent — pass as canvasmaker to SimpleDocTemplate.build().
    """

    def __init__(self, *args, report_title='Discharge Patient Report',
                 hospital_name='HealthCare Management System',
                 generated_at=None, total_records=0, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.report_title   = report_title
        self.hospital_name  = hospital_name
        self.generated_at   = generated_at or datetime.now().strftime('%d %b %Y, %H:%M')
        self.total_records  = total_records

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header()
            self._draw_footer(self._pageNumber, num_pages)
            super().showPage()
        super().save()

    # ── Header ──
    def _draw_header(self):
        w, h = PAGE_W, PAGE_H

        # Full-width gradient-like dark band
        self.setFillColor(HEADER_BG)
        self.rect(0, h - 48 * mm, w, 48 * mm, fill=1, stroke=0)

        # Decorative right accent stripe
        self.setFillColor(BRAND_CYAN)
        self.rect(w - 6 * mm, h - 48 * mm, 6 * mm, 48 * mm, fill=1, stroke=0)

        # Hospital name (top line)
        self.setFillColor(colors.HexColor('#94a3b8'))
        self.setFont('Helvetica', 7.5)
        self.drawString(MARGIN_LEFT, h - 9 * mm, self.hospital_name.upper())

        # Report title (large)
        self.setFillColor(colors.white)
        self.setFont('Helvetica-Bold', 18)
        self.drawString(MARGIN_LEFT, h - 20 * mm, self.report_title)

        # Subtitle / generated timestamp
        self.setFillColor(colors.HexColor('#7dd3fc'))
        self.setFont('Helvetica', 7.5)
        self.drawString(MARGIN_LEFT, h - 27 * mm, f'Generated on  {self.generated_at}')

        # Records count badge (right side)
        badge_x = w - 52 * mm
        badge_y = h - 26 * mm
        self.setFillColor(BRAND_BLUE)
        self.roundRect(badge_x, badge_y, 36 * mm, 10 * mm, 3 * mm, fill=1, stroke=0)
        self.setFillColor(colors.white)
        self.setFont('Helvetica-Bold', 8)
        self.drawCentredString(badge_x + 18 * mm, badge_y + 3.2 * mm,
                               f'{self.total_records} Records')

        # Bottom border line under header
        self.setStrokeColor(BRAND_CYAN)
        self.setLineWidth(1.5)
        self.line(0, h - 48 * mm, w, h - 48 * mm)

    # ── Footer ──
    def _draw_footer(self, page_num, total_pages):
        w = PAGE_W
        y = 12 * mm

        # Footer line
        self.setStrokeColor(FOOTER_LINE)
        self.setLineWidth(0.5)
        self.line(MARGIN_LEFT, y + 5 * mm, w - MARGIN_RIGHT, y + 5 * mm)

        # Left: system name
        self.setFillColor(MUTED_TEXT)
        self.setFont('Helvetica', 7)
        self.drawString(MARGIN_LEFT, y + 1.5 * mm, 'This report was automatically generated by System on ' + datetime.now().strftime('%d %b %Y, %H:%M'))

        # Right: page number
        self.setFont('Helvetica-Bold', 7)
        page_text = f'Page {page_num} of {total_pages}'
        self.drawRightString(w - MARGIN_RIGHT, y + 1.5 * mm, page_text)


# ─────────────────────────────────────────────────────────────────────────────
# PDF builder function
# ─────────────────────────────────────────────────────────────────────────────
def generate_discharge_patient_pdf(queryset_data: list, filters_applied: dict) -> bytes:
    """
    Build a professional PDF from a list of discharge record dicts.

    Each record dict must contain:
        patient_id, name, discharge_date (ISO str or datetime),
        contact_number, discharge_due_note, discharge_status
    """
    buffer = io.BytesIO()

    generated_at   = datetime.now().strftime('%d %b %Y, %H:%M')
    total_records  = len(queryset_data)

    # Status summary
    paid_count    = sum(1 for r in queryset_data if r.get('discharge_status') == 'Paid')
    due_count     = sum(1 for r in queryset_data if r.get('discharge_status') == 'Due')
    partial_count = sum(1 for r in queryset_data if r.get('discharge_status') == 'Partial Paid')

    # ── Document setup ──
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=52 * mm,    # room for header
        bottomMargin=MARGIN_BOT,
        title='Discharge Patient Report',
        author='HealthCare HMS',
    )

    styles  = getSampleStyleSheet()
    story   = []

    # ── Shared paragraph styles ──
    style_section_head = ParagraphStyle(
        'SectionHead',
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=BRAND_BLUE,
        spaceAfter=4,
        spaceBefore=8,
    )
    style_normal_small = ParagraphStyle(
        'NormalSmall',
        fontName='Helvetica',
        fontSize=7.5,
        textColor=BRAND_DARK,
        leading=10,
    )
    style_muted = ParagraphStyle(
        'Muted',
        fontName='Helvetica',
        fontSize=7,
        textColor=MUTED_TEXT,
        leading=9,
    )

    # ── Summary stats row ──
    summary_data = [
        [
            Paragraph('<b>Total Discharged</b>', style_normal_small),
            Paragraph('<b>Paid</b>', style_normal_small),
            Paragraph('<b>Due</b>', style_normal_small),
            Paragraph('<b>Partial Paid</b>', style_normal_small),
        ],
        [
            Paragraph(f'<font size=14><b>{total_records}</b></font>', style_normal_small),
            Paragraph(f'<font size=14 color="#059669"><b>{paid_count}</b></font>', style_normal_small),
            Paragraph(f'<font size=14 color="#dc2626"><b>{due_count}</b></font>', style_normal_small),
            Paragraph(f'<font size=14 color="#d97706"><b>{partial_count}</b></font>', style_normal_small),
        ],
    ]

    usable_w = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT
    col_w    = usable_w / 4

    summary_table = Table(summary_data, colWidths=[col_w] * 4, rowHeights=[14, 18])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.white),
        ('BOX',        (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('INNERGRID',  (0, 0), (-1, -1), 0.3, BORDER_COLOR),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('ROUNDEDCORNERS', [3]),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 6 * mm))

    # ── Active filters note ──
    filter_parts = []
    if filters_applied.get('status'):
        filter_parts.append(f"Payment Status: <b>{filters_applied['status']}</b>")
    if filters_applied.get('search_term') and filters_applied.get('search_field'):
        field_label = 'Patient ID' if filters_applied['search_field'] == 'patient_id' else 'Mobile'
        filter_parts.append(f"Search ({field_label}): <b>{filters_applied['search_term']}</b>")

    if filter_parts:
        filter_text = '  ·  '.join(filter_parts)
        story.append(Paragraph(
            f'<font color="#475569">Active filters — </font>{filter_text}',
            ParagraphStyle('FilterNote', fontName='Helvetica', fontSize=7.5,
                           textColor=MUTED_TEXT, leading=10, spaceAfter=4)
        ))
        story.append(HRFlowable(width='100%', thickness=0.4,
                                color=BORDER_COLOR, spaceAfter=4))

    # ── Table header definition ──
    # Columns: #  |  Patient ID  |  Name  |  Discharge Date  |  Discharge Time  |  Mobile  |  Due Note  |  Payment Status
    COL_WIDTHS = [
        8  * mm,   # Serial
        22 * mm,   # Patient ID
        38 * mm,   # Name
        24 * mm,   # Discharge Date
        20 * mm,   # Discharge Time
        26 * mm,   # Mobile
        None,      # Due Note (fills remaining)
        22 * mm,   # Payment Status
    ]
    # calculate flexible "Due Note" column
    fixed = sum(w for w in COL_WIDTHS if w is not None)
    COL_WIDTHS[6] = usable_w - fixed

    # Header row
    col_head_style = ParagraphStyle(
        'ColHead', fontName='Helvetica-Bold', fontSize=7,
        textColor=COL_HEAD_FG, leading=9, alignment=TA_CENTER,
    )
    header_row = [
        Paragraph('#',                col_head_style),
        Paragraph('Patient ID',       col_head_style),
        Paragraph('Name',             col_head_style),
        Paragraph('Discharge Date',   col_head_style),
        Paragraph('Discharge Time',   col_head_style),
        Paragraph('Mobile',           col_head_style),
        Paragraph('Due Note',         col_head_style),
        Paragraph('Payment',          col_head_style),
    ]

    # ── Cell styles ──
    cell_base = ParagraphStyle(
        'CellBase', fontName='Helvetica', fontSize=7.5,
        textColor=BRAND_DARK, leading=10, alignment=TA_CENTER,
    )
    cell_left = ParagraphStyle(
        'CellLeft', fontName='Helvetica', fontSize=7.5,
        textColor=BRAND_DARK, leading=10, alignment=TA_LEFT,
    )
    cell_muted = ParagraphStyle(
        'CellMuted', fontName='Helvetica', fontSize=7.5,
        textColor=MUTED_TEXT, leading=10, alignment=TA_CENTER,
    )
    cell_note = ParagraphStyle(
        'CellNote', fontName='Helvetica', fontSize=7,
        textColor=MUTED_TEXT, leading=9, alignment=TA_LEFT,
    )

    def _status_style(status):
        """Return coloured paragraph style for payment status."""
        colour_map = {
            'Paid':         '#059669',
            'Due':          '#dc2626',
            'Partial Paid': '#d97706',
        }
        hex_c = colour_map.get(status, '#475569')
        return ParagraphStyle(
            f'Status_{status}', fontName='Helvetica-Bold', fontSize=7,
            textColor=colors.HexColor(hex_c), leading=9, alignment=TA_CENTER,
        )

    def _row_bg(status):
        bg_map = {
            'Paid':         ROW_PAID,
            'Due':          ROW_DUE,
            'Partial Paid': ROW_PARTIAL,
        }
        return bg_map.get(status, None)

    # ── Build data rows ──
    table_data  = [header_row]
    row_colours = []   # (row_index, bg_colour)

    for idx, rec in enumerate(queryset_data, start=1):
        date_str, time_str = _fmt_date_from_model(rec.get('discharge_date'))
        due_note = rec.get('discharge_due_note') or '—'
        status   = rec.get('discharge_status') or '—'
        pid      = rec.get('patient_id') or '—'
        name     = rec.get('name') or '—'
        mobile   = rec.get('contact_number') or '—'

        row = [
            Paragraph(str(idx),    cell_base),
            Paragraph(str(pid),    cell_base),
            Paragraph(str(name),   cell_left),
            Paragraph(date_str,    cell_muted),
            Paragraph(time_str,    cell_muted),
            Paragraph(str(mobile), cell_muted),
            Paragraph(str(due_note), cell_note),
            Paragraph(str(status), _status_style(status)),
        ]
        table_data.append(row)

        # Row colouring: status-based tint
        bg = _row_bg(status)
        if bg:
            row_colours.append((idx, bg))   # +1 offset because row 0 is header

    # ── Assemble table ──
    main_table = Table(table_data, colWidths=COL_WIDTHS, repeatRows=1)

    ts = TableStyle([
        # Header
        ('BACKGROUND',    (0, 0),  (-1, 0),  COL_HEAD_BG),
        ('TEXTCOLOR',     (0, 0),  (-1, 0),  COL_HEAD_FG),
        ('FONTNAME',      (0, 0),  (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0),  (-1, 0),  7),
        ('ALIGN',         (0, 0),  (-1, 0),  'CENTER'),
        ('VALIGN',        (0, 0),  (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0),  (-1, 0),  5),
        ('BOTTOMPADDING', (0, 0),  (-1, 0),  5),
        # Body rows
        ('FONTNAME',      (0, 1),  (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 1),  (-1, -1), 7.5),
        ('TOPPADDING',    (0, 1),  (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1),  (-1, -1), 4),
        ('LEFTPADDING',   (0, 0),  (-1, -1), 5),
        ('RIGHTPADDING',  (0, 0),  (-1, -1), 5),
        # Grid
        ('BOX',           (0, 0),  (-1, -1), 0.5, BORDER_COLOR),
        ('INNERGRID',     (0, 0),  (-1, -1), 0.3, BORDER_COLOR),
        # Alternating row shade on even rows (where no status colour)
        *[('BACKGROUND', (0, i), (-1, i), ROW_ALT)
          for i in range(2, len(table_data), 2)],
    ])

    # Apply status-coloured rows on top of alternating
    for row_i, bg_c in row_colours:
        ts.add('BACKGROUND', (0, row_i), (-1, row_i), bg_c)

    main_table.setStyle(ts)
    story.append(main_table)

    # ── Build PDF ──
    def make_canvas(*args, **kwargs):
        return _HeaderFooterCanvas(
            *args,
            report_title='Discharge Patient Report',
            hospital_name='HealthCare Management System',
            generated_at=generated_at,
            total_records=total_records,
            **kwargs,
        )

    doc.build(story, canvasmaker=make_canvas)
    return buffer.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Django view
# ─────────────────────────────────────────────────────────────────────────────
@method_decorator(csrf_exempt, name='dispatch')
class DischargeReportPdfView(View):
    def get(self, request, *args, **kwargs):
        try:
            status       = request.GET.get('status', '').strip()
            search_field = request.GET.get('search_field', 'patient_id').strip()
            search_term  = request.GET.get('search_term', '').strip()
            sort_key     = request.GET.get('sort_key', 'discharge_date').strip()
            sort_dir     = request.GET.get('sort_dir', 'desc').strip()

            qs = DischargedRecord.objects.values(  # ← correct model
                'patient_id', 'name', 'age', 'gender', 'blood_group',
                'email', 'contact_number', 'address', 'emergency_contact',
                'cause_of_admission', 'admit_doctor_by', 'cabin_ward_no',
                'important_notes', 'discharge_date', 'discharge_by',
                'discharge_status', 'discharge_due_note',
                # no admit_date per your requirement
            )

            if status:
                qs = qs.filter(discharge_status=status)

            if search_term:
                if search_field == 'patient_id':
                    qs = qs.filter(patient_id__icontains=search_term)
                elif search_field == 'contact_number':
                    qs = qs.filter(contact_number__icontains=search_term)

            ALLOWED_SORT_FIELDS = {
                'patient_id', 'name', 'discharge_date',
                'discharge_status', 'contact_number',
            }
            if sort_key not in ALLOWED_SORT_FIELDS:
                sort_key = 'discharge_date'

            order_prefix = '-' if sort_dir == 'desc' else ''
            qs = qs.order_by(f'{order_prefix}{sort_key}')

            records = list(qs)

            if not records:
                return JsonResponse(
                    {'success': False, 'message': 'No records found for the selected filters.'},
                    status=404
                )

            filters_applied = {
                'status':       status or None,
                'search_field': search_field if search_term else None,
                'search_term':  search_term or None,
            }
            pdf_bytes = generate_discharge_patient_pdf(records, filters_applied)

            date_str = datetime.now().strftime('%Y-%m-%d')
            filename = f'discharge-report-{date_str}.pdf'
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = len(pdf_bytes)
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'
            return response

        except Exception as exc:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'message': str(exc)}, status=500)
        


# ─────────────────────────────────────────────────────────────────────────────
# URL pattern for the PDF report view
# ─────────────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([AllowAny])
def available_cabin_ward_for_report(request):

    cabins = CabinWardDetails.objects.all().order_by('cabin_ward_no')
 
    available = []
    engaged = []
 
    for cabin in cabins:
        # Build the base dict
        entry = {
            "id":               cabin.id,
            "cabin_ward_no":    cabin.cabin_ward_no,
            "cabin_ward_charge": cabin.cabin_ward_charge,
            "service_charge":   cabin.service_charge,
            "discount":         cabin.discount,
            "final_charge":     cabin.final_charge,
            "is_available":     cabin.is_available,
            "comments":         cabin.comments,
            "patient_info":     None,
        }
 
        if cabin.is_available:
            available.append(entry)
        else:
            # Find the admitted patient occupying this cabin/ward
            patient = (
                AdmitPatient.objects
                .filter(cabin_ward_no=cabin)
                .select_related('admit_doctor_by')
                .order_by('-created_at')
                .first()
            )
 
            if patient:
                entry["patient_info"] = {
                    "patient_id":          patient.patient_id,
                    "patient_name":        patient.name,
                    "admitted_by_doctor":  (
                        patient.admit_doctor_by.doctor_name   # adjust field name to your DoctorDetails model
                        if patient.admit_doctor_by else "N/A"
                    ),
                }
 
            engaged.append(entry)
 
    return JsonResponse({
        "available":       available,
        "engaged":         engaged,
        "total":           len(available) + len(engaged),
        "available_count": len(available),
        "engaged_count":   len(engaged),
    }, safe=False)



@api_view(['GET'])
@permission_classes([AllowAny])
def get_voucher_records(request):
    """
    API endpoint to fetch voucher records with filters:
    - from_date: Filter records from this date (YYYY-MM-DD)
    - to_date: Filter records to this date (YYYY-MM-DD)
    - voucher_no: Search by voucher number (partial match)
    """
    try:
        # Get query parameters
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        voucher_no = request.GET.get('voucher_no', '').strip()
        
        # Start with all records
        queryset = VoucherDetails.objects.select_related('account_head').all()
        
        # Apply date range filter
        if from_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                queryset = queryset.filter(created_at__date__gte=from_date_obj.date())
            except ValueError:
                pass
        
        if to_date:
            try:
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                # Add one day to include the end date fully
                to_date_end = to_date_obj + timedelta(days=1)
                queryset = queryset.filter(created_at__lt=to_date_end)
            except ValueError:
                pass
        
        # Apply voucher number search (partial match)
        if voucher_no:
            queryset = queryset.filter(voucher_number__icontains=voucher_no)
        
        # Order by created_at descending by default
        queryset = queryset.order_by('-created_at')
        
        # Serialize data
        records = []
        for voucher in queryset:
            records.append({
                'id': voucher.id,
                'voucher_number': voucher.voucher_number,
                'account_head': {
                    'id': voucher.account_head.id if voucher.account_head else None,
                    'account_head_code': voucher.account_head.account_head_code if voucher.account_head else None,
                    'account_head_name': voucher.account_head.account_head_name if voucher.account_head else None,
                } if voucher.account_head else None,
                'account_head_type': voucher.account_head_type,
                'amount': voucher.amount,
                'transaction_type': voucher.transaction_type,
                'comments': voucher.comments,
                'created_at': voucher.created_at.isoformat() if voucher.created_at else None,
            })
        
        return Response({
            'success': True,
            'records': records,
            'count': len(records),
            'filters': {
                'from_date': from_date,
                'to_date': to_date,
                'voucher_no': voucher_no,
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'success': False,
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)