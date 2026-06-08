"""Layer 1 — official / aggregator board sources.

- ``ArbeitsagenturSource`` — German Federal Employment Agency (adapted from the
  reference project's client). Public API key, broad DE coverage.
- ``EuresSource`` — EU job-mobility portal; one source spanning EU/EEA. Needs
  partner credentials in production (passed as a header by the injected transport).
- ``JobRoomSource`` — Switzerland's official public employment service (job-room.ch,
  run by SECO). Switzerland is NOT in EURES, so this is the compliant CH baseline;
  commercial boards (jobs.ch / jobup.ch) need a partnership and are out of scope here.
"""

from job_agent.sources.aggregators.arbeitsagentur import ArbeitsagenturSource
from job_agent.sources.aggregators.eures import EuresSource
from job_agent.sources.aggregators.jobroom import JobRoomSource
from job_agent.sources.aggregators.jsearch import JSearchSource

__all__ = ["ArbeitsagenturSource", "EuresSource", "JobRoomSource", "JSearchSource"]
