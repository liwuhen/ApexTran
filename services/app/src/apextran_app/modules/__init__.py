"""Business modules. Each is a self-contained bounded context.

Modules must not import each other's internals (see boundary rules §3). They may
import only from ``apextran_app.shared`` or another module's public service API.
"""
