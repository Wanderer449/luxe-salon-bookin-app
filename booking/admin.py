"""
Django Admin registration for booking models.
"""

from django.contrib import admin
from .models import Service, TimeSlot, Appointment


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_minutes', 'price', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)
    list_editable = ('is_active',)


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('staff', 'date', 'start_time', 'end_time', 'is_booked')
    list_filter = ('date', 'is_booked', 'staff')
    search_fields = ('staff__username', 'staff__first_name', 'staff__last_name')
    date_hierarchy = 'date'


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'service', 'get_slot_date', 'get_slot_time', 'status', 'created_at')
    list_filter = ('status', 'service', 'slot__date')
    search_fields = ('customer__username', 'customer__first_name', 'customer__last_name', 'notes')
    date_hierarchy = 'slot__date'

    @admin.display(description="Date", ordering="slot__date")
    def get_slot_date(self, obj):
        return obj.slot.date

    @admin.display(description="Time", ordering="slot__start_time")
    def get_slot_time(self, obj):
        return f"{obj.slot.start_time.strftime('%H:%M')} - {obj.slot.end_time.strftime('%H:%M')}"
