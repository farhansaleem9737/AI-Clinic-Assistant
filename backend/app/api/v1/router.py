from fastapi import APIRouter

from app.api.v1.endpoints import appointments, auth, dashboard, departments, doctors, patients, schedules, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(users.roles_router)
api_router.include_router(departments.public_router)
api_router.include_router(departments.router)
api_router.include_router(doctors.public_router)
api_router.include_router(doctors.router)
api_router.include_router(patients.router)
api_router.include_router(schedules.router)
api_router.include_router(appointments.router)
api_router.include_router(dashboard.router)
