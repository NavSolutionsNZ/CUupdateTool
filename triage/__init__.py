"""triage -- vendor-delta triage front-end for the CU upgrade process.

Stage 1: compare the Existing vendor baseline against the New vendor baseline to
find the objects the vendor changed (or added) in the new CU. Those are the only
objects that need to land in the customer DB; everything identical between the
two baselines is dropped. Emits a pipe-separated, type-grouped object list for
easy export from NAV, and stages the New Baseline copies of the changed objects.

Imports compareengine for the body-level comparison (no engine fork). Isolated
from cuupdate/.
"""
__version__ = "0.9"
