from rest_framework import serializers


class DaySerializer(serializers.Serializer):
    date = serializers.DateField()
    total_capacity_hours = serializers.FloatField()
    allocated_hours = serializers.FloatField()
    utilisation_pct = serializers.FloatField()


class AssignedStaffSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ScheduledJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client_name = serializers.CharField()
    remaining_hours = serializers.FloatField()
    delivery_date = serializers.DateField(allow_null=True)
    anticipated_start_date = serializers.DateField(allow_null=True)
    anticipated_end_date = serializers.DateField(allow_null=True)
    is_late = serializers.BooleanField()
    min_people = serializers.IntegerField()
    max_people = serializers.IntegerField()
    assigned_staff = AssignedStaffSerializer(many=True)
    anticipated_staff = AssignedStaffSerializer(many=True)


class UnscheduledJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client_name = serializers.CharField()
    delivery_date = serializers.DateField(allow_null=True)
    remaining_hours = serializers.FloatField()
    reason = serializers.CharField()


class WorkshopScheduleResponseSerializer(serializers.Serializer):
    days = DaySerializer(many=True)
    jobs = ScheduledJobSerializer(many=True)
    unscheduled_jobs = UnscheduledJobSerializer(many=True)


class WorkshopScheduleQuerySerializer(serializers.Serializer):
    day_horizon = serializers.IntegerField(
        required=False, min_value=1, max_value=365, default=14
    )
