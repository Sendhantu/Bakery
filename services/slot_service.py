from datetime import date, datetime, time, timedelta

from exceptions import ValidationError


class SlotService:
    def __init__(self, time_slots=None, pickup_buffer_minutes=20):
        self.time_slots = list(time_slots or [])
        self.pickup_buffer_minutes = max(0, int(pickup_buffer_minutes or 0))

    def get_available_slots(self, target_date, now=None):
        current_time = now or datetime.utcnow()
        normalized_date = self._normalize_date(target_date)
        if normalized_date > current_time.date():
            return list(self.time_slots)

        earliest_allowed = current_time + timedelta(minutes=self.pickup_buffer_minutes)
        available = []
        for slot in self.time_slots:
            start_time, _ = self._parse_slot(slot)
            slot_start = datetime.combine(normalized_date, start_time)
            if slot_start >= earliest_allowed:
                available.append(slot)
        return available

    def validate_delivery_selection(self, target_date, selected_slot, now=None):
        current_time = now or datetime.utcnow()
        normalized_date = self._normalize_date(target_date)
        selected_slot = (selected_slot or "").strip()

        if normalized_date < (current_time.date() + timedelta(days=1)):
            raise ValidationError("Please choose a delivery date from tomorrow onward.")
        if selected_slot not in self.time_slots:
            raise ValidationError("Please choose a valid delivery time slot.")
        return selected_slot

    def validate_pickup_selection(self, target_date, selected_slot="", custom_time="", now=None):
        current_time = now or datetime.utcnow()
        normalized_date = self._normalize_date(target_date)
        selected_slot = (selected_slot or "").strip()
        custom_time = (custom_time or "").strip()

        if normalized_date < current_time.date():
            raise ValidationError("Please choose a valid pickup date.")

        if custom_time:
            pickup_moment = self._combine_custom_time(normalized_date, custom_time)
            earliest_allowed = current_time + timedelta(minutes=self.pickup_buffer_minutes)
            if pickup_moment < earliest_allowed:
                raise ValidationError(
                    f"Pickup needs at least {self.pickup_buffer_minutes} minutes of preparation time."
                )
            self._ensure_within_business_hours(pickup_moment.time())
            return pickup_moment.strftime("Pickup at %I:%M %p")

        available_slots = self.get_available_slots(normalized_date, now=current_time)
        if selected_slot not in available_slots:
            if normalized_date == current_time.date():
                raise ValidationError("Please choose a future pickup slot or a custom pickup time.")
            raise ValidationError("Please choose a valid pickup slot.")
        return selected_slot

    def scheduled_datetime_for_selection(self, target_date, selected_slot="", custom_time=""):
        normalized_date = self._normalize_date(target_date)
        custom_time = (custom_time or "").strip()
        if custom_time:
            return self._combine_custom_time(normalized_date, custom_time)
        start_time, _ = self._parse_slot(selected_slot)
        return datetime.combine(normalized_date, start_time)

    def business_hours_range(self):
        if not self.time_slots:
            return time(9, 0), time(21, 0)
        first_start, _ = self._parse_slot(self.time_slots[0])
        _, last_end = self._parse_slot(self.time_slots[-1])
        return first_start, last_end

    def _ensure_within_business_hours(self, selected_time):
        opening_time, closing_time = self.business_hours_range()
        if selected_time < opening_time or selected_time > closing_time:
            raise ValidationError(
                f"Pickup time must be between {opening_time.strftime('%I:%M %p')} and {closing_time.strftime('%I:%M %p')}."
            )

    def _combine_custom_time(self, target_date, custom_time):
        try:
            parsed_time = datetime.strptime(custom_time, "%H:%M").time()
        except ValueError as exc:
            raise ValidationError("Please choose a valid custom pickup time.") from exc
        return datetime.combine(target_date, parsed_time)

    def _normalize_date(self, target_date):
        if isinstance(target_date, datetime):
            return target_date.date()
        if isinstance(target_date, date):
            return target_date
        raise ValidationError("Please choose a valid order date.")

    def _parse_slot(self, slot_label):
        parts = [(part or "").strip() for part in str(slot_label or "").split("-")]
        if len(parts) != 2:
            raise ValidationError("Please choose a valid time slot.")
        return self._parse_clock(parts[0]), self._parse_clock(parts[1])

    def _parse_clock(self, value):
        try:
            return datetime.strptime(value, "%H:%M").time()
        except ValueError as exc:
            raise ValidationError("Please choose a valid time slot.") from exc
