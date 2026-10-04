"""Refusals: the protocol said no, and nothing was read, registered or recorded.

A refusal is different from a failed run. A failed or errored run happened and
is on the record; a refusal stops a request before it can touch data or the
registry. The command line exits 2 for every refusal.
"""

from __future__ import annotations


class ProtocolRefusal(RuntimeError):
    """The request would weaken the evidence, so it was refused before anything happened."""


class SpecError(ProtocolRefusal, ValueError):
    """A spec is malformed or cannot be registered as written."""


class HoldoutViolation(ProtocolRefusal):
    """A request would read unseen data in exploration, or seen data as a holdout."""


class NotRegistered(ProtocolRefusal):
    """A run was requested for a spec that has no registration."""


class DossierMismatch(ProtocolRefusal):
    """The framing dossier no longer matches what the registration bound."""


class UnpinnedCode(ProtocolRefusal):
    """A holdout run would use code that is not committed or not the pinned version."""
