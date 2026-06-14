"""Egenta discovery accelerator.

Read-only client-discovery engine: deterministic connectors normalise each source
into a canonical event log in a per-engagement warehouse, a deterministic mining
pass writes citeable metrics, and (iteration 2) capped Claude reasoners synthesise
a grounded pain register over the warehouse. The LLM never touches a live client
credential or system.
"""
__version__ = "0.1.0"
