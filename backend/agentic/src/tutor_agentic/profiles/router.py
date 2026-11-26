"""FastAPI routes for student profile management.

Mounted by the application at /api/v1/profile (students) and
/api/v1/students/{ref}/profile (teachers managing their students).

Endpoints
---------
POST   /api/v1/profile                       create or replace own profile (student)
GET    /api/v1/profile                       read own profile (student)
PUT    /api/v1/profile                       partial update own profile (student)
DELETE /api/v1/profile                       delete own profile (student)
GET    /api/v1/students/{ref}/profile        read a student's profile (teacher)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..auth import Authenticator, Principal
from ..errors import NotFound
from .defaults import needs_to_preferences
from .models import (
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    StudentProfile,
)
from .store import ProfileStore


def create_profile_router(
    store: ProfileStore,
    authenticator: Authenticator,
) -> APIRouter:
    router = APIRouter(tags=["profile"])
    bearer = HTTPBearer(auto_error=False)

    def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        return authenticator.authenticate(
            credentials.credentials if credentials else None
        )

    CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

    # ------------------------------------------------------------------
    # Student: manage own profile
    # ------------------------------------------------------------------

    @router.post("/profile", response_model=ProfileResponse, status_code=201)
    def create_profile(
        body: ProfileCreateRequest,
        principal: CurrentPrincipal,
    ) -> ProfileResponse:
        """Onboarding: create or fully replace the caller's profile."""
        principal.require_role("student")

        # Derive rendering preferences from declared needs unless the
        # student explicitly supplied them.
        draft = StudentProfile(
            subject_ref=principal.subject_ref,
            age_group=body.age_group,
            school_level=body.school_level,
            cognitive_need=body.cognitive_need,
            vision_need=body.vision_need,
            hearing_need=body.hearing_need,
            motor_need=body.motor_need,
            language_preference=body.language_preference,
        )
        draft = draft.model_copy(
            update={
                "rendering_preferences": (
                    body.rendering_preferences
                    if body.rendering_preferences is not None
                    else needs_to_preferences(draft)
                )
            }
        )
        store.save(draft)
        return ProfileResponse.from_profile(draft)

    @router.get("/profile", response_model=ProfileResponse)
    def get_profile(principal: CurrentPrincipal) -> ProfileResponse:
        """Returns the caller's profile, or 404 if onboarding is not done."""
        principal.require_role("student")
        profile = store.get(principal.subject_ref)
        if profile is None:
            raise NotFound("Profile not found. Complete onboarding first.")
        return ProfileResponse.from_profile(profile)

    @router.put("/profile", response_model=ProfileResponse)
    def update_profile(
        body: ProfileUpdateRequest,
        principal: CurrentPrincipal,
    ) -> ProfileResponse:
        """Partial update. Any field left None keeps its current value.

        If a need field changes and rendering_preferences is not explicitly
        supplied, preferences are re-derived from scratch.
        """
        principal.require_role("student")
        existing = store.get(principal.subject_ref)
        if existing is None:
            raise NotFound("Profile not found. Complete onboarding first.")

        needs_changed = any(
            getattr(body, f) is not None
            for f in ("cognitive_need", "vision_need", "hearing_need", "motor_need")
        )

        updated = existing.model_copy(
            update={
                k: v
                for k, v in body.model_dump(exclude_none=True).items()
                if k != "rendering_preferences"
            }
        )

        if body.rendering_preferences is not None:
            updated = updated.model_copy(
                update={"rendering_preferences": body.rendering_preferences}
            )
        elif needs_changed:
            # Re-derive preferences from the new needs combination
            updated = updated.model_copy(
                update={"rendering_preferences": needs_to_preferences(updated)}
            )

        store.save(updated)
        return ProfileResponse.from_profile(updated)

    @router.delete("/profile", status_code=204)
    def delete_profile(principal: CurrentPrincipal) -> None:
        """Remove the caller's profile (GDPR right to erasure)."""
        principal.require_role("student")
        store.delete(principal.subject_ref)

    # ------------------------------------------------------------------
    # Teacher: read a student's profile (read-only)
    # ------------------------------------------------------------------

    @router.get("/students/{student_ref}/profile", response_model=ProfileResponse)
    def get_student_profile(
        student_ref: Annotated[str, Path(min_length=1, max_length=64)],
        principal: CurrentPrincipal,
    ) -> ProfileResponse:
        """Allows a teacher to read the profile of one of their students."""
        principal.require_role("teacher")
        profile = store.get(student_ref)
        if profile is None:
            raise NotFound(f"No profile found for student {student_ref!r}.")
        return ProfileResponse.from_profile(profile)

    return router
