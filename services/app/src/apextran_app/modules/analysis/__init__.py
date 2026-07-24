"""analysis — AI analysis module: assembles context, streams agent-service output.

Depends only on the ``AgentClient`` port. It never imports the ``market`` module's
internals; to enrich context with market data it would call market's public
service API (boundary rule §3).
"""
