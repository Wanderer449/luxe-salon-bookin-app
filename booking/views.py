"""
Views for the Salon Booking & Appointment System.

BEGINNER-FRIENDLY ARCHITECTURE NOTES:
1. Transaction & Concurrency Safety:
   In booking_create_view and appointment_reschedule_view, we wrap slot updates inside
   `transaction.atomic()` and fetch the TimeSlot using `.select_for_update()`.
   This places a row-level lock on the chosen TimeSlot record in SQLite/PostgreSQL.
   If another user attempts to book the same slot at the exact same millisecond,
   their query will wait for the lock to release, then see that `slot.is_booked == True`
   and be rejected cleanly with a friendly error message ("This slot was just taken").

2. Role & Permission Enforcing:
   - Views under `/staff/` are protected with `@staff_required`. If a customer or anonymous
     user navigates to `/staff/`, they are shown an explicit 403-style 'Staff Only' template.
   - Customer booking views are protected with `@login_required`.
   - Cancellation checks ensure that users can only cancel their OWN appointments, and
     only if the status is still 'pending' or 'confirmed'.
"""

from datetime import datetime, date, time, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse, HttpResponseForbidden
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone

from .models import Service, TimeSlot, Appointment
from .forms import (
    UserSignupForm,
    SlotBulkCreateForm,
    BookingSubmissionForm,
    AppointmentRescheduleForm,
)
from .utils import (
    staff_required,
    is_staff_member,
    is_customer_member,
    ensure_groups_exist,
    send_booking_created_email,
    send_booking_confirmed_email,
    send_booking_cancelled_email,
    send_appointment_rescheduled_email,
    STAFF_GROUP_NAME,
    CUSTOMER_GROUP_NAME,
)


# ==========================================
# Public & Authentication Views
# ==========================================

def home_view(request):
    """
    Public landing page for the salon.
    Displays featured services, business hours, and quick booking links.
    """
    services = Service.objects.filter(is_active=True)[:6]
    return render(request, 'booking/home.html', {
        'services': services,
    })


def signup_view(request):
    """
    User registration view.
    Renders UserSignupForm containing the role selection radio buttons ('Customer' vs 'Staff').
    Upon submission, assigns user to the chosen group and logs them in.
    """
    if request.user.is_authenticated:
        return redirect('role_redirect')

    if request.method == 'POST':
        form = UserSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Log the new user in immediately
            login(request, user)
            selected_role = form.cleaned_data.get('role')
            messages.success(
                request,
                f"Welcome, {user.first_name or user.username}! Your account has been created with role: {selected_role}."
            )
            if selected_role == STAFF_GROUP_NAME:
                return redirect('staff_dashboard')
            return redirect('book_appointment')
    else:
        form = UserSignupForm()

    return render(request, 'booking/signup.html', {'form': form})


def login_view(request):
    """
    User login view with role-aware redirection.
    """
    if request.user.is_authenticated:
        return redirect('role_redirect')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            
            # If a 'next' query param is provided, honor it
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url:
                return redirect(next_url)

            # Otherwise redirect based on role
            return redirect('role_redirect')
        else:
            messages.error(request, "Invalid username or password. Please try again.")
    else:
        form = AuthenticationForm()

    return render(request, 'booking/login.html', {'form': form})


def logout_view(request):
    """
    Logs out the current user and redirects to the login page.
    """
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('login')


@login_required
def role_redirect_view(request):
    """
    Smart router redirecting authenticated users to their primary workspace:
    - Staff members -> /staff/
    - Customers -> /my-bookings/
    """
    if is_staff_member(request.user):
        return redirect('staff_dashboard')
    return redirect('my_bookings')


# ==========================================
# Customer Views
# ==========================================

def services_view(request):
    """
    Displays the catalog of all active salon services with duration and pricing.
    """
    services = Service.objects.filter(is_active=True)
    return render(request, 'booking/services.html', {
        'services': services,
    })


