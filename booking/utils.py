"""
Utility functions for permissions, role verification, and email notifications.
"""

from functools import wraps
from django.shortcuts import render
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import Group


STAFF_GROUP_NAME = 'Staff'
CUSTOMER_GROUP_NAME = 'Customer'


def ensure_groups_exist():
    """
    Ensures that 'Staff' and 'Customer' groups exist in the database.
    Safe to call during startup or view dispatch.
    """
    Group.objects.get_or_create(name=STAFF_GROUP_NAME)
    Group.objects.get_or_create(name=CUSTOMER_GROUP_NAME)


def is_staff_member(user):
    """
    Returns True if the user is authenticated and belongs to the 'Staff' group
    or is a Django superuser/staff user.
    """
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=STAFF_GROUP_NAME).exists()


def is_customer_member(user):
    """
    Returns True if the user is authenticated and belongs to the 'Customer' group.
    """
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=CUSTOMER_GROUP_NAME).exists()


def staff_required(view_func):
    """
    Decorator for views that checks that the user is logged in and is in the 'Staff' group.
    If the user is not in the Staff group, it renders a friendly 403 'staff only' template.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

        if not is_staff_member(request.user):
            # Render custom 403-style Staff Only page
            return render(request, 'booking/403_staff_only.html', status=403)

        return view_func(request, *args, **kwargs)
    return _wrapped_view


# ==========================================
# Dev-Friendly Email Notifications (Console)
# ==========================================

def send_booking_created_email(appointment):
    """
    Sends email notification when a new booking is created with status 'pending'.
    Dev-friendly console output: prints directly to the terminal running the server.
    """
    subject = f"Salon Appointment Request Received - #{appointment.pk} ({appointment.service.name})"
    slot = appointment.slot
    customer_name = appointment.customer.get_full_name() or appointment.customer.username
    staff_name = slot.staff.get_full_name() or slot.staff.username

    message = (
        f"Hello {customer_name},\n\n"
        f"Thank you for booking with us! Your appointment request has been received and is currently PENDING approval.\n\n"
        f"--- APPOINTMENT DETAILS ---\n"
        f"Reference #: {appointment.pk}\n"
        f"Service: {appointment.service.name} ({appointment.service.duration_minutes} min - ${appointment.service.price})\n"
        f"Date: {slot.date.strftime('%A, %B %d, %Y')}\n"
        f"Time: {slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}\n"
        f"Stylist / Staff: {staff_name}\n"
        f"Status: PENDING\n\n"
        f"Notes: {appointment.notes or 'None'}\n\n"
        f"Our team will review your booking shortly. You can track your booking status on the 'My Bookings' page.\n\n"
        f"Best regards,\n"
        f"The Salon Team"
    )

    recipient_list = [appointment.customer.email] if appointment.customer.email else ['customer@example.local']
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
    except Exception as e:
        print(f"[Email Error] Could not send booking created email: {e}")


def send_booking_confirmed_email(appointment):
    """
    Sends email notification when staff confirms a pending appointment.
    """
    subject = f"Appointment Confirmed! - #{appointment.pk} ({appointment.service.name})"
    slot = appointment.slot
    customer_name = appointment.customer.get_full_name() or appointment.customer.username
    staff_name = slot.staff.get_full_name() or slot.staff.username

    message = (
        f"Hello {customer_name},\n\n"
        f"Great news! Your salon appointment has been CONFIRMED by our staff.\n\n"
        f"--- CONFIRMED DETAILS ---\n"
        f"Reference #: {appointment.pk}\n"
        f"Service: {appointment.service.name}\n"
        f"Date: {slot.date.strftime('%A, %B %d, %Y')}\n"
        f"Time: {slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}\n"
        f"Stylist / Staff: {staff_name}\n"
        f"Status: CONFIRMED\n\n"
        f"We look forward to seeing you! If you need to make changes, please visit 'My Bookings'.\n\n"
        f"Warm regards,\n"
        f"The Salon Team"
    )

    recipient_list = [appointment.customer.email] if appointment.customer.email else ['customer@example.local']
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
    except Exception as e:
        print(f"[Email Error] Could not send booking confirmed email: {e}")


def send_booking_cancelled_email(appointment, cancelled_by="Customer"):
    """
    Sends email notification when an appointment is cancelled by either customer or staff.
    """
    subject = f"Appointment Cancelled - #{appointment.pk} ({appointment.service.name})"
    slot = appointment.slot
    customer_name = appointment.customer.get_full_name() or appointment.customer.username
    staff_name = slot.staff.get_full_name() or slot.staff.username

    message = (
        f"Hello {customer_name},\n\n"
        f"This is to notify you that appointment #{appointment.pk} has been CANCELLED (by {cancelled_by}).\n\n"
        f"--- CANCELLED APPOINTMENT DETAILS ---\n"
        f"Service: {appointment.service.name}\n"
        f"Original Date: {slot.date.strftime('%A, %B %d, %Y')}\n"
        f"Original Time: {slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}\n"
        f"Staff Member: {staff_name}\n"
        f"Status: CANCELLED\n\n"
        f"The time slot has been freed. You are welcome to book another time slot at your convenience!\n\n"
        f"Sincerely,\n"
        f"The Salon Team"
    )

    recipient_list = [appointment.customer.email] if appointment.customer.email else ['customer@example.local']
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
    except Exception as e:
        print(f"[Email Error] Could not send booking cancelled email: {e}")


def send_appointment_rescheduled_email(appointment, old_slot):
    """
    Sends email notification when staff reschedules an appointment to a new slot.
    """
    subject = f"Appointment Rescheduled - #{appointment.pk} ({appointment.service.name})"
    new_slot = appointment.slot
    customer_name = appointment.customer.get_full_name() or appointment.customer.username
    staff_name = new_slot.staff.get_full_name() or new_slot.staff.username

    message = (
        f"Hello {customer_name},\n\n"
        f"Your salon appointment has been RESCHEDULED to a new time.\n\n"
        f"--- PREVIOUS SCHEDULE ---\n"
        f"Date: {old_slot.date.strftime('%A, %B %d, %Y')}\n"
        f"Time: {old_slot.start_time.strftime('%I:%M %p')} - {old_slot.end_time.strftime('%I:%M %p')}\n\n"
        f"--- NEW SCHEDULE ---\n"
        f"Service: {appointment.service.name}\n"
        f"Date: {new_slot.date.strftime('%A, %B %d, %Y')}\n"
        f"Time: {new_slot.start_time.strftime('%I:%M %p')} - {new_slot.end_time.strftime('%I:%M %p')}\n"
        f"Stylist / Staff: {staff_name}\n"
        f"Status: {appointment.get_status_display().upper()}\n\n"
        f"Please check your 'My Bookings' page to view your updated schedule.\n\n"
        f"Best regards,\n"
        f"The Salon Team"
    )

    recipient_list = [appointment.customer.email] if appointment.customer.email else ['customer@example.local']
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
    except Exception as e:
        print(f"[Email Error] Could not send appointment rescheduled email: {e}")
