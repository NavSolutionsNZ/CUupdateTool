"""CUupdateTool -- C/AL CU cumulative-update merge engine.

Single source of truth for the tool version. The build (cu.spec) reads this to
name the frozen executable (CUupdate_<version>.exe) and the GUI shows it in the
window title, so a developer can tell at a glance which build produced a merge.

Versioning: start 1.9, increment by 0.1 up to whole numbers (1.9 -> 2.0 -> 2.1).
"""
__version__ = "2.1"