@login_required
def book_appointment_view(request):
    """
    Interactive customer booking view.
    1. Select a service
    2. View 7-day calendar grid of available time slots
    3. Confirm reservation with atomic lock (select_for_update) to prevent race conditions.
    """
    services = Service.objects.filter(is_active=True)
    if not services.exists():
        messages.warning(request, "No active services are currently available. Please check back later.")

    # Selected service ID (from query param or first active service)
    selected_service_id = request.GET.get('service')
    selected_service = None
    if selected_service_id:
        selected_service = Service.objects.filter(pk=selected_service_id, is_active=True).first()
    if not selected_service and services.exists():
        selected_service = services.first()

    # Determine start date for the 7-day grid view (default today)
    start_date_str = request.GET.get('date')
    try:
        if start_date_str:
            grid_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            grid_start_date = date.today()
    except ValueError:
        grid_start_date = date.today()

    # Build 7-day calendar window
    week_days = []
    for day_offset in range(7):
        target_day = grid_start_date + timedelta(days=day_offset)
        # Fetch slots for this day
        day_slots = TimeSlot.objects.filter(
            date=target_day
        ).select_related('staff').order_by('start_time')

        week_days.append({
            'date': target_day,
            'is_today': target_day == date.today(),
            'is_past': target_day < date.today(),
            'slots': day_slots,
            'available_count': day_slots.filter(is_booked=False).count(),
        })

    # Navigation for 7-day grid (previous week, next week)
    prev_week_date = grid_start_date - timedelta(days=7)
    next_week_date = grid_start_date + timedelta(days=7)

    return render(request, 'booking/book.html', {
        'services': services,
        'selected_service': selected_service,
        'grid_start_date': grid_start_date,
        'week_days': week_days,
        'prev_week_date': prev_week_date,
        'next_week_date': next_week_date,
        'today': date.today(),
    })


@login_required
def api_slots_view(request):
    """
    Lightweight JSON endpoint for dynamic UI slot fetching by date.
    Used by vanilla JS for frictionless tab switching without full reload.
    """
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'error': 'Date parameter is required.'}, status=400)

    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

    slots = TimeSlot.objects.filter(date=query_date).select_related('staff').order_by('start_time')
    slots_data = []
    for s in slots:
        slots_data.append({
            'id': s.pk,
            'start_time': s.start_time.strftime('%I:%M %p'),
            'end_time': s.end_time.strftime('%I:%M %p'),
            'staff_name': s.staff.get_full_name() or s.staff.username,
            'is_booked': s.is_booked,
            'is_past': s.date < date.today(),
        })

    return JsonResponse({'date': date_str, 'slots': slots_data})


@login_required
def booking_confirm_view(request):
    """
    Handles atomic booking creation.

    CONCURRENCY & RACE CONDITION SAFETY:
    -----------------------------------
    When two users attempt to book the exact same slot simultaneously:
    1. We open a `transaction.atomic()` database transaction.
    2. We invoke `TimeSlot.objects.select_for_update().get(pk=slot_id)`.
       This puts an exclusive row lock on this particular slot in the DB.
    3. The first customer's thread obtains the lock and reads `is_booked == False`.
    4. The second customer's thread is blocked at `select_for_update()` until the first completes.
    5. The first customer marks `slot.is_booked = True` and commits.
    6. The second customer's thread now receives the row lock, inspects `is_booked`,
       finds it is now `True`, and receives the friendly error:
       "This slot was just taken. Please pick another one."
    7. In addition, Appointment.slot is a OneToOneField, which guarantees at the SQL level
       that duplicate appointments for the same slot will be aborted by the database.
    """
    if request.method != 'POST':
        return redirect('book_appointment')

    form = BookingSubmissionForm(request.POST)
    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field.capitalize()}: {error}")
        return redirect('book_appointment')

    service = form.cleaned_data['service']
    slot_id = form.cleaned_data['slot_id']
    notes = form.cleaned_data.get('notes', '').strip()

    try:
        with transaction.atomic():
            # Critical: Acquire row lock on the slot
            slot = TimeSlot.objects.select_for_update().get(pk=slot_id)

            # Check if someone else booked it right before us
            if slot.is_booked:
                messages.error(
                    request,
                    "This slot was just taken! Someone booked it moments ago. Please select an available slot."
                )
                return redirect('book_appointment')

            # Ensure slot is not in the past
            if slot.date < date.today():
                messages.error(request, "Cannot book a time slot in the past.")
                return redirect('book_appointment')

            # Mark slot as booked
            slot.is_booked = True
            slot.save(update_fields=['is_booked'])

            # Create the pending appointment
            appointment = Appointment.objects.create(
                customer=request.user,
                slot=slot,
                service=service,
                status=Appointment.STATUS_PENDING,
                notes=notes
            )

        # Trigger console email notification
        send_booking_created_email(appointment)

        messages.success(
            request,
            f"Your appointment for {service.name} on {slot.date} at {slot.start_time.strftime('%I:%M %p')} has been booked! "
            f"Status is currently PENDING approval from salon staff."
        )
        return redirect('my_bookings')

    except TimeSlot.DoesNotExist:
        messages.error(request, "The requested time slot does not exist.")
        return redirect('book_appointment')
    except Exception as e:
        messages.error(request, f"An unexpected error occurred while booking: {e}")
        return redirect('book_appointment')


