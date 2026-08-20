"""The values every stomp package exchanges.

Pure Python by construction: no kernel, no parser, no I/O beyond
serialisation. What lives here either crosses a package boundary with no
owner, or is a contract both tools implement identically. See ADR-0009.
"""
