"""Neutral core types — ApexTran's runtime-agnostic foundation.

Project-owned value types and protocols that the rest of the backend builds on,
independent of any third-party agent runtime:

* ``events``     — StreamEvent / StreamState / AsyncStreamEvents
* ``errors``     — ErrorKind / AgentError
* ``tools``      — Tool / ToolContext / @tool
* ``tape_types`` — TapeEntry / TapeQuery / TapeContext
* ``store``      — TapeStore / AsyncTapeStore protocols + in-memory store
* ``engine``     — ModelEngine / Tape (tape storage; model calls run via LangGraph)
"""
