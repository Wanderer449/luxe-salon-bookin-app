"""
Models for the Salon Booking & Appointment System.

Key concepts implemented:
1. Role-based constraints (Staff group foreign key filtering)
2. Validation logic in TimeSlot.clean() to prevent invalid time intervals and overlapping slots
3. DB-level uniqueness constraint to prevent identical slot start times
4. OneToOneField constraint on Appointment.slot ensuring a slot cannot have multiple appointments
"""

from datetime import datetime, date, time
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class Service(models.Model):
    """
    Represents a salon service (e.g., Haircut, Beard Trim, Styling, Coloring).
    """
    name = models.CharField(max_length=100)
    duration_minutes = models.PositiveIntegerField(
        help_text=_("Estimated duration in minutes (e.g., 15, 30, 45, 60)")
    )
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text=_("Price in dollars (e.g., 25.00)")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Designates whether this service is currently offered to customers.")
    )

    class Meta:
        ordering = ['name']
        verbose_name = _("Service")
        verbose_name_plural = _("Services")

    def __str__(self):
        return f"{self.name} ({self.duration_minutes} min - ${self.price})"


class TimeSlot(models.Model):
    """
    Represents an available or booked appointment window for a specific staff member.

    Validation rules:
    - end_time must strictly be after start_time.
    - Cannot overlap with any other slot belonging to the same staff member on the same date.
    - Unique constraint on (staff, date, start_time) at the database layer.
    """
    staff = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='time_slots',
        limit_choices_to={'groups__name': 'Staff'},
        help_text=_("Staff member assigned to this time slot.")
    )
    date = models.DateField(
        help_text=_("Date of the appointment slot.")
    )
    start_time = models.TimeField(
        help_text=_("Start time of the slot.")
    )
    end_time = models.TimeField(
        help_text=_("End time of the slot.")
    )
    is_booked = models.BooleanField(
        default=False,
        help_text=_("Tracks whether this slot has been booked by a customer.")
    )

    class Meta:
        ordering = ['date', 'start_time']
        constraints = [
            # DB-level constraint: Prevents duplicate slots for the same staff on the same date and start time
            models.UniqueConstraint(
                fields=['staff', 'date', 'start_time'],
                name='unique_staff_date_start_time'
            )
        ]
        verbose_name = _("Time Slot")
        verbose_name_plural = _("Time Slots")

    def clean(self):
        """
        Custom validation rules:
        1. end_time must be strictly greater than start_time.
        2. No overlapping time slots for the same staff member on the same date.
           Two time intervals [A_start, A_end) and [B_start, B_end) overlap if:
           A_start < B_end AND A_end > B_start.
        """
        super().clean()

        if self.start_time and self.end_time:
            # Check 1: end_time must be after start_time
            if self.end_time <= self.start_time:
                raise ValidationError({
                    'end_time': _("End time must be after the start time.")
                })

            # Check 2: Overlap check for the same staff on the same date
            if self.staff_id and self.date:
                # Query for any other slots by this staff member on the same date that overlap
                overlapping_slots = TimeSlot.objects.filter(
                    staff=self.staff,
                    date=self.date,
                    start_time__lt=self.end_time,
                    end_time__gt=self.start_time,
                )

                # Exclude the current instance if editing an existing slot
                if self.pk:
                    overlapping_slots = overlapping_slots.exclude(pk=self.pk)

                if overlapping_slots.exists():
                    first_conflict = overlapping_slots.first()
                    conflict_str = f"{first_conflict.start_time.strftime('%H:%M')} - {first_conflict.end_time.strftime('%H:%M')}"
                    raise ValidationError(
                        _(f"This time slot overlaps with an existing slot for {self.staff.get_full_name() or self.staff.username} on {self.date} ({conflict_str}).")
                    )

    def save(self, *args, **kwargs):
        """
        Enforce clean() validation on all programmatic model saves.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        booked_indicator = " [Booked]" if self.is_booked else " [Available]"
        staff_name = self.staff.get_full_name() or self.staff.username
        return f"{self.date} {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} ({staff_name}){booked_indicator}"


class Appointment(models.Model):
    """
    Represents a customer's booked appointment.

    CRITICAL CONSTRAINTS & CONCURRENCY:
    - slot is a OneToOneField:
      Guarantees at the database schema level that no two appointments can ever reference the same slot.
    - Concurrency Safety:
      Booking views use django.db.transaction.atomic and TimeSlot.objects.select_for_update()
      to lock the row during reservation, preventing race conditions.
    """
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_COMPLETED = 'completed'

    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pending')),
        (STATUS_CONFIRMED, _('Confirmed')),
        (STATUS_CANCELLED, _('Cancelled')),
        (STATUS_COMPLETED, _('Completed')),
    ]

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='appointments',
        help_text=_("Customer who made this appointment.")
    )
    # OneToOneField enforces database-level uniqueness: 1 slot = at most 1 appointment
    slot = models.OneToOneField(
        TimeSlot,
        on_delete=models.CASCADE,
        related_name='appointment',
        help_text=_("The reserved time slot.")
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name='appointments',
        help_text=_("The requested salon service.")
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        help_text=_("Current lifecycle status of the appointment.")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("Timestamp when the appointment was created.")
    )
    notes = models.TextField(
        blank=True,
        help_text=_("Optional customer notes or special requests.")
    )

    class Meta:
        ordering = ['-slot__date', '-slot__start_time']
        verbose_name = _("Appointment")
        verbose_name_plural = _("Appointments")

    def __str__(self):
        customer_name = self.customer.get_full_name() or self.customer.username
        return f"Appointment #{self.pk}: {self.service.name} for {customer_name} on {self.slot.date} ({self.get_status_display()})"

    @property
    def status_badge_class(self):
        """
        Returns Bootstrap 5 badge color class based on status:
        - pending: warning (yellow)
        - confirmed: primary (blue)
        - completed: success (green)
        - cancelled: danger (red)
        """
        mapping = {
            self.STATUS_PENDING: 'bg-warning text-dark',
            self.STATUS_CONFIRMED: 'bg-primary text-white',
            self.STATUS_COMPLETED: 'bg-success text-white',
            self.STATUS_CANCELLED: 'bg-danger text-white',
        }
        return mapping.get(self.status, 'bg-secondary text-white')

    def can_be_cancelled(self):
        """
        Customers can only cancel appointments that are pending or confirmed.
        """
        return self.status in [self.STATUS_PENDING, self.STATUS_CONFIRMED]
