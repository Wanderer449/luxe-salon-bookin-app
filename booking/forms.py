"""
Forms for the Salon Booking & Appointment System.
"""

from datetime import datetime, date, time, timedelta
from django import forms
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Service, TimeSlot, Appointment
from .utils import STAFF_GROUP_NAME, CUSTOMER_GROUP_NAME, ensure_groups_exist


class UserSignupForm(UserCreationForm):
    """
    Custom user signup form extending Django's built-in UserCreationForm.
    Allows user to select their role ('Customer' or 'Staff') via radio buttons,
    automatically assigning them to the corresponding Django Group upon creation.
    """
    ROLE_CHOICES = [
        (CUSTOMER_GROUP_NAME, 'Customer — Browse salon services and book appointments'),
        (STAFF_GROUP_NAME, 'Staff / Stylist — Manage schedule slots and client appointments'),
    ]

    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'})
    )
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial=CUSTOMER_GROUP_NAME,
        help_text=_("Select your account type.")
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apply Bootstrap form-control class to all text/password fields
        for field_name, field in self.fields.items():
            if field_name != 'role':
                existing_classes = field.widget.attrs.get('class', '')
                if 'form-control' not in existing_classes:
                    field.widget.attrs['class'] = f"{existing_classes} form-control".strip()

    def save(self, commit=True):
        """
        Saves user and assigns them to the chosen Django Group ('Staff' or 'Customer').
        """
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']

        role = self.cleaned_data.get('role', CUSTOMER_GROUP_NAME)
        if role == STAFF_GROUP_NAME:
            user.is_staff = True  # Optional convenience for Django admin access

        if commit:
            user.save()
            ensure_groups_exist()
            group = Group.objects.get(name=role)
            user.groups.add(group)

        return user


class SlotBulkCreateForm(forms.Form):
    """
    Form for staff to generate non-overlapping time slots in bulk for a given day.
    Pick date, start time, end time, and slot duration.
    """
    DURATION_CHOICES = [
        (15, '15 minutes'),
        (30, '30 minutes (Standard)'),
        (45, '45 minutes'),
        (60, '60 minutes (1 Hour)'),
        (90, '90 minutes (1.5 Hours)'),
    ]

    staff = forms.ModelChoiceField(
        queryset=User.objects.filter(groups__name=STAFF_GROUP_NAME),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_("Staff Member / Stylist"),
        help_text=_("Choose which staff member these slots belong to.")
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        label=_("Target Date"),
        initial=date.today
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        label=_("Shift Start Time"),
        initial=time(9, 0)
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        label=_("Shift End Time"),
        initial=time(17, 0)
    )
    slot_length = forms.ChoiceField(
        choices=DURATION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial=30,
        label=_("Slot Duration")
    )

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        slot_length = cleaned_data.get('slot_length')

        if start_time and end_time:
            if end_time <= start_time:
                raise ValidationError(_("End time must be after start time."))

            slot_minutes = int(slot_length) if slot_length else 30
            # Calculate total duration in minutes
            dt_start = datetime.combine(date.today(), start_time)
            dt_end = datetime.combine(date.today(), end_time)
            total_minutes = (dt_end - dt_start).total_seconds() / 60

            if total_minutes < slot_minutes:
                raise ValidationError(_(
                    f"The time window ({int(total_minutes)} min) is shorter than one slot duration ({slot_minutes} min)."
                ))

        return cleaned_data


class BookingSubmissionForm(forms.Form):
    """
    Customer form for confirming their appointment request.
    """
    service = forms.ModelChoiceField(
        queryset=Service.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_("Service")
    )
    slot_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Add any notes, hairstyle preferences, or special requests...'
        }),
        label=_("Notes (Optional)")
    )


class AppointmentRescheduleForm(forms.Form):
    """
    Form for staff to reassign an appointment to a free time slot.
    """
    new_slot = forms.ModelChoiceField(
        queryset=TimeSlot.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_("Select New Free Time Slot")
    )

    def __init__(self, *args, **kwargs):
        current_slot = kwargs.pop('current_slot', None)
        super().__init__(*args, **kwargs)
        # Offer only available slots from today onward
        qs = TimeSlot.objects.filter(
            is_booked=False,
            date__gte=date.today()
        ).order_by('date', 'start_time')
        if current_slot:
            qs = qs.exclude(pk=current_slot.pk)
        self.fields['new_slot'].queryset = qs
