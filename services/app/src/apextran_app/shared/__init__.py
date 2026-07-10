"""Cross-module infrastructure. The ONLY package modules may import from.

Modules must not import each other's internals — they collaborate only through
`shared/` or another module's public service methods. See the three boundary
rules in docs/business-service-架构方案.md §3.
"""
