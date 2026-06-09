
from rest_framework import serializers
from .models import TestGroup, TestDetails
 
 
class TestGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestGroup
        fields = ['id', 'test_group_name', 'comments']
 
 
class TestDetailsSerializer(serializers.ModelSerializer):
    # Read-only convenience field so the frontend can show the group name
    # without a second API call.
    test_group_name = serializers.CharField(
        source='test_group.test_group_name',
        read_only=True,
        default=None,
    )
 
    class Meta:
        model = TestDetails
        fields = [
            'id',
            'test_group',
            'test_group_name',
            'test_name',
            'test_charge',
            'discount',
            'comments',
        ]
        read_only_fields = ['id', 'test_group_name']

