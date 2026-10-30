from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    ai_agent,
    appointments,
    auth,
    dashboard,
    departments,
    doctor_applications,
    doctors,
    documents,
    patients,
    schedules,
    users,
    workspace,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.public_router)
api_router.include_router(admin.router)
api_router.include_router(users.router)
api_router.include_router(users.roles_router)
api_router.include_router(departments.public_router)
api_router.include_router(departments.router)
api_router.include_router(doctors.public_router)
api_router.include_router(doctors.router)
api_router.include_router(doctor_applications.router)
api_router.include_router(patients.router)
api_router.include_router(documents.router)
api_router.include_router(schedules.router)
api_router.include_router(appointments.router)
api_router.include_router(dashboard.router)
api_router.include_router(workspace.router)
api_router.include_router(ai_agent.router)
