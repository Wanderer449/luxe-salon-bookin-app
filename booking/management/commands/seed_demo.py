"""
Management command to seed demo data for the salon booking application.

Creates:
1. Groups: 'Staff' and 'Customer'
2. 1 Staff user: staff1 (password: staff123)
3. 2 Customer users: user1, user2 (password: test123)
4. 4 Salon services: Haircut (30m), Beard Trim (15m), Facial (45m), Hair Color (60m)
5. Time slots for the next 7 days for staff1
6. Initial sample appointments (Pending, Confirmed, Completed) for testing dashboards
"""

from datetime import date, time, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from booking.models import Service, TimeSlot, Appointment
from booking.utils import STAFF_GROUP_NAME, CUSTOMER_GROUP_NAME


class Command(BaseCommand):
    help = "Seeds demo data: 1 staff user, 2 customers, 4 services, and slots for 7 days"

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("--- Starting Salon Demo Data Seeding ---"))

        # 1. Ensure Groups Exist
        staff_group, _ = Group.objects.get_or_create(name=STAFF_GROUP_NAME)
        customer_group, _ = Group.objects.get_or_create(name=CUSTOMER_GROUP_NAME)
        self.stdout.write(self.style.SUCCESS(f"Groups verified: '{STAFF_GROUP_NAME}' and '{CUSTOMER_GROUP_NAME}'"))

        # 2. Create Staff User: staff1 / staff123
        staff_user, created = User.objects.get_or_create(
            username='staff1',
            defaults={
                'email': 'staff1@salondemo.local',
                'first_name': 'Elena',
                'last_name': 'Vance',
                'is_staff': True,
            }
        )
        staff_user.set_password('staff123')
        staff_user.is_staff = True
        staff_user.save()
        staff_user.groups.add(staff_group)
        self.stdout.write(self.style.SUCCESS("Staff user 'staff1' (password: staff123) ready."))

        # 3. Create Customers: user1, user2 / test123
        user1, created = User.objects.get_or_create(
            username='user1',
            defaults={
                'email': 'user1@example.com',
                'first_name': 'Alex',
                'last_name': 'Taylor',
            }
        )
        user1.set_password('test123')
        user1.save()
        user1.groups.add(customer_group)
        self.stdout.write(self.style.SUCCESS("Customer 'user1' (password: test123) ready."))

        user2, created = User.objects.get_or_create(
            username='user2',
            defaults={
                'email': 'user2@example.com',
                'first_name': 'Jordan',
                'last_name': 'Lee',
            }
        )
        user2.set_password('test123')
        user2.save()
        user2.groups.add(customer_group)
        self.stdout.write(self.style.SUCCESS("Customer 'user2' (password: test123) ready."))

        # 4. Create 4 Salon Services
        services_data = [
            {
                'name': 'Classic Precision Haircut',
                'duration_minutes': 30,
                'price': 35.00,
                'is_active': True,
            },
            {
                'name': 'Beard Sculpting & Hot Towel Trim',
                'duration_minutes': 15,
                'price': 20.00,
                'is_active': True,
            },
            {
                'name': 'Revitalizing Facial & Scalp Massage',
                'duration_minutes': 45,
                'price': 55.00,
                'is_active': True,
            },
            {
                'name': 'Full Hair Color & Gloss Treatment',
                'duration_minutes': 60,
                'price': 85.00,
                'is_active': True,
            },
        ]

        created_services = []
        for s_data in services_data:
            service, _ = Service.objects.update_or_create(
                name=s_data['name'],
                defaults=s_data
            )
            created_services.append(service)
        self.stdout.write(self.style.SUCCESS(f"Created/updated {len(created_services)} salon services."))

        # 5. Create Time Slots for Next 7 Days (Today through Today + 6)
        today = date.today()
        # Daily schedule times: 9:00 AM to 5:00 PM in 30-minute blocks (lunch break 12:00-13:00)
        slot_hours = [
            (time(9, 0), time(9, 30)),
            (time(9, 30), time(10, 0)),
            (time(10, 0), time(10, 30)),
            (time(10, 30), time(11, 0)),
            (time(11, 0), time(11, 30)),
            (time(11, 30), time(12, 0)),
            # Afternoon
            (time(13, 0), time(13, 30)),
            (time(13, 30), time(14, 0)),
            (time(14, 0), time(14, 30)),
            (time(14, 30), time(15, 0)),
            (time(15, 0), time(15, 30)),
            (time(15, 30), time(16, 0)),
            (time(16, 0), time(16, 30)),
            (time(16, 30), time(17, 0)),
        ]

        total_slots_created = 0
        for day_offset in range(7):
            target_date = today + timedelta(days=day_offset)
            for start_t, end_t in slot_hours:
                # Check if slot already exists to prevent duplication
                slot, created = TimeSlot.objects.get_or_create(
                    staff=staff_user,
                    date=target_date,
                    start_time=start_t,
                    defaults={
                        'end_time': end_t,
                        'is_booked': False,
                    }
                )
                if created:
                    total_slots_created += 1

        self.stdout.write(self.style.SUCCESS(f"Generated {total_slots_created} new time slots across 7 days."))

        # 6. Create Initial Demo Appointments for Realistic Experience
        # Demo Appointment 1: Tomorrow 10:00 AM for user1 (Confirmed)
        tomorrow = today + timedelta(days=1)
        slot_tomorrow_10am = TimeSlot.objects.filter(
            staff=staff_user, date=tomorrow, start_time=time(10, 0)
        ).first()
        if slot_tomorrow_10am and not hasattr(slot_tomorrow_10am, 'appointment'):
            slot_tomorrow_10am.is_booked = True
            slot_tomorrow_10am.save()
            Appointment.objects.create(
                customer=user1,
                slot=slot_tomorrow_10am,
                service=created_services[0],  # Haircut
                status=Appointment.STATUS_CONFIRMED,
                notes="Looking forward to styling my hair before the weekend event."
            )
            self.stdout.write(self.style.SUCCESS("Demo appointment created: user1 Confirmed for tomorrow at 10:00 AM."))

        # Demo Appointment 2: Tomorrow 2:00 PM for user2 (Pending approval)
        slot_tomorrow_2pm = TimeSlot.objects.filter(
            staff=staff_user, date=tomorrow, start_time=time(14, 0)
        ).first()
        if slot_tomorrow_2pm and not hasattr(slot_tomorrow_2pm, 'appointment'):
            slot_tomorrow_2pm.is_booked = True
            slot_tomorrow_2pm.save()
            Appointment.objects.create(
                customer=user2,
                slot=slot_tomorrow_2pm,
                service=created_services[1],  # Beard Trim
                status=Appointment.STATUS_PENDING,
                notes="First time visiting, please trim beard neatly."
            )
            self.stdout.write(self.style.SUCCESS("Demo appointment created: user2 Pending for tomorrow at 2:00 PM."))

        # Demo Appointment 3: Today 9:00 AM for user1 (Pending or Confirmed)
        slot_today_9am = TimeSlot.objects.filter(
            staff=staff_user, date=today, start_time=time(9, 0)
        ).first()
        if slot_today_9am and not hasattr(slot_today_9am, 'appointment'):
            slot_today_9am.is_booked = True
            slot_today_9am.save()
            Appointment.objects.create(
                customer=user1,
                slot=slot_today_9am,
                service=created_services[2],  # Facial
                status=Appointment.STATUS_CONFIRMED,
                notes="Morning refresh session."
            )
            self.stdout.write(self.style.SUCCESS("Demo appointment created: user1 Confirmed for today at 9:00 AM."))

        self.stdout.write(self.style.SUCCESS("\nDemo data seeding completed successfully!"))
        self.stdout.write("Credentials:")
        self.stdout.write(" - Staff: staff1 / staff123")
        self.stdout.write(" - Customer 1: user1 / test123")
        self.stdout.write(" - Customer 2: user2 / test123")
