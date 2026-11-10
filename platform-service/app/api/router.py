"""Mounts the controllers. Public API under /api/v1; internal endpoints at the root (never exposed by the proxy)."""

from fastapi import APIRouter

from app.api.controllers import health_controller, platform_controller

api_router = APIRouter()
api_router.include_router(platform_controller.admin_router)
api_router.include_router(platform_controller.notifications_router)

root_router = APIRouter()
root_router.include_router(health_controller.router)
root_router.include_router(platform_controller.internal_router)
