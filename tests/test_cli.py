import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aps_length import cli, counting
from tests.helpers import document, options


class OptionsTests(unittest.TestCase):
    def assert_invalid(self, *arguments):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                options(*arguments)
        self.assertEqual(error.exception.code, 2)

    def test_invalid_values_are_usage_errors(self):
        for arguments in (('--journal=NOPE',), ('--method=bad',), ('--figs=bad',),
                          ('--scale-figs=-1',), ('--scale-figs=nan',), ('--scale-figs=inf',),
                          ('--timeout=0',), ('--timeout=inf',), ('--latex=',),
                          ('--latex="unclosed',), ('--latexopts="unclosed',),
                          ('--var', '', 'value')):
            with self.subTest(arguments=arguments):
                self.assert_invalid(*arguments)

    def test_stop_comment_default_and_empty(self):
        self.assertEqual(options().stop_comment, '!STOP-APS-LENGTH!')
        self.assertEqual(options('--stop-comment=').stop_comment, '')

    def test_environment_whitespace_and_keep_aliases(self):
        self.assertEqual(options('--env= abstract, align , ,custom').env, ('abstract', 'align', 'custom'))
        self.assertTrue(options('--keep_tmp_files').keep_tmp_files)
        self.assertTrue(options('--keep-tmp-files').keep_tmp_files)

    def test_zero_figure_scale_is_allowed(self):
        self.assertEqual(options('--scale-figs=0').scale_figs, 0)


class CliTests(unittest.TestCase):
    def test_missing_file_is_a_clean_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with contextlib.redirect_stdout(io.StringIO()):
                result = cli.main(['/does/not/exist.tex'])
        self.assertEqual(result, 1)
        self.assertIn('exist.tex', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())

    def test_batch_continues_after_one_failure_and_returns_failure(self):
        with patch.object(cli, 'process', side_effect=[ValueError('bad input'), cli.Counts(1, 2, 0, 0, 0)]) as process:
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                status = cli.main(['bad.tex', 'good.tex'])
        self.assertEqual(status, 1)
        self.assertEqual(process.call_count, 2)
        self.assertIn('bad input', errors.getvalue())

    def test_keyboard_interrupt_has_standard_exit_status(self):
        with patch.object(cli, 'process', side_effect=KeyboardInterrupt):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['paper.tex']), 130)

    def test_absolute_source_path_never_changes_process_directory(self):
        with tempfile.TemporaryDirectory(prefix='aps length ') as directory:
            path = Path(directory) / 'paper with space.tex'
            path.write_text(document('body'), encoding='utf-8')
            before = Path.cwd()
            with patch.object(counting, 'count_main_text_words_wordcount', return_value=7) as backend:
                with contextlib.redirect_stdout(io.StringIO()):
                    counts = cli.process(path, options())
            self.assertEqual(counts.total, 7)
            self.assertEqual(backend.call_args.args[2], path.resolve().parent)
            self.assertEqual(Path.cwd(), before)

    def test_invalid_structure_is_rejected_before_running_latex(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.tex'
            path.write_text(document(r'\begin{figure}missing end'))
            with patch.object(counting, 'count_main_text_words_wordcount') as backend:
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(ValueError):
                        cli.process(path, options())
            backend.assert_not_called()

    def test_launcher_and_module_entry_points(self):
        root = Path(__file__).resolve().parents[1]
        for arguments in (['aps-length', '--help'], ['-m', 'aps_length', '--help']):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, *arguments], cwd=root,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--timeout', result.stdout)
        result = subprocess.run([sys.executable, 'aps-length'], cwd=root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
