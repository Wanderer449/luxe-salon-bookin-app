"""
URL Configuration for the booking application.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Public views
    path('', views.home_view, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('role-redirect/', views.role_redirect_view, name='role_redirect'),

    # Customer views
    path('services/', views.services_view, name='services'),
    path('book/', views.book_appointment_view, name='book_appointment'),
    path('book/confirm/', views.booking_confirm_view, name='booking_confirm'),
    path('my-bookings/', views.my_bookings_view, name='my_bookings'),
    path('bookings/', views.my_bookings_view, name='bookings_alias'),  # Alias per spec
    path('my-bookings/<int:pk>/cancel/', views.cancel_booking_view, name='cancel_booking'),
    path('api/slots/', views.api_slots_view, name='api_slots'),

    # Staff views
    path('staff/', views.staff_dashboard_view, name='staff_dashboard'),
    path('staff/slots/', views.staff_slots_view, name='staff_slots'),
    path('staff/slots/<int:pk>/delete/', views.staff_delete_slot_view, name='staff_delete_slot'),
    path('staff/appointments/', views.staff_appointments_view, name='staff_appointments'),
    path('staff/appointments/<int:pk>/approve/', views.staff_approve_appointment_view, name='staff_approve_appointment'),
    path('staff/appointments/<int:pk>/cancel/', views.staff_cancel_appointment_view, name='staff_cancel_appointment'),
    path('staff/appointments/<int:pk>/complete/', views.staff_complete_appointment_view, name='staff_complete_appointment'),
    path('staff/appointments/<int:pk>/reschedule/', views.staff_reschedule_appointment_view, name='staff_reschedule_appointment'),
]
