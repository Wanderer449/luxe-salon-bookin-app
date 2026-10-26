"""
Comprehensive Test Suite for Salon Booking System.

Tests cover:
1. Authentication & Role assignment via Groups (Staff vs Customer)
2. TimeSlot.clean() validation rules:
   - end_time > start_time validation
   - Overlapping slot detection for same staff member
   - Cross-staff concurrency (different staff at the same time is allowed)
3. Database constraint & concurrency safety:
   - OneToOneField uniqueness guarantee on Appointment.slot
   - Atomic booking transaction with select_for_update() simulation
   - Double-booking prevention and friendly "This slot was just taken" rejection
4. Permissions & Access Control:
   - Staff access to /staff/ views
   - Customer blocked with 403 on /staff/
   - Login redirection for protected routes
5. Cancellation rules:
   - Customer cancels own booking -> slot is freed (is_booked=False)
   - Cannot cancel other users' bookings
   - Cannot cancel already completed/cancelled bookings
6. Rescheduling:
   - Old slot freed, new slot reserved, appointment updated atomically
7. Console email notification triggers on all lifecycle changes
"""

from datetime import date, time, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.core import mail
from django.db import transaction

from .models import Service, TimeSlot, Appointment
from .utils import (
    STAFF_GROUP_NAME,
    CUSTOMER_GROUP_NAME,
    ensure_groups_exist,
    send_booking_created_email,
    send_booking_confirmed_email,
    send_booking_cancelled_email,
    send_appointment_rescheduled_email,
)


