"""All Phase 4 routers, for one line in app/main.py:

    from app.manage.routers import manage_routers
    for r in manage_routers:
        app.include_router(r)
"""
from .router_analytics import router as analytics_router
from .router_knowledge import router as knowledge_router
from .router_logs import router as logs_router
from .router_machines import router as machines_router
from .router_people import audit_router, router as people_router

manage_routers = [people_router, audit_router, machines_router, knowledge_router, analytics_router, logs_router]
