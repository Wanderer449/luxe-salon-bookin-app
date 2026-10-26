/**
 * Vanilla JavaScript for Salon Booking System
 * Handles slot modal popup, live service selection updates, and auto-dismiss alerts.
 */

document.addEventListener('DOMContentLoaded', function () {
  // 1. Auto-dismiss flash messages after 6 seconds
  const alerts = document.querySelectorAll('.alert-dismissible');
  alerts.forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) {
        bsAlert.close();
      }
    }, 6000);
  });

  // 2. Interactive Booking Modal Population
  const bookingModal = document.getElementById('bookingModal');
  if (bookingModal) {
    bookingModal.addEventListener('show.bs.modal', function (event) {
      const triggerBtn = event.relatedTarget;
      if (!triggerBtn) return;

      const slotId = triggerBtn.getAttribute('data-slot-id');
      const slotDate = triggerBtn.getAttribute('data-slot-date');
      const slotTime = triggerBtn.getAttribute('data-slot-time');
      const staffName = triggerBtn.getAttribute('data-staff-name');

      // Populate hidden inputs and display labels
      const inputSlotId = document.getElementById('modalSlotId');
      if (inputSlotId) inputSlotId.value = slotId;

      const displayDate = document.getElementById('modalDisplayDate');
      if (displayDate) displayDate.textContent = slotDate;

      const displayTime = document.getElementById('modalDisplayTime');
      if (displayTime) displayTime.textContent = slotTime;

      const displayStaff = document.getElementById('modalDisplayStaff');
      if (displayStaff) displayStaff.textContent = staffName;

      // Sync service select dropdown with currently active chosen service
      const mainServiceSelect = document.getElementById('mainServiceSelect');
      const modalServiceSelect = document.getElementById('modalServiceSelect');
      if (mainServiceSelect && modalServiceSelect) {
        modalServiceSelect.value = mainServiceSelect.value;
      }
    });
  }

  // 3. Service dropdown change handler to update URL parameters smoothly
  const mainServiceSelect = document.getElementById('mainServiceSelect');
  if (mainServiceSelect) {
    mainServiceSelect.addEventListener('change', function () {
      const selectedId = this.value;
      const url = new URL(window.location.href);
      url.searchParams.set('service', selectedId);
      window.location.href = url.toString();
    });
  }
});
