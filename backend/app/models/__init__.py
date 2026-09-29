"""Import every model so Base.metadata is complete (Alembic autogenerate, tests)."""

from app.models.department import Department
from app.models.doctor import Doctor
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.refresh_token import RefreshToken
from app.models.user import User

__all__ = ["Department", "Doctor", "Permission", "RefreshToken", "Role", "RolePermission", "User", "UserRole"]
