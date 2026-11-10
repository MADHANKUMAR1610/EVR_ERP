"""Mounts the controllers. Public API under /api/v1; internal endpoints and the JWKS at the root."""

from fastapi import APIRouter

from app.api.controllers import admin_controller, auth_controller, health_controller, internal_controller

api_router = APIRouter()
api_router.include_router(auth_controller.router)
api_router.include_router(admin_controller.router)

root_router = APIRouter()
root_router.include_router(health_controller.router)
root_router.include_router(internal_controller.keys_router)
root_router.include_router(internal_controller.router)
