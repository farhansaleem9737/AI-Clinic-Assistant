"""Seed fictional demo data for development: departments, doctors, working
hours, and enough bookings to show every availability state.

    cd backend
    python -m scripts.seed_demo

Safe to run repeatedly: anything that already exists (matched by department
name / doctor email) is left alone. Refuses to run when ENVIRONMENT=production.

Everyone created here is fictional. Emails use the reserved ``.example``
domain and cannot receive mail.

Doctor logins share one password: the SEED_PASSWORD environment variable if
set, otherwise a random one that is printed once at the end.
"""

import asyncio
import os
import secrets
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment, settings
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.db.database import AsyncSessionLocal, engine
from app.models.appointment import Appointment, AppointmentStatus, AppointmentStatusHistory
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate
from app.models.user import User
from app.services import rbac_service

DEPARTMENTS = {
    "Cardiology": "Heart and circulation.",
    "General Medicine": "Everyday care for adults.",
    "Dermatology": "Skin, hair and nails.",
    "Neurology": "Brain, spine and nerves.",
    "Pediatrics": "Care for infants, children and teenagers.",
    "Orthopedics": "Bones, joints and sports injuries.",
}

# Weekly working hours: weekdays (Monday = 0), start, end.
HOURS = {
    "full": (range(0, 5), time(9, 0), time(17, 0)),
    "mornings": (range(0, 6), time(9, 0), time(13, 0)),
    "evenings": (range(0, 4), time(14, 0), time(20, 0)),
}

# (name, department, specialization, years, fee, qualifications, room, schedule)
# schedule: a key of HOURS, "leave" (full hours but on leave for three weeks,
# so shown as Unavailable) or "busy" (one short clinic, fully booked).
DOCTORS = [
    ("James Lee", "General Medicine", "General Physician", 8, "120.00", "MBBS, MRCGP", "A-3", "full"),
    ("Emily Carter", "Dermatology", "Dermatologist", 6, "130.00", "MBBS, MD (Dermatology)", "C-1", "busy"),
    ("Michael Brown", "Neurology", "Neurologist", 12, "160.00", "MBBS, FCPS (Neurology)", "D-4", "full"),
    ("Ayesha Malik", "Pediatrics", "Pediatrician", 7, "110.00", "MBBS, FCPS (Pediatrics)", "E-2", "mornings"),
    ("Robert Wilson", "Orthopedics", "Orthopedic Surgeon", 15, "170.00", "MBBS, FRCS (Orth)", "F-1", "leave"),
    ("Hannah Fischer", "Cardiology", "Interventional Cardiologist", 11, "210.00", "MD, FACC", "B-14", "evenings"),
    ("Omar Siddiqui", "General Medicine", "Family Physician", 4, "90.00", "MBBS, MCPS", "A-5", "mornings"),
    ("Priya Nair", "Dermatology", "Cosmetic Dermatologist", 9, "180.00", "MBBS, DDVL", "C-3", "evenings"),
    ("Daniel Okafor", "Neurology", "Pediatric Neurologist", 14, "195.00", "MBBS, MRCP, FRCPCH", "D-6", "full"),
    ("Sofia Rossi", "Pediatrics", "Neonatologist", 10, "150.00", "MD, Fellowship in Neonatology", "E-5", "full"),
    ("Kenji Tanaka", "Orthopedics", "Sports Medicine Specialist", 5, "140.00", "MD, CAQSM", "F-3", "mornings"),
    ("Layla Hassan", "Cardiology", "Cardiologist", 18, "230.00", "MBBS, FCPS, FRCP", "B-16", "evenings"),
]

DEMO_PATIENTS = [
    ("Demo", "Patient", date(1988, 4, 12), "demo.patient@clinic-demo.example"),
    ("Sample", "Visitor", date(1975, 9, 30), "demo.visitor@clinic-demo.example"),
]


def _email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@clinic-demo.example"


async def _department(db: AsyncSession, name: str) -> Department:
    department = await db.scalar(select(Department).where(Department.name == name))
    if department is None:
        department = Department(name=name, description=DEPARTMENTS[name], timezone=settings.clinic_timezone)
        db.add(department)
        await db.flush()
        print(f"  + department {name}")
    return department


async def _demo_patient(db: AsyncSession, first: str, last: str, born: date, email: str, by: User) -> Patient:
    patient = await db.scalar(select(Patient).where(Patient.email == email))
    if patient is None:
        patient = Patient(first_name=first, last_name=last, date_of_birth=born, email=email, registered_by_user_id=by.id)
        db.add(patient)
        await db.flush()
    return patient


