from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    ai_agent,
    appointments,
    auth,
    google_auth,
    catalog,
    dashboard,
    departments,
    doctor_applications,
    doctors,
    documents,
    follow_ups,
    health_records,
    internal,
    patients,
    queue,
    realtime,
    receptionists,
    schedules,
    users,
    workspace,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(google_auth.router)
api_router.include_router(admin.public_router)
api_router.include_router(admin.router)
api_router.include_router(users.router)
api_router.include_router(users.roles_router)
api_router.include_router(departments.public_router)
api_router.include_router(departments.router)
# Before the doctors routers, so /doctors/me/... is not read as /doctors/{doctor_id} (D131).
api_router.include_router(receptionists.doctor_router)
api_router.include_router(receptionists.public_router)
api_router.include_router(receptionists.router)
api_router.include_router(doctors.public_router)
api_router.include_router(doctors.router)
api_router.include_router(catalog.public_router)
api_router.include_router(catalog.router)
api_router.include_router(catalog.doctor_router)
api_router.include_router(doctor_applications.router)
api_router.include_router(patients.router)
api_router.include_router(documents.router)
api_router.include_router(health_records.router)
api_router.include_router(schedules.router)
api_router.include_router(follow_ups.router)
api_router.include_router(appointments.router)
api_router.include_router(queue.router)
api_router.include_router(dashboard.router)
api_router.include_router(workspace.router)
api_router.include_router(ai_agent.router)
api_router.include_router(internal.router)
api_router.include_router(realtime.router)
