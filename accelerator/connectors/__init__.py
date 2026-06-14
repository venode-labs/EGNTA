"""Read-only connectors that normalise a client source into the canonical Event
shape. Every connector reads, never writes, and is the one boundary where a raw
source is mapped through a vertical's synonym table before any mining happens.
"""
