"""Collect admission requirements from official program pages.

The pipeline is snapshot -> extraction with quotes -> verbatim quote check -> import. A value only
counts as machine-checked (`机器核对`) when its quote appears verbatim in the stored snapshot of the
official page; nothing here ever writes `verified_at`, which only a human sets.
"""
