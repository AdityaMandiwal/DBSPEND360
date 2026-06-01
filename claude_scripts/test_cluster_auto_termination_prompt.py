"""Lock the JOB-cluster auto-termination rendering into the LLM prompt path.

Background
----------
`system.compute.clusters.auto_termination_minutes` is NULL for JOB clusters by
design — the cluster lifecycle is bound to the run, so there is no idle-shutdown
to configure. Older versions of DBSpend360 rendered the literal string
``Auto-termination: Disabled`` for those rows, which caused the cluster-analysis
LLM to flag a non-issue and recommend "enable auto-termination".

This file pins that behaviour with two assertions:

1. For ``cluster_source == 'JOB'`` (the only kind in the current pipeline, since
   ``dbspend360_dbu_cost_app.ipynb`` filters to JOB clusters), the user message
   and the structured fallback MUST NOT contain ``Auto-termination: Disabled``.
2. For interactive clusters, the legacy ``Auto-termination: Disabled`` text
   still surfaces when the column is NULL.

Run directly:

    uv run python claude_scripts/test_cluster_auto_termination_prompt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.models.job_spend import ClusterDetails  # noqa: E402
from server.services.llm_service import LLMService  # noqa: E402


def _job_cluster() -> ClusterDetails:
  return ClusterDetails(
    cluster_id='0901-160000-job-abc',
    cluster_name='ephemeral-job-cluster',
    cluster_source='JOB',
    driver_node_type='Standard_DS3_v2',
    worker_node_type='Standard_DS3_v2',
    worker_count=2,
    auto_termination_minutes=None,
  )


def _interactive_cluster() -> ClusterDetails:
  return ClusterDetails(
    cluster_id='0901-160000-interactive-xyz',
    cluster_name='my-team-shared-cluster',
    cluster_source='UI',
    driver_node_type='Standard_DS3_v2',
    worker_node_type='Standard_DS3_v2',
    worker_count=4,
    auto_termination_minutes=None,
  )


def assert_job_cluster_user_message_is_clean() -> None:
  msg = (
    LLMService._build_cluster_user_message.__wrapped__
    if hasattr(  # type: ignore[attr-defined]
      LLMService._build_cluster_user_message, '__wrapped__'
    )
    else LLMService._build_cluster_user_message
  )

  rendered = msg(LLMService.__new__(LLMService), _job_cluster(), None)

  assert 'Auto-termination: Disabled' not in rendered, (
    'Regression: JOB cluster user message contains '
    "'Auto-termination: Disabled'. The LLM will incorrectly flag a "
    'non-issue.\n\n--- rendered ---\n' + rendered
  )
  assert 'Cluster Type: JOB cluster' in rendered, (
    "JOB cluster user message is missing the 'Cluster Type: JOB cluster' "
    'preamble.\n\n--- rendered ---\n' + rendered
  )
  assert 'N/A (ephemeral job cluster' in rendered, (
    'JOB cluster auto-termination line is not rendered as N/A.\n\n--- rendered ---\n' + rendered
  )


def assert_job_cluster_fallback_is_clean() -> None:
  rendered = LLMService._build_cluster_fallback(_job_cluster(), None)

  assert 'Auto-termination: Disabled' not in rendered, (
    "Regression: JOB cluster fallback contains 'Auto-termination: "
    "Disabled'.\n\n--- rendered ---\n" + rendered
  )
  assert 'Not applicable' in rendered, (
    'JOB cluster fallback ## 4. Idle Waste Risk should say '
    "'Not applicable'.\n\n--- rendered ---\n" + rendered
  )


def assert_interactive_cluster_still_flags_disabled() -> None:
  """Future-proofing: if the DBU pipeline ever stops filtering to JOB clusters,
  auto-termination must still be flagged as 'Disabled' for interactive ones."""
  rendered_msg = LLMService._build_cluster_user_message(
    LLMService.__new__(LLMService), _interactive_cluster(), None
  )
  rendered_fb = LLMService._build_cluster_fallback(_interactive_cluster(), None)

  assert 'Auto-termination: Disabled' in rendered_msg, (
    "Interactive cluster should still render 'Auto-termination: Disabled' "
    'when the column is NULL.\n\n--- rendered ---\n' + rendered_msg
  )
  assert 'Auto-termination: Disabled' in rendered_fb, (
    "Interactive cluster fallback should still render 'Auto-termination: "
    "Disabled' when the column is NULL.\n\n--- rendered ---\n" + rendered_fb
  )


def main() -> None:
  checks = [
    ('JOB cluster user message is clean', assert_job_cluster_user_message_is_clean),
    ('JOB cluster fallback is clean', assert_job_cluster_fallback_is_clean),
    (
      'Interactive cluster still flags Disabled',
      assert_interactive_cluster_still_flags_disabled,
    ),
  ]

  failures: list[tuple[str, AssertionError]] = []
  for name, fn in checks:
    try:
      fn()
      print(f'PASS  {name}')
    except AssertionError as e:
      print(f'FAIL  {name}')
      failures.append((name, e))

  if failures:
    print('\n--- failures ---')
    for name, err in failures:
      print(f'\n{name}:\n{err}')
    sys.exit(1)

  print('\nAll checks passed.')


if __name__ == '__main__':
  main()
