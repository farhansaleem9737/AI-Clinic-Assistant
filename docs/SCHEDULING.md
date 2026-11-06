# Hybrid scheduling, tokens and the day's queue (D117)

## Doctor policy

Each doctor may save a scheduling policy (My Schedule › Scheduling settings). Only the
doctor changes their own; an administrator (`schedule:manage_any` + `settings:manage`)
may change anyone's. Receptionists can read it. Every change is audited
(`doctor.scheduling_policy_changed`, before and after).

| Setting | Default | Range |
|---|---|---|
| Mode | hybrid | scheduled · fifo · hybrid |
| Consultation length | 15 min | 5–240 (10, 15, 20, 30, 45, 60 or custom) |
| Buffer between patients | 0 min | 0–120 |
| Accept walk-ins | yes | — |
| Walk-in tokens per day | no limit | 1–500 |
| Late-arrival grace | 10 min | 0–120 |
| Double-booking limit (extra patients per time) | 1 | 0–5 |
| Front desk may override | yes | — |

**Legacy duration policy.** A doctor with no saved policy keeps the old behaviour: free
times use each weekly template's own `slot_minutes`. Nothing is converted automatically:
saving a policy changes only how *future* free times are offered. Existing appointments
always keep their own start and end times (a 60-minute booking stays 60 minutes). The
migration creates no policy rows, so production availability is unchanged on deploy.

## Free times

`availability_service.working_slots` cuts each working window (weekly hours, custom
hours, extra availability, minus leave/holidays/blocks) into appointments of the
consultation length, one every *length + buffer* minutes:

- 15 min, no buffer, 11:00–12:00 → 11:00, 11:15, 11:30, 11:45
- 20 min → 11:00, 11:20, 11:40
- 15 min + 5 min buffer → 11:00, 11:20, 11:40

A slot is free when no active appointment overlaps it (any length, any start). The
booking wizard shows Date → Hour → Time; taken times are shown disabled. FastAPI is the
authority: the chosen time is checked again when the booking is made.

## Booking safety and overbooking

Ordinary bookings keep every existing guard: advisory locks per doctor and patient, a
re-check of the slot, the Idempotency-Key, and the database `EXCLUDE` constraint.

Authorized double booking uses **capacity lanes**. `appointments.capacity_lane` is 0 for
every ordinary booking; the doctor-overlap constraint is now
`EXCLUDE (doctor_id =, capacity_lane =, time range &&)`. A double booking takes the lowest
free lane 1..`max_overbook`, so the doctor's limit is enforced by the database too and each
lane remains overlap-free. The patient-overlap constraint is unchanged.

Staff overrides (`appointment:override`, granted to receptionists and administrators):

- **custom time**: any 5-minute start inside the doctor's working hours;
- **custom length**: 5–240 minutes;
- **double booking**: only into a taken time, only with a reason, within the limit, and
  only if the doctor allows front-desk overrides (administrators always may).

The UI shows a warning, requires the reason and an explicit confirmation. Every override is
audited (`appointment.override_booked`) and the appointment shows as a capacity exception.
Patients and the assistant can never use overrides.

## The queue