def _weekly_hours(db: AsyncSession, doctor: Doctor, schedule: str, today: date) -> None:
    weekdays, start, end = HOURS[schedule]
    for weekday in weekdays:
        db.add(ScheduleTemplate(doctor_id=doctor.id, weekday=weekday, start_time=start, end_time=end,
                                slot_minutes=30, valid_from=today))


async def _fully_booked_clinic(db: AsyncSession, doctor: Doctor, tz: ZoneInfo, today: date, by: User) -> None:
    """One hour of clinic two days from now, with both half-hour slots taken:
    the directory shows this doctor as Busy (working, but nothing free this
    week). A week later the next clinic is free again."""
    day = today + timedelta(days=2)
    db.add(ScheduleTemplate(doctor_id=doctor.id, weekday=day.weekday(), start_time=time(10, 0), end_time=time(11, 0),
                            slot_minutes=30, valid_from=today))
    start = datetime.combine(day, time(10, 0), tzinfo=tz)
    for index, details in enumerate(DEMO_PATIENTS):
        patient = await _demo_patient(db, *details, by)
        appointment = Appointment(
            patient_id=patient.id, doctor_id=doctor.id, status=AppointmentStatus.scheduled, reason="Demo booking",
            starts_at=start + timedelta(minutes=30 * index), ends_at=start + timedelta(minutes=30 * (index + 1)),
            booked_by_user_id=by.id,
        )
        db.add(appointment)
        await db.flush()
        db.add(AppointmentStatusHistory(appointment_id=appointment.id, from_status=None,
                                        to_status=AppointmentStatus.scheduled, changed_by_user_id=by.id,
                                        reason="Created by the demo seed"))


async def seed() -> None:
    if settings.environment is Environment.production:
        sys.exit("Refusing to seed demo data: ENVIRONMENT=production")

    password = os.environ.get("SEED_PASSWORD") or secrets.token_urlsafe(12)
    password_hash = hash_password(password)
    tz = ZoneInfo(settings.clinic_timezone)
    today = datetime.now(tz).date()
    created = 0

    async with AsyncSessionLocal() as db:
        print("Departments")
        departments = {name: await _department(db, name) for name in DEPARTMENTS}

        print("Doctors")
        for index, (name, dept, specialization, years, fee, qualifications, room, schedule) in enumerate(DOCTORS):
            email = _email(name)
            if await db.scalar(select(User.id).where(User.email == email)) is not None:
                continue
            user = User(name=name, email=email, password_hash=password_hash)
            db.add(user)
            await db.flush()
            await rbac_service.grant_roles(db, user.id, [RoleCode.doctor])
            doctor = Doctor(
                user_id=user.id, department_id=departments[dept].id, title="Dr.", specialization=specialization,
                license_number=f"DEMO-{index + 1:04d}", qualifications=qualifications, years_of_experience=years,
                consultation_fee=Decimal(fee), room_number=room,
                bio=f"{specialization} with {years} years of clinical experience. (Fictional demo profile.)",
            )
            db.add(doctor)
            await db.flush()

            if schedule == "busy":
                await _fully_booked_clinic(db, doctor, tz, today, user)
            elif schedule == "leave":
                _weekly_hours(db, doctor, "full", today)
                db.add(ScheduleException(
                    doctor_id=doctor.id, kind=ExceptionKind.leave, reason="Annual leave (demo)",
                    starts_at=datetime.combine(today, time.min, tzinfo=tz),
                    ends_at=datetime.combine(today + timedelta(days=21), time.min, tzinfo=tz),
                    created_by_user_id=user.id,
                ))
            else:
                _weekly_hours(db, doctor, schedule, today)
            created += 1
            print(f"  + Dr. {name}: {specialization}, {dept} ({schedule})")

        # A doctor with no working hours at all cannot be booked. Give any
        # such existing doctor a standard week so the directory is usable.
        print("Working hours for existing doctors that have none")
        idle = await db.scalars(
            select(Doctor).where(Doctor.is_active.is_(True), ~Doctor.id.in_(select(ScheduleTemplate.doctor_id)))
        )
        for doctor in idle.all():
            _weekly_hours(db, doctor, "full", today)
            print(f"  + Mon-Fri 09:00-17:00 for doctor {doctor.id}")

        await db.commit()

    await engine.dispose()
    print(f"\nDone: {created} doctor(s) created.")
    if created and not os.environ.get("SEED_PASSWORD"):
        print(f"Password for the seeded doctor logins (shown once): {password}")


if __name__ == "__main__":
    asyncio.run(seed())