@login_required
def my_bookings_view(request):
    """
    Displays all appointments belonging to the currently logged-in customer.
    Includes status badges and cancellation actions for pending/confirmed appointments.
    """
    appointments = Appointment.objects.filter(
        customer=request.user
    ).select_related('service', 'slot', 'slot__staff').order_by('-slot__date', '-slot__start_time')

    return render(request, 'booking/my_bookings.html', {
        'appointments': appointments,
    })


@login_required
def cancel_booking_view(request, pk):
    """
    Allows a customer to cancel their own appointment.
    Rules:
    - User must be the owner of the appointment (customer=request.user)
    - Appointment status must be 'pending' or 'confirmed'
    - Cancellation is executed atomically: marks appointment as 'cancelled' and frees the TimeSlot (is_booked=False)
    """
    appointment = get_object_or_404(
        Appointment.objects.select_related('slot', 'service', 'slot__staff'),
        pk=pk,
        customer=request.user
    )

    if not appointment.can_be_cancelled():
        messages.error(
            request,
            f"This appointment cannot be cancelled because its status is already '{appointment.get_status_display()}'."
        )
        return redirect('my_bookings')

    if request.method == 'POST':
        with transaction.atomic():
            # Lock the slot to avoid races when freeing it
            slot = TimeSlot.objects.select_for_update().get(pk=appointment.slot_id)
            slot.is_booked = False
            slot.save(update_fields=['is_booked'])

            appointment.status = Appointment.STATUS_CANCELLED
            appointment.save(update_fields=['status'])

        # Send cancellation email to customer and staff
        send_booking_cancelled_email(appointment, cancelled_by=request.user.get_full_name() or request.user.username)

        messages.success(request, f"Appointment #{appointment.pk} for {appointment.service.name} has been cancelled.")
        return redirect('my_bookings')

    return render(request, 'booking/cancel_confirm.html', {
        'appointment': appointment,
    })


# ==========================================
# Staff Views
# ==========================================

@staff_required
def staff_dashboard_view(request):
    """
    Staff dashboard:
    - Today's date and scheduled appointments
    - Pending approval counter
    - Breakdown of confirmed, completed, and cancelled appointments
    - Quick shortcut links to slot generation and appointment management
    """
    today = date.today()

    today_appointments = Appointment.objects.filter(
        slot__date=today
    ).select_related('customer', 'service', 'slot', 'slot__staff').order_by('slot__start_time')

    pending_count = Appointment.objects.filter(status=Appointment.STATUS_PENDING).count()
    confirmed_count = Appointment.objects.filter(status=Appointment.STATUS_CONFIRMED).count()
    completed_count = Appointment.objects.filter(status=Appointment.STATUS_COMPLETED).count()
    cancelled_count = Appointment.objects.filter(status=Appointment.STATUS_CANCELLED).count()

    recent_pending = Appointment.objects.filter(
        status=Appointment.STATUS_PENDING
    ).select_related('customer', 'service', 'slot', 'slot__staff').order_by('created_at')[:5]

    total_slots_count = TimeSlot.objects.filter(date__gte=today).count()
    free_slots_count = TimeSlot.objects.filter(date__gte=today, is_booked=False).count()

    return render(request, 'booking/staff/dashboard.html', {
        'today': today,
        'today_appointments': today_appointments,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
        'recent_pending': recent_pending,
        'total_slots_count': total_slots_count,
        'free_slots_count': free_slots_count,
    })


