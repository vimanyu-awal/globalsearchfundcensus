"""Microcap Deep-Value Pipeline.

Research-only system that reads the US microcap universe and surfaces names in
three lanes (net-nets, special situations, ignored compounders). See SPEC.md.

This package never trades, never connects to a brokerage, and never asserts
compliance. Phase 1 (this milestone) builds the tradable universe only.
"""

__all__ = ["config"]
