"""Focused local checks for Azure cost-loader chunk checkpointing."""

# ruff: noqa: D101, D102, D103

import ast
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'jobs/notebooks/azure_cloud_cost_explorer_app.ipynb'


def load_code() -> str:
    notebook = json.loads(NOTEBOOK.read_text())
    return '\n\n'.join(
        ''.join(cell.get('source', []))
        for cell in notebook['cells']
        if cell.get('cell_type') == 'code'
        and not ''.join(cell.get('source', [])).lstrip().startswith(('%', '!'))
    )


def class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


class AzureChunkCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_code()
        cls.tree = ast.parse(cls.source)

    def method_source(self, method_name: str) -> str:
        node = class_method(self.tree, 'AzureCostReporterApp', method_name)
        return ast.get_source_segment(self.source, node)

    def test_notebook_python_cells_parse(self):
        self.assertIsInstance(self.tree, ast.Module)

    def test_checkpoint_key_is_deterministic_and_watermark_safe(self):
        node = class_method(
            self.tree, 'AzureCostReporterApp', '_chunk_checkpoint_name'
        )
        probe = ast.Module(
            body=[
                ast.ClassDef(
                    name='Probe',
                    bases=[],
                    keywords=[],
                    decorator_list=[],
                    body=[node],
                )
            ],
            type_ignores=[],
        )
        namespace = {}
        exec(compile(ast.fix_missing_locations(probe), '<checkpoint-probe>', 'exec'), namespace)
        key = namespace['Probe']._chunk_checkpoint_name(
            'dbspend360_cloud_cost_explorer',
            date(2026, 1, 2),
            date(2026, 1, 11),
        )
        self.assertEqual(
            key,
            'dbspend360_cloud_cost_explorer__chunk__2026-01-02__2026-01-11',
        )
        self.assertNotEqual(key, 'dbspend360_cloud_cost_explorer')

    def test_chunk_builder_preserves_inclusive_one_day_semantics(self):
        node = class_method(self.tree, 'AzureCostClient', '_build_chunks')
        probe = ast.Module(
            body=[
                ast.ClassDef(
                    name='Probe',
                    bases=[],
                    keywords=[],
                    decorator_list=[],
                    body=[node],
                )
            ],
            type_ignores=[],
        )
        namespace = {'datetime': datetime, 'timedelta': timedelta}
        exec(compile(ast.fix_missing_locations(probe), '<chunk-probe>', 'exec'), namespace)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 3, tzinfo=timezone.utc)
        chunks = namespace['Probe']()._build_chunks(start, end, 1)
        self.assertEqual(
            [(left.date(), right.date()) for left, right in chunks],
            [
                (date(2026, 1, 1), date(2026, 1, 1)),
                (date(2026, 1, 2), date(2026, 1, 2)),
                (date(2026, 1, 3), date(2026, 1, 3)),
            ],
        )

    def test_cluster_loop_skips_success_and_checkpoints_after_merge(self):
        run = self.method_source('run')
        loop = run.index('for chunk_start_utc, chunk_end_utc in chunks:')
        skip = run.index('if checkpoint_rows is not None:', loop)
        query = run.index('self.client.query_cluster_chunk(', loop)
        merge = run.index('self._merge_cluster_chunk(', query)
        chunk_success = run.index('"SUCCESS", chunk_rows, chunk_quality', merge)
        full_guard = run.index('if completed_chunks != len(chunks):', chunk_success)
        standard_success = run.index('self.audit_table, self.TABLE_NAME', full_guard)
        self.assertLess(skip, query)
        self.assertLess(merge, chunk_success)
        self.assertLess(chunk_success, full_guard)
        self.assertLess(full_guard, standard_success)

    def test_pool_is_checkpointed_and_remains_non_fatal(self):
        run_pool = self.method_source('run_pool')
        loop = run_pool.index('for chunk_start_utc, chunk_end_utc in chunks:')
        skip = run_pool.index('if checkpoint_rows is not None:', loop)
        query = run_pool.index('self.client.query_pool_chunk(', loop)
        merge = run_pool.index('self._merge_pool_chunk(', query)
        chunk_success = run_pool.index('"SUCCESS", chunk_rows, chunk_quality', merge)
        full_guard = run_pool.index('if completed_chunks != len(chunks):', chunk_success)
        standard_success = run_pool.index(
            'self.audit_table, self.POOL_TABLE_NAME', full_guard
        )
        except_block = run_pool.index('except Exception as e:', standard_success)
        self.assertLess(skip, query)
        self.assertLess(merge, chunk_success)
        self.assertLess(chunk_success, full_guard)
        self.assertLess(full_guard, standard_success)
        self.assertNotIn('raise\n', run_pool[except_block:])
        self.assertIn('self._pool_window_cost(start_dt, end_dt)', run_pool)

    def test_empty_first_page_still_follows_next_link(self):
        cluster = ast.get_source_segment(
            self.source, class_method(self.tree, 'AzureCostClient', '_execute_query')
        )
        pool = ast.get_source_segment(
            self.source, class_method(self.tree, 'AzureCostClient', '_execute_pool_query')
        )
        for source in (cluster, pool):
            self.assertIn('if not all_rows and not next_link:', source)
            self.assertNotIn('if not result.rows:', source)
            self.assertIn('self._query_page_state(result)', source)
        fetch = ast.get_source_segment(
            self.source, class_method(self.tree, 'AzureCostClient', '_fetch_next_page')
        )
        self.assertNotIn('data=query_json', fetch)

    def test_empty_cluster_day_is_a_valid_zero_row_checkpoint(self):
        merge = self.method_source('_merge_cluster_chunk')
        empty_branch = merge[: merge.index('else:')]
        self.assertIn('merged_row_count = 0', empty_branch)
        self.assertIn('empty_chunk=true', empty_branch)
        self.assertNotIn('raise DataQualityError', empty_branch)

    def test_no_cross_chunk_result_accumulation(self):
        self.assertNotIn('all_chunk_dfs', self.source)
        self.assertNotIn('all_records.extend', self.source)
        client = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'AzureCostClient'
        )
        methods = {
            node.name for node in client.body if isinstance(node, ast.FunctionDef)
        }
        self.assertNotIn('group_by_job_clusterid_daily', methods)
        self.assertNotIn('group_by_pool_daily', methods)


if __name__ == '__main__':
    unittest.main()