@staff_required
def staff_slots_view(request):
    """
    Staff view for bulk generation of non-overlapping time slots.
    Input parameters: staff user, target date, shift start, shift end, slot duration.
    Generates non-overlapping slots, handles duplicates gracefully, and displays existing slots for that date.
    """
    target_date_str = request.GET.get('date', date.today().isoformat())
    try:
        selected_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = date.today()

    if request.method == 'POST':
        form = SlotBulkCreateForm(request.POST)
        if form.is_valid():
            staff_user = form.cleaned_data['staff']
            slot_date = form.cleaned_data['date']
            start_time = form.cleaned_data['start_time']
            end_time = form.cleaned_data['end_time']
            slot_minutes = int(form.cleaned_data['slot_length'])

            # Iteratively generate slots between start_time and end_time
            current_dt = datetime.combine(slot_date, start_time)
            end_dt = datetime.combine(slot_date, end_time)
            step = timedelta(minutes=slot_minutes)

            created_count = 0
            skipped_count = 0

            while current_dt + step <= end_dt:
                slot_start = current_dt.time()
                slot_end = (current_dt + step).time()

                # Check if an overlapping slot exists for this staff member on this date
                overlap_exists = TimeSlot.objects.filter(
                    staff=staff_user,
                    date=slot_date,
                    start_time__lt=slot_end,
                    end_time__gt=slot_start
                ).exists()

                if overlap_exists:
                    skipped_count += 1
                else:
                    try:
                        TimeSlot.objects.create(
                            staff=staff_user,
                            date=slot_date,
                            start_time=slot_start,
                            end_time=slot_end,
                            is_booked=False
                        )
                        created_count += 1
                    except Exception:
                        skipped_count += 1

                current_dt += step

            if created_count > 0:
                messages.success(
                    request,
                    f"Successfully generated {created_count} time slot(s) for {staff_user.get_full_name() or staff_user.username} on {slot_date}."
                )
            if skipped_count > 0:
                messages.warning(
                    request,
                    f"Skipped {skipped_count} slot(s) due to existing overlaps or duplicates."
                )

            return redirect(f"{request.path}?date={slot_date.isoformat()}")
    else:
        # Pre-select logged-in user if they are staff
        initial_data = {
            'date': selected_date,
            'start_time': time(9, 0),
            'end_time': time(17, 0),
            'slot_length': 30,
        }
        if request.user.groups.filter(name=STAFF_GROUP_NAME).exists():
            initial_data['staff'] = request.user
        form = SlotBulkCreateForm(initial=initial_data)

    # Fetch slots for current date to display in table
    existing_slots = TimeSlot.objects.filter(
        date=selected_date
    ).select_related('staff').order_by('staff', 'start_time')

    return render(request, 'booking/staff/slots.html', {
        'form': form,
        'selected_date': selected_date,
        'existing_slots': existing_slots,
    })


@staff_required
def staff_delete_slot_view(request, pk):
    """
    Allows staff to delete an unbooked time slot.
    Booked slots cannot be deleted directly (their appointment must be cancelled/rescheduled first).
    """
    slot = get_object_or_404(TimeSlot, pk=pk)
    if slot.is_booked:
        messages.error(request, "Cannot delete a booked time slot. Please cancel or reschedule the appointment first.")
        return redirect(f"/staff/slots/?date={slot.date.isoformat()}")

    slot_date = slot.date
    slot.delete()
    messages.success(request, "Time slot deleted successfully.")
    return redirect(f"/staff/slots/?date={slot_date.isoformat()}")


@staff_required
def staff_appointments_view(request):
    """
    Staff appointment management page.
    Filters:
    - Status (all, pending, confirmed, completed, cancelled)
    - Date (today, upcoming, past, all)
    Actions:
    - Approve (pending -> confirmed)
    - Cancel (frees the slot, sends notification)
    - Mark Completed (confirmed -> completed)
    - Reschedule (reassigns to a different free slot)
    """
    status_filter = request.GET.get('status', 'all')
    date_filter = request.GET.get('date', 'all')

    qs = Appointment.objects.select_related('customer', 'service', 'slot', 'slot__staff').order_by('-slot__date', '-slot__start_time')

    # Apply status filter
    if status_filter in [Appointment.STATUS_PENDING, Appointment.STATUS_CONFIRMED, Appointment.STATUS_COMPLETED, Appointment.STATUS_CANCELLED]:
        qs = qs.filter(status=status_filter)

    # Apply date filter
    today = date.today()
    if date_filter == 'today':
        qs = qs.filter(slot__date=today)
    elif date_filter == 'upcoming':
        qs = qs.filter(slot__date__gte=today)
    elif date_filter == 'past':
        qs = qs.filter(slot__date__lt=today)

    return render(request, 'booking/staff/appointments.html', {
        'appointments': qs,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'today': today,
    })


