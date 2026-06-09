from datetime import datetime
import os
import uuid
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Max
from uuid import uuid4

# Create your models here.


class UserDetails(models.Model):
    id = models.AutoField(primary_key=True)
    user_name = models.CharField(max_length=50)
    user_category = models.CharField(max_length=50, default="pending", null=True, blank=True)
    user_role = models.CharField(max_length=100, default="user", null=True, blank=True)
    user_status = models.CharField(max_length=50, default="pending", null=True, blank=True)
    mobile_no = models.CharField(max_length=12, null=True, blank=True)
    # FK --
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="details")


    def __str__(self) -> str:
        return self.user_name

    class Meta:
        db_table = "auth_user_details"


class DoctorDetails(models.Model):
    id = models.AutoField(primary_key=True)
    doctor_name = models.CharField(max_length=100)
    specialization = models.CharField(max_length=100, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    contact = models.CharField(max_length=15, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    address = models.CharField(max_length=200, null=True, blank=True)

    def __str__(self) -> str:
        return self.doctor_name

    class Meta:
        db_table = "lkp_doctor_details"



class CabinWardDetails(models.Model):
    id = models.AutoField(primary_key=True)
    cabin_ward_no = models.CharField(max_length=100)
    cabin_ward_charge = models.IntegerField(null=True, blank=True)
    service_charge = models.IntegerField(null=True, blank=True)
    discount = models.IntegerField(null=True, blank=True)
    final_charge = models.IntegerField(null=True, blank=True)
    is_available = models.BooleanField(default=True)
    comments = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Calculate final_charge before saving
        if self.cabin_ward_charge and self.service_charge and self.discount is not None:
            total_charge = self.cabin_ward_charge + self.service_charge
            discount_amount = total_charge * (self.discount / 100)
            self.final_charge = int(total_charge - discount_amount)
        elif self.cabin_ward_charge and self.service_charge:
            # If discount is not provided, final_charge = total charge
            self.final_charge = self.cabin_ward_charge + self.service_charge
        else:
            self.final_charge = None
        
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.cabin_ward_no

    class Meta:
        db_table = "lkp_cabin_ward_details"



class TestGroup(models.Model):
    id = models.AutoField(primary_key=True)
    test_group_name = models.CharField(max_length=100)
    comments = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return self.test_group_name

    class Meta:
        db_table = "lkp_test_group"
        


class TestDetails(models.Model):
    id = models.AutoField(primary_key=True)
    test_group = models.ForeignKey(TestGroup, on_delete=models.SET_NULL, null=True, blank=True)
    test_name = models.CharField(max_length=100)
    test_charge = models.IntegerField(null=True, blank=True)
    discount = models.IntegerField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return self.test_name
    
    def save(self, *args, **kwargs):
        # Ensure test_charge is not negative
        if self.test_charge is not None and self.test_charge < 0:
            raise ValueError("Test charge cannot be negative.")
        
        # Ensure discount is between 0 and 100
        if self.discount is not None and (self.discount < 0 or self.discount > 100):
            raise ValueError("Discount must be between 0 and 100.")
        
        # Calculate final charge if test_charge and discount are provided
        if self.test_charge is not None and self.discount is not None:
            discount_amount = self.test_charge * (self.discount / 100)
            final_charge = int(self.test_charge - discount_amount)
            self.comments = f"Final charge after {self.discount}% discount: {final_charge}"
        elif self.test_charge is not None:
            self.comments = f"Final charge: {self.test_charge}"
        else:
            self.comments = "Test charge not provided."
        
        super().save(*args, **kwargs)

    class Meta:
        db_table = "lkp_test_details"



class AccountHeadType(models.Model):
    id = models.AutoField(primary_key=True)
    account_head_type_name = models.CharField(max_length=50, unique=True)
    comments = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return self.account_head_type_name

    class Meta:
        db_table = "lkp_account_head_type"



class AccountHead(models.Model):
    id = models.AutoField(primary_key=True)
    account_head_code = models.CharField(max_length=20, unique=True)
    account_head_name = models.CharField(max_length=100)
    account_head_type = models.ForeignKey(AccountHeadType, on_delete=models.SET_NULL, null=True, blank=True)
    comments = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return self.account_head_name

    class Meta:
        db_table = "lkp_account_head"



class VoucherDetails(models.Model):
    id = models.AutoField(primary_key=True)
    voucher_number = models.CharField(max_length=20, unique=True)
    account_head = models.ForeignKey(AccountHead, on_delete=models.SET_NULL, null=True, blank=True)
    account_head_type = models.CharField(max_length=10, null=True, blank=True)
    amount = models.IntegerField(null=True, blank=True)
    transaction_type = models.CharField(max_length=10, null=True, blank=True)  # "debit" or "credit"
    comments = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self) -> str:
        return self.voucher_number
    
    def save(self, *args, **kwargs):
        if not self.voucher_number:
            # Get current datetime in YYYYMMDDSS format
            now = datetime.now()
            datetime_str = now.strftime('%Y%m%d%S')  # YYYYMMDDSS format
            
            # Get the last voucher_number for this exact second
            last_voucher = VoucherDetails.objects.filter(
                voucher_number__startswith=datetime_str
            ).order_by('-voucher_number').first()
            
            if last_voucher:
                # Extract the sequence number from the last voucher_number
                # Format: YYYYMMDDSS + 2-digit sequence
                last_sequence = int(last_voucher.voucher_number[-2:])
                new_sequence = last_sequence + 1
            else:
                new_sequence = 1
            
            # Format sequence with leading zero (01, 02, etc.)
            sequence_str = f"{new_sequence:02d}"
            
            # Generate voucher_number with format: YYYYMMDDSS + Sequence
            self.voucher_number = f"{datetime_str}{sequence_str}"
        
        super().save(*args, **kwargs)

    class Meta:
        db_table = "tbl_voucher_details"




class AdmitPatient(models.Model):
    id = models.AutoField(primary_key=True)
    patient_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    age = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    blood_group = models.CharField(max_length=5, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    contact_number = models.CharField(max_length=15)
    address = models.CharField(max_length=200, null=True, blank=True)
    emergency_contact = models.CharField(max_length=100, null=True, blank=True)
    cause_of_admission = models.CharField(max_length=200, null=True, blank=True)
    admit_doctor_by = models.ForeignKey(DoctorDetails, on_delete=models.SET_NULL, null=True, blank=True, related_name="admitted_patients")
    cabin_ward_no = models.ForeignKey(CabinWardDetails, on_delete=models.SET_NULL, null=True, blank=True, related_name="admitted_patients")
    important_notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, help_text="Admission date and time")
    created_by = models.CharField(max_length=100, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    updated_by = models.CharField(max_length=100, null=True, blank=True)


    def __str__(self) -> str:
        return f"{self.patient_id} - {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.patient_id:
            # Get a random 6-digit number            
            random_number = uuid4().int % 1000000

            # Check if the generated patient_id already exists
            while AdmitPatient.objects.filter(patient_id=f"{random_number:06d}").exists():
                random_number = uuid4().int % 1000000

            self.patient_id = f"{random_number:06d}"
        super().save(*args, **kwargs)
            

    class Meta:
        db_table = "tbl_admit_patients"



class DischargedRecord(models.Model):
    id = models.AutoField(primary_key=True)
    patient_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    age = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    blood_group = models.CharField(max_length=5, null=True, blank=True) 
    email = models.EmailField(null=True, blank=True)
    contact_number = models.CharField(max_length=15)
    address = models.CharField(max_length=200, null=True, blank=True)
    emergency_contact = models.CharField(max_length=100, null=True, blank=True)
    cause_of_admission = models.CharField(max_length=200, null=True, blank=True)
    admit_doctor_by = models.CharField(max_length=100, null=True, blank=True) 
    cabin_ward_no = models.CharField(max_length=100, null=True, blank=True)
    important_notes = models.TextField(null=True, blank=True)
    admit_date = models.DateTimeField(null=True, blank=True) 
    provided_discount = models.IntegerField(null=True, blank=True) 
    total_discharge_amount = models.IntegerField(null=True, blank=True) 
    discharge_date = models.DateTimeField(null=True, blank=True)
    discharge_by = models.CharField(max_length=100, null=True, blank=True)
    discharge_status = models.CharField(max_length=20, null=True, blank=True)
    discharge_due_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    voucher_number = models.CharField(max_length=15, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.patient_id} - {self.name}"
    
    class Meta:
        db_table = "tbl_discharge_records"



class TestsRecord(models.Model):
    PATIENT_TYPE_CHOICES = [('Admitted', 'Admitted'),('Non-Admit', 'Non-Admit'),]
    id               = models.AutoField(primary_key=True)
    test_id          = models.CharField(max_length=6, unique=True, blank=True)
    test_date        = models.DateField(null=True, blank=True)
    patient_type     = models.CharField(max_length=10, choices=PATIENT_TYPE_CHOICES, null=True, blank=True)
    admitted_patient = models.ForeignKey('AdmitPatient', on_delete=models.SET_NULL, null=True, blank=True, related_name='test_records')
    name             = models.CharField(max_length=100)
    age              = models.IntegerField(null=True, blank=True)
    blood_group      = models.CharField(max_length=5, null=True, blank=True)
    mobile           = models.CharField(max_length=15, null=True, blank=True)
    test_doctor_by   = models.ForeignKey('DoctorDetails', on_delete=models.SET_NULL, null=True, blank=True, related_name='test_records')
    provided_discount= models.IntegerField(null=True, blank=True)
    total_test_amount= models.IntegerField(null=True, blank=True)
    voucher_number = models.CharField(max_length=15, null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    created_by       = models.CharField(max_length=100, null=True, blank=True)
    updated_at       = models.DateTimeField(auto_now=True, null=True, blank=True)
    updated_by       = models.CharField(max_length=100, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.test_id:
            random_number = uuid4().int % 1000000
            while TestsRecord.objects.filter(test_id=f"{random_number:06d}").exists():
                random_number = uuid4().int % 1000000
            self.test_id = f"{random_number:06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.test_id} — {self.name}"

    class Meta:
        db_table = 'tbl_tests_record'
        ordering = ['-created_at']



class TestsRecordItem(models.Model):
    """One row per test inside a TestsRecord visit."""
    id              = models.AutoField(primary_key=True)
    tests_record    = models.ForeignKey(TestsRecord, on_delete=models.CASCADE, related_name='items')
    test_amount     = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.tests_record.test_id} → {self.test}"

    class Meta:
        db_table = 'tbl_tests_record_items'


