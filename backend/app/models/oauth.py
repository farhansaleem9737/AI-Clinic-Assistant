"""Sign-in with an external identity provider (D123: Google).

``OAuthIdentity`` links a provider account to a local user. The provider's
``subject`` (Google's ``sub``) is the permanent key: an email address can change
hands, ``sub`` never does. One provider account belongs to one user, and a user
has at most one account per provider.

``OAuthFlow`` holds the short-lived, single-use server state of a sign-in in
progress. Only hashes of the random values the browser holds are stored.

- ``authorize``: started, waiting for Google's callback (state, PKCE verifier, nonce);
- ``handoff``: Google confirmed a known user; the app page completes the session;
- ``signup``: Google confirmed a new person; they finish the registration form.
- ``link`` (D128): Google confirmed an address that already has an account; the
  owner proves they control it (password or emailed code), then Google is linked.

Each row is bound to the browser that started it (``binder_hash``: a cookie),
expires quickly and is consumed atomically, so it cannot be replayed or used in
another browser (login CSRF).
"""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, Boolean, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

GOOGLE = "google"


class OAuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="provider_subject"),
        UniqueConstraint("user_id", "provider", name="one_per_provider"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    # The provider's address when last seen: shown to the user, never used to find them.
    email: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthFlow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "oauth_flows"
    __table_args__ = (
        CheckConstraint("kind IN ('authorize', 'handoff', 'signup', 'link')", name="kind_known"),
        CheckConstraint("purpose IN ('login', 'register', 'link')", name="purpose_known"),
    )

    kind: Mapped[str] = mapped_column(String(10))
    purpose: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(20), default=GOOGLE)
    # SHA-256 of the value in the URL (state) or in the step's cookie.
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    # SHA-256 of the cookie of the browser that started the sign-in.
    binder_hash: Mapped[str] = mapped_column(CHAR(64))
    code_verifier: Mapped[str | None] = mapped_column(String(128))
    nonce: Mapped[str | None] = mapped_column(String(64))
    # purpose link: the signed-in user; handoff: the user to sign in; kind link: the existing account.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False)
    # signup / link: the verified Google identity waiting for the form or the proof.
    subject: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    given_name: Mapped[str | None] = mapped_column(String(100))
    family_name: Mapped[str | None] = mapped_column(String(100))
    # kind link (D128): wrong passwords or codes so far, and the emailed code's HMAC.
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    code_hash: Mapped[str | None] = mapped_column(CHAR(64))
    code_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