@staff_required
def staff_approve_appointment_view(request, pk):
    """
    Staff action: approve an appointment (pending -> confirmed).
    Sends confirmation email.
    """
    if request.method != 'POST':
        return redirect('staff_appointments')

    appointment = get_object_or_404(Appointment, pk=pk)
    if appointment.status != Appointment.STATUS_PENDING:
        messages.warning(request, f"Appointment is already {appointment.get_status_display()}.")
        return redirect('staff_appointments')

    appointment.status = Appointment.STATUS_CONFIRMED
    appointment.save(update_fields=['status'])

    send_booking_confirmed_email(appointment)
    messages.success(request, f"Appointment #{appointment.pk} for {appointment.customer.username} has been CONFIRMED.")
    return redirect('staff_appointments')


@staff_required
def staff_cancel_appointment_view(request, pk):
    """
    Staff action: cancel an appointment.
    Frees the associated time slot and sends cancellation email.
    """
    if request.method != 'POST':
        return redirect('staff_appointments')

    appointment = get_object_or_404(Appointment, pk=pk)
    if appointment.status == Appointment.STATUS_CANCELLED:
        messages.info(request, "This appointment is already cancelled.")
        return redirect('staff_appointments')

    with transaction.atomic():
        # Free the slot
        slot = TimeSlot.objects.select_for_update().get(pk=appointment.slot_id)
        slot.is_booked = False
        slot.save(update_fields=['is_booked'])

        appointment.status = Appointment.STATUS_CANCELLED
        appointment.save(update_fields=['status'])

    send_booking_cancelled_email(appointment, cancelled_by=f"Staff ({request.user.get_full_name() or request.user.username})")
    messages.success(request, f"Appointment #{appointment.pk} has been CANCELLED and the time slot is now available.")
    return redirect('staff_appointments')


@staff_required
def staff_complete_appointment_view(request, pk):
    """
    Staff action: mark an appointment as completed.
    """
    if request.method != 'POST':
        return redirect('staff_appointments')

    appointment = get_object_or_404(Appointment, pk=pk)
    appointment.status = Appointment.STATUS_COMPLETED
    appointment.save(update_fields=['status'])
    messages.success(request, f"Appointment #{appointment.pk} marked as COMPLETED.")
    return redirect('staff_appointments')


@staff_required
def staff_reschedule_appointment_view(request, pk):
    """
    Staff action: Reschedule an appointment to a different free time slot.
    Atomically:
    1. Unlocks & frees the old slot (is_booked=False).
    2. Locks & reserves the new slot (is_booked=True).
    3. Reassigns appointment.slot = new_slot.
    4. Sends reschedule email to customer.
    """
    appointment = get_object_or_404(
        Appointment.objects.select_related('slot', 'service', 'customer', 'slot__staff'),
        pk=pk
    )

    if request.method == 'POST':
        form = AppointmentRescheduleForm(request.POST, current_slot=appointment.slot)
        if form.is_valid():
            new_slot_selected = form.cleaned_data['new_slot']

            try:
                with transaction.atomic():
                    # 1. Lock both slots to guarantee no race conditions
                    old_slot = TimeSlot.objects.select_for_update().get(pk=appointment.slot_id)
                    new_slot = TimeSlot.objects.select_for_update().get(pk=new_slot_selected.pk)

                    if new_slot.is_booked:
                        messages.error(request, "The selected slot was booked by someone else in the meantime.")
                        return redirect('staff_reschedule_appointment', pk=pk)

                    # 2. Release old slot
                    old_slot.is_booked = False
                    old_slot.save(update_fields=['is_booked'])

                    # 3. Claim new slot
                    new_slot.is_booked = True
                    new_slot.save(update_fields=['is_booked'])

                    # 4. Reassign appointment
                    saved_old_slot = old_slot
                    appointment.slot = new_slot
                    appointment.save(update_fields=['slot'])

                # 5. Send notification
                send_appointment_rescheduled_email(appointment, old_slot=saved_old_slot)

                messages.success(
                    request,
                    f"Appointment #{appointment.pk} successfully rescheduled to {new_slot.date} at {new_slot.start_time.strftime('%I:%M %p')}!"
                )
                return redirect('staff_appointments')

            except Exception as e:
                messages.error(request, f"Failed to reschedule: {e}")
                return redirect('staff_reschedule_appointment', pk=pk)
    else:
        form = AppointmentRescheduleForm(current_slot=appointment.slot)

    return render(request, 'booking/staff/reschedule.html', {
        'form': form,
        'appointment': appointment,
    })
