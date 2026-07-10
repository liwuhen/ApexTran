"""Copy-paste skeleton for a new business module (模块 B / C / ...).

To add a module named ``foo``:

1. ``cp -r modules/_template modules/foo``
2. Rename ``ModuleSpec(name="_template")`` → ``name="foo"`` in ``wiring.py`` and
   the router prefix ``/api/v1/_template`` → ``/api/v1/foo`` in ``router.py``.
3. That's it — ``discover_modules()`` picks it up on next boot; ``main`` mounts
   the router, ``worker`` registers the jobs. No edits to main/worker/discovery.

The leading ``_`` makes discovery skip this template so it never mounts. Remove
it (via the rename) and the module goes live. Structure mirrors ``market/``:

    domain/     pure models (no I/O)
    ports.py    the Protocol(s) the service depends on
    adapters/   concrete implementations of the ports (sources, clients)
    service.py  application logic (orchestrates ports; no framework imports)
    provider.py composition — build the singleton from config
    router.py   HTTP surface (thin; delegates to the service)
    ingest.py   optional scheduled jobs (register_jobs)
    wiring.py   the ModuleSpec discovery collects

Rule of thumb: a module never imports another module's internals — cross-module
needs go through ``shared/`` or an HTTP call.
"""