Per doctor and local date. A booked patient gets a token when they check in (the
appointment's `checked_in` transition); a walk-in gets one when the front desk registers
them, or when a patient asks for one (state `registered` until reception checks them in).

**Tokens** come from `queue_token_counters` with a single
`INSERT … ON CONFLICT DO UPDATE … RETURNING`: concurrent check-ins never share a number,
and a token never changes. The **position** is computed on every read.

**Order** (one coordinator, `queue_service.order`):

0. patients staff moved up (audited), in the order that was done;
1. checked-in booked patients whose reserved time has come, by that time;
2. everyone else: booked patients by reserved time, walk-ins by check-in time (FIFO);
3. deferred patients, until their deferral ends.

Ties: the token number.

**Call next** takes the first of that order, with one rule for walk-ins: a walk-in is called
only if a consultation fits before the next reserved time; otherwise a booked patient who is
already here goes first; if none is here, the walk-in is called and the result says it may
delay the booked patient.

**Never automatic.** Nobody is marked absent or a no-show by the system. Late patients are
flagged (after the doctor's grace) and stay listed. Staff mark *absent* (they can check in
again and rejoin by their new check-in time) or *no-show*.

The database allows one *called* patient and one *consultation in progress* per doctor
(partial unique indexes); starting a second consultation fails with 409.

Waits are shown as a range (about 0.75–1.5 × consultation length per patient ahead, never
earlier than a booked time), and always labelled as an estimate.

Patients see only their own tokens (`GET /queue/me`): no other patient's details.

## API

| Method | Path | Who |
|---|---|---|
| GET / PUT | `/doctors/{id}/scheduling-policy` | read: staff, the doctor · write: the doctor, admin |
| GET | `/queue/sessions?date=` | front desk |
| GET | `/queue/doctors/{id}?date=` | front desk, the doctor |
| POST | `/queue/doctors/{id}/call-next` | front desk, the doctor |
| POST | `/queue/walk-ins` | front desk (checked in now), patient (own token) |
| POST | `/queue/entries/{id}/check-in` | front desk |
| POST | `/queue/entries/{id}/call · defer · prioritize · absent · no-show` | front desk, the doctor |
| POST | `/queue/entries/{id}/start · complete` | the doctor |
| POST | `/queue/entries/{id}/cancel` | front desk, the patient (own walk-in token) |
| GET | `/queue/me` | patient |

All queue changes are audited (`queue.*`). No Redis or WebSockets: screens refresh every
30 s (staff) or 60 s (patients).

## Automatic token booking (D120)

Booking a time has two ways in, sharing one engine and one transaction:

- **Automatic token (default).** The patient (or the front desk, for a patient) picks a
  doctor and a date; `GET /appointments/next-available?doctor_id=&date=[&patient_id=]`
  returns the earliest free time that day from `availability_service.slot_board` (working
  hours, breaks, custom hours, leave/blocks, existing bookings, notice, horizon, the
  doctor's length), skipping times the patient is already booked. It is computed from the
  real free intervals, never "bookings + 1", so cancelled, moved and custom-time bookings
  are all accounted for. Nothing is reserved. The user reviews and confirms; the booking
  (`POST /appointments/` with `booking_mode: "auto"`) re-checks the time under the usual
  locks and constraint. If the time went meanwhile the answer is `409 SLOT_UNAVAILABLE`
  with `details.next_available`, shown for review: another time is never booked silently.
  A full date returns `slot: null` and `next_date`.
- **Custom time.** The same day's free times, picked by the user (`booking_mode: "custom"`).

`appointments.booking_mode` records `auto`, `custom` or `override` (staff); older rows are
NULL (not guessed).

**Numbers.** Three different things, never confused:

| | What | Changes? |
|---|---|---|
| Reference | `APT-` + the end of the appointment id | never |
| Queue no. | the n-th active appointment of the doctor's local day by time (ties: booking order) | yes: moves up when an earlier booking is cancelled or moved; computed on read, never stored |
| Token | issued at check-in from the day's counter (D117) | never |

So a custom booking made before an existing automatic one simply takes the earlier place,
and nobody's reference or token is renumbered.

**Appointment duration.** The doctor's settings offer 15, 20 or 30 minutes (a length saved
earlier stays selectable). `POST /doctors/{id}/scheduling-policy/preview` shows the real
times of a date for a proposed length and buffer, with booked/free counts and the upcoming
bookings that would not fit. Saving a new length or buffer while such bookings exist is
refused (`409 SCHEDULE_CONFLICTS`, listing them) unless the request says
`keep_existing_appointments: true`; they then keep their booked times and lengths. Nothing is
moved or cancelled by a settings change.

The assistant books the same way: `propose_booking` with `earliest_on=<date>` gets the
server's earliest time and queue no. (the model never chooses a time or a number), the user
confirms, and the reply quotes the saved appointment.

Demo data: `python -m scripts.seed_demo` gives fictional demo doctors without a policy a
15-minute hybrid policy (09:00-17:00 = 32 times). Real doctors are never changed.

Migration `e3b7c1d9f240` adds the nullable `booking_mode` column and its check;
`alembic downgrade d5e9a3c7b418` removes them (bookings are untouched).

## Migration and rollback

Migration `c8d1f4a7e352` is additive: new tables, two nullable/defaulted appointment
columns, the overlap constraint rebuilt with the lane (every existing row is lane 0, so
it means the same), and the `appointment:override` permission.

Rollback: `alembic downgrade a9c4e2f7b310` (after downgrading any later revision). It
refuses while an active double booking exists (it would break the restored constraint);
cancel or move those first. Policies and queue data are dropped. Appointments are not
touched.
