"""Mounts the controllers under /api/v1, and the health probes at the root."""

from fastapi import APIRouter

from app.api.controllers import health_controller, manufacturing_controller

api_router = APIRouter()
api_router.include_router(manufacturing_controller.production_router)
api_router.include_router(manufacturing_controller.dashboard_router)

root_router = APIRouter()
root_router.include_router(health_controller.router)
