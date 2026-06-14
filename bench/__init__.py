"""Graded benchmark for the EGNTA discovery accelerator.

Makes the "better than the baseline" claim falsifiable: a synthetic business with
planted, labelled defects (an answer key), a pre-registered metric, and two
non-conflated baselines. The headline is relative error reduction in detection-F1
against a naive single-pass baseline, gated by citation-grounding. PM4Py is an
out-of-process CI oracle for the process sub-metric only, never the headline.
"""