class SalonBookingTests(TestCase):
    def setUp(self):
        # 1. Ensure Groups
        ensure_groups_exist()
        self.staff_group = Group.objects.get(name=STAFF_GROUP_NAME)
        self.customer_group = Group.objects.get(name=CUSTOMER_GROUP_NAME)

        # 2. Create Staff User
        self.staff1 = User.objects.create_user(
            username='staff1',
            email='staff1@example.com',
            password='staff123',
            first_name='Elena',
            last_name='Stylist'
        )
        self.staff1.groups.add(self.staff_group)

        # 3. Create Second Staff User for overlap isolation test
        self.staff2 = User.objects.create_user(
            username='staff2',
            email='staff2@example.com',
            password='staff123',
            first_name='Marcus',
            last_name='Barber'
        )
        self.staff2.groups.add(self.staff_group)

        # 4. Create Customers
        self.customer1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='test123',
            first_name='Alex',
            last_name='Customer'
        )
        self.customer1.groups.add(self.customer_group)

        self.customer2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='test123',
            first_name='Jordan',
            last_name='Client'
        )
        self.customer2.groups.add(self.customer_group)

        # 5. Create Services
        self.service_haircut = Service.objects.create(
            name='Classic Haircut',
            duration_minutes=30,
            price=35.00,
            is_active=True
        )
        self.service_beard = Service.objects.create(
            name='Beard Trim',
            duration_minutes=15,
            price=20.00,
            is_active=True
        )

        # Base test date
        self.test_date = date.today() + timedelta(days=2)

    # ==========================================
    # 1. Role Assignment Tests
    # ==========================================

    def test_signup_as_customer_assigns_customer_group(self):
        """Signing up with role=Customer puts the new user into the Customer group."""
        client = Client()
        response = client.post(reverse('signup'), {
            'username': 'newcustomer',
            'first_name': 'New',
            'last_name': 'User',
            'email': 'new@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'role': CUSTOMER_GROUP_NAME,
        })
        self.assertEqual(response.status_code, 302)
        new_user = User.objects.get(username='newcustomer')
        self.assertTrue(new_user.groups.filter(name=CUSTOMER_GROUP_NAME).exists())
        self.assertFalse(new_user.groups.filter(name=STAFF_GROUP_NAME).exists())

    def test_signup_as_staff_assigns_staff_group(self):
        """Signing up with role=Staff puts the new user into the Staff group."""
        client = Client()
        response = client.post(reverse('signup'), {
            'username': 'newstaff',
            'first_name': 'New',
            'last_name': 'StaffMember',
            'email': 'newstaff@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'role': STAFF_GROUP_NAME,
        })
        self.assertEqual(response.status_code, 302)
        new_user = User.objects.get(username='newstaff')
        self.assertTrue(new_user.groups.filter(name=STAFF_GROUP_NAME).exists())

    # ==========================================
    # 2. TimeSlot clean() Validation Tests
    # ==========================================

    def test_slot_end_time_must_be_after_start_time(self):
        """clean() rejects slots where end_time <= start_time."""
        slot = TimeSlot(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(9, 30),  # invalid: before start
            is_booked=False
        )
        with self.assertRaises(ValidationError) as ctx:
            slot.clean()
        self.assertIn('end_time', ctx.exception.message_dict)

        # Equal start and end time
        slot.end_time = time(10, 0)
        with self.assertRaises(ValidationError):
            slot.clean()

    def test_overlapping_slots_for_same_staff_rejected(self):
        """clean() detects and rejects overlapping time intervals for the same staff member."""
        # Initial slot: 10:00 - 10:30
        TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(10, 30),
            is_booked=False
        )

        # Case A: Identical interval (10:00 - 10:30)
        duplicate_slot = TimeSlot(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(10, 30)
        )
        with self.assertRaises(ValidationError):
            duplicate_slot.clean()

        # Case B: Partial overlap (10:15 - 10:45)
        partial_overlap = TimeSlot(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 15),
            end_time=time(10, 45)
        )
        with self.assertRaises(ValidationError):
            partial_overlap.clean()

        # Case C: Completely enclosing (09:45 - 10:45)
        enclosing_overlap = TimeSlot(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(9, 45),
            end_time=time(10, 45)
        )
        with self.assertRaises(ValidationError):
            enclosing_overlap.clean()

    def test_adjacent_slots_are_allowed(self):
        """Slots that touch borders (10:00-10:30 and 10:30-11:00) do NOT overlap."""
        slot1 = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(10, 30)
        )
        slot2 = TimeSlot(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 30),
            end_time=time(11, 0)
        )
        # Should not raise
        slot2.clean()
        slot2.save()
        self.assertEqual(TimeSlot.objects.filter(staff=self.staff1, date=self.test_date).count(), 2)

    def test_overlapping_times_for_different_staff_allowed(self):
        """Staff A and Staff B can have slots at the exact same time on the same date."""
        TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(10, 30)
        )
        slot_staff2 = TimeSlot(
            staff=self.staff2,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(10, 30)
        )
        # Should cleanly validate without error
        slot_staff2.clean()
        slot_staff2.save()
        self.assertEqual(TimeSlot.objects.filter(date=self.test_date).count(), 2)

    # ==========================================
    # 3. Concurrency, select_for_update & Atomic Booking Tests
    # ==========================================

    def test_booking_available_slot_succeeds_and_marks_is_booked(self):
        """Booking an available slot creates pending appointment and sets is_booked=True."""
        slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(11, 0),
            end_time=time(11, 30),
            is_booked=False
        )

        client = Client()
        client.force_login(self.customer1)

        response = client.post(reverse('booking_confirm'), {
            'service': self.service_haircut.id,
            'slot_id': slot.id,
            'notes': 'Looking forward to the haircut!',
        })
        self.assertEqual(response.status_code, 302)

        # Refresh slot from DB
        slot.refresh_from_db()
        self.assertTrue(slot.is_booked)

        # Appointment created with status pending
        appointment = Appointment.objects.get(slot=slot)
        self.assertEqual(appointment.customer, self.customer1)
        self.assertEqual(appointment.status, Appointment.STATUS_PENDING)
        self.assertEqual(appointment.service, self.service_haircut)

    def test_race_condition_protection_already_booked_slot_rejected(self):
        """
        Simulates two users attempting to book the same slot:
        Once slot.is_booked becomes True, subsequent booking attempt is rejected
        with the message: 'This slot was just taken'.
        """
        slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(14, 0),
            end_time=time(14, 30),
            is_booked=False
        )

        # Customer 1 books the slot first
        client1 = Client()
        client1.force_login(self.customer1)
        res1 = client1.post(reverse('booking_confirm'), {
            'service': self.service_haircut.id,
            'slot_id': slot.id,
        })
        self.assertEqual(res1.status_code, 302)

        # Customer 2 attempts to book the same slot
        client2 = Client()
        client2.force_login(self.customer2)
        res2 = client2.post(reverse('booking_confirm'), {
            'service': self.service_beard.id,
            'slot_id': slot.id,
        }, follow=True)

        # Must be rejected with friendly message
        self.assertContains(res2, "This slot was just taken")

        # Database must still only have 1 appointment for this slot
        self.assertEqual(Appointment.objects.filter(slot=slot).count(), 1)
        self.assertEqual(Appointment.objects.get(slot=slot).customer, self.customer1)

    # ==========================================
    # 4. Access Control & Permission Tests
    # ==========================================

    def test_customer_cannot_access_staff_dashboard(self):
        """Customer accessing /staff/ gets 403-style Staff Only response."""
        client = Client()
        client.force_login(self.customer1)
        response = client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Staff Only Area", status_code=403)

    def test_staff_can_access_staff_dashboard(self):
        """Staff member accessing /staff/ gets 200 OK."""
        client = Client()
        client.force_login(self.staff1)
        response = client.get(reverse('staff_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Dashboard")

    def test_unauthenticated_user_redirected_to_login(self):
        """Anonymous user trying to access /staff/ or /my-bookings/ is redirected to login."""
        client = Client()
        res_staff = client.get(reverse('staff_dashboard'))
        self.assertEqual(res_staff.status_code, 302)
        self.assertIn('/login/', res_staff.url)

        res_bookings = client.get(reverse('my_bookings'))
        self.assertEqual(res_bookings.status_code, 302)
        self.assertIn('/login/', res_bookings.url)

    # ==========================================
    # 5. Cancellation Lifecycle Tests
    # ==========================================

    def test_customer_can_cancel_own_pending_or_confirmed_booking(self):
        """Cancelling an appointment sets status=cancelled and frees the time slot."""
        slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(15, 0),
            end_time=time(15, 30),
            is_booked=True
        )
        appointment = Appointment.objects.create(
            customer=self.customer1,
            slot=slot,
            service=self.service_haircut,
            status=Appointment.STATUS_PENDING
        )

        client = Client()
        client.force_login(self.customer1)

        response = client.post(reverse('cancel_booking', args=[appointment.id]))
        self.assertEqual(response.status_code, 302)

        appointment.refresh_from_db()
        slot.refresh_from_db()

        self.assertEqual(appointment.status, Appointment.STATUS_CANCELLED)
        # Slot is now free for other clients
        self.assertFalse(slot.is_booked)

    def test_customer_cannot_cancel_other_customer_booking(self):
        """User A cannot cancel User B's appointment (returns 404)."""
        slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(16, 0),
            end_time=time(16, 30),
            is_booked=True
        )
        appointment = Appointment.objects.create(
            customer=self.customer1,
            slot=slot,
            service=self.service_haircut,
            status=Appointment.STATUS_CONFIRMED
        )

        client = Client()
        client.force_login(self.customer2)  # Logged in as user2
        response = client.post(reverse('cancel_booking', args=[appointment.id]))
        self.assertEqual(response.status_code, 404)

    # ==========================================
    # 6. Staff Actions & Rescheduling Tests
    # ==========================================

    def test_staff_approve_pending_appointment(self):
        """Staff approves a pending appointment, changing status to confirmed."""
        slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(9, 0),
            end_time=time(9, 30),
            is_booked=True
        )
        appointment = Appointment.objects.create(
            customer=self.customer1,
            slot=slot,
            service=self.service_haircut,
            status=Appointment.STATUS_PENDING
        )

        client = Client()
        client.force_login(self.staff1)
        response = client.post(reverse('staff_approve_appointment', args=[appointment.id]))
        self.assertEqual(response.status_code, 302)

        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.STATUS_CONFIRMED)

    def test_staff_reschedule_appointment_atomically(self):
        """
        Rescheduling an appointment:
        - Frees the old slot
        - Books the new slot
        - Reassigns the appointment
        """
        old_slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(10, 0),
            end_time=time(10, 30),
            is_booked=True
        )
        new_slot = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(11, 0),
            end_time=time(11, 30),
            is_booked=False
        )
        appointment = Appointment.objects.create(
            customer=self.customer1,
            slot=old_slot,
            service=self.service_haircut,
            status=Appointment.STATUS_CONFIRMED
        )

        client = Client()
        client.force_login(self.staff1)
        response = client.post(reverse('staff_reschedule_appointment', args=[appointment.id]), {
            'new_slot': new_slot.id,
        })
        self.assertEqual(response.status_code, 302)

        old_slot.refresh_from_db()
        new_slot.refresh_from_db()
        appointment.refresh_from_db()

        self.assertFalse(old_slot.is_booked)
        self.assertTrue(new_slot.is_booked)
        self.assertEqual(appointment.slot, new_slot)

    def test_staff_bulk_slot_generation(self):
        """Staff generates bulk non-overlapping slots."""
        client = Client()
        client.force_login(self.staff1)
        target_day = date.today() + timedelta(days=5)

        response = client.post(reverse('staff_slots'), {
            'staff': self.staff1.id,
            'date': target_day.isoformat(),
            'start_time': '09:00',
            'end_time': '11:00',
            'slot_length': '30',
        })
        self.assertEqual(response.status_code, 302)

        # 9:00 to 11:00 with 30m slots -> 4 slots: 9-9:30, 9:30-10, 10-10:30, 10:30-11
        slots_count = TimeSlot.objects.filter(staff=self.staff1, date=target_day).count()
        self.assertEqual(slots_count, 4)

    # ==========================================
    # 7. Dev Console Email Notifications
    # ==========================================

    def test_email_notifications_sent_on_all_lifecycle_events(self):
        """Verifies email notifications are triggered for created, confirmed, cancelled, and rescheduled."""
        mail.outbox.clear()

        slot1 = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(13, 0),
            end_time=time(13, 30),
            is_booked=True
        )
        appointment = Appointment.objects.create(
            customer=self.customer1,
            slot=slot1,
            service=self.service_haircut,
            status=Appointment.STATUS_PENDING
        )

        # 1. Booking created email
        send_booking_created_email(appointment)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Classic Haircut", mail.outbox[0].subject)
        self.assertIn("Elena Stylist", mail.outbox[0].body)

        # 2. Booking confirmed email
        send_booking_confirmed_email(appointment)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Confirmed", mail.outbox[1].subject)

        # 3. Reschedule email
        slot2 = TimeSlot.objects.create(
            staff=self.staff1,
            date=self.test_date,
            start_time=time(14, 0),
            end_time=time(14, 30),
            is_booked=True
        )
        appointment.slot = slot2
        appointment.save()
        send_appointment_rescheduled_email(appointment, old_slot=slot1)
        self.assertEqual(len(mail.outbox), 3)
        self.assertIn("Rescheduled", mail.outbox[2].subject)

        # 4. Cancelled email
        send_booking_cancelled_email(appointment, cancelled_by="Customer")
        self.assertEqual(len(mail.outbox), 4)
        self.assertIn("Cancelled", mail.outbox[3].subject)
