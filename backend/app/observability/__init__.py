"""Records what the planner did (agents, tools, data lookups, AI calls, safety decisions) for the dashboard.

Use it as ``from app.observability import recorder as observe``. Everything there does nothing outside a recorded
request, and a recording problem never changes or stops a plan.
"""
