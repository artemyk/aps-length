import builtins
import contextlib
import io
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import zlib

from aps_length import tools


class CommandTests(unittest.TestCase):
    def test_consistent_bytes_and_closed_stdin(self):
        completed = subprocess.CompletedProcess(['tool'], 0, b'ok', b'')
        with patch.object(tools.subprocess, 'run', return_value=completed) as run:
            tools.run_command(['tool'])
            self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
            tools.run_command(['tool'], input_text='input\n')
            self.assertEqual(run.call_args.kwargs['input'], b'input\n')
            self.assertIsNone(run.call_args.kwargs['stdin'])

    def test_missing_command_and_timeout_are_clear_errors(self):
        for error, message in ((FileNotFoundError(), 'Could not find command'),
                               (subprocess.TimeoutExpired(['tool'], 1), 'timed out')):
            with self.subTest(error=error), patch.object(tools.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(RuntimeError, message):
                    tools.run_command(['tool'], timeout=1)

    def test_failures_include_exit_code_and_both_output_types(self):
        for stdout, stderr in ((b'output\xff', b'error'), ('output', 'error')):
            completed = subprocess.CompletedProcess(['tool'], 3, stdout, stderr)
            with self.subTest(stdout=stdout), patch.object(tools.subprocess, 'run', return_value=completed):
                with self.assertRaisesRegex(RuntimeError, 'exit 3.*') as error:
                    tools.run_command(['tool'])
                self.assertIn('output', str(error.exception))
                self.assertIn('error', str(error.exception))

    def test_log_tail_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'test.log'
            log.write_text('\n'.join('line%d' % i for i in range(100)))
            completed = subprocess.CompletedProcess(['tool'], 1, b'', b'')
            message = tools.command_failure(['tool'], completed, log)
        self.assertNotIn('line0\n', message)
        self.assertIn('line99', message)

    def test_temporary_workspace_is_removed_on_exception(self):
        with self.assertRaisesRegex(ValueError, 'failure'):
            with tools.temporary_workspace() as path:
                (path / 'manuscriptNotes.bib').touch()
                raise ValueError('failure')
        self.assertFalse(path.exists())

    def test_keep_workspace_reports_location(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with tools.temporary_workspace(keep=True) as path:
                (path / 'test').touch()
        self.addCleanup(tools.shutil.rmtree, path)
        self.assertTrue((path / 'test').is_file())
        self.assertIn(str(path), errors.getvalue())


class DimensionTests(unittest.TestCase):
    def completed(self, stdout=b'', stderr=b''):
        return subprocess.CompletedProcess([], 0, stdout, stderr)

    def test_identify_requests_structured_dimensions_for_space_in_path(self):
        with patch.object(tools, 'run_command', return_value=self.completed(b'640 480\n')) as run:
            self.assertEqual(tools.identify_dimensions('fig with space.png'), (640.0, 480.0))
        self.assertIn('-format', run.call_args.args[0])
        self.assertTrue(run.call_args.args[0][-1].endswith('fig with space.png[0]'))

    def test_bad_identify_output_is_an_error(self):
        for output in (b'', b'not dimensions', b'10 20 30'):
            with self.subTest(output=output), patch.object(tools, 'run_command', return_value=self.completed(output)):
                with self.assertRaisesRegex(RuntimeError, 'Could not parse identify'):
                    tools.identify_dimensions('plot.png')

    def test_gs_uses_high_resolution_box_and_subtracts_origin(self):
        output = (b'warning before bbox\n%%BoundingBox: 10 20 111 71\n'
                  b'%%HiResBoundingBox: 10.5 20.5 110.5 70.5\n')
        with tempfile.NamedTemporaryFile() as image:
            with patch.object(tools, 'run_command', return_value=self.completed(stderr=output)):
                self.assertEqual(tools.gs_dimensions(image.name), (100.0, 50.0))

    def test_gs_malformed_and_missing_bounding_box(self):
        with tempfile.NamedTemporaryFile() as image:
            for output in (b'warning only', b'%%BoundingBox: invalid data'):
                with self.subTest(output=output), patch.object(tools, 'run_command', return_value=self.completed(stderr=output)):
                    with self.assertRaises(RuntimeError):
                        tools.gs_dimensions(image.name)

    def test_nonpositive_and_nonfinite_dimensions_are_rejected(self):
        for width, height in ((0, 10), (-1, 10), (10, 0), (math.nan, 1), (1, math.inf)):
            with self.subTest(width=width, height=height):
                with self.assertRaisesRegex(ValueError, 'Invalid figure dimensions'):
                    tools.validate_dimensions(width, height, 'figure')

    def test_pdf_missing_dependency_warns_once_and_falls_back(self):
        original_import = builtins.__import__

        def without_pymupdf(name, *args, **kwargs):
            if name == 'pymupdf':
                raise ImportError('not installed')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=without_pymupdf):
            with patch.object(tools, '_pymupdf_missing_warned', False):
                with patch.object(tools, 'gs_dimensions', return_value=(300.0, 100.0)) as gs:
                    with contextlib.redirect_stderr(io.StringIO()) as errors:
                        self.assertEqual(tools.pdf_dimensions('plot.pdf'), (300.0, 100.0))
                        tools.pdf_dimensions('plot.pdf')
        self.assertEqual(gs.call_count, 2)
        self.assertEqual(errors.getvalue().count('PyMuPDF is not installed'), 1)

    def test_pdf_is_closed_on_bad_page_data(self):
        pdf = MagicMock()
        pdf.__enter__.return_value = pdf
        pdf.__len__.return_value = 0
        fake_pymupdf = SimpleNamespace(open=MagicMock(return_value=pdf))
        with patch.dict('sys.modules', {'pymupdf': fake_pymupdf}):
            with self.assertRaisesRegex(RuntimeError, 'no pages'):
                tools.pdf_dimensions('empty.pdf')
        pdf.__exit__.assert_called_once()

    def test_pdf_open_errors_include_filename(self):
        fake_pymupdf = SimpleNamespace(open=MagicMock(side_effect=ValueError('corrupt')))
        with patch.dict('sys.modules', {'pymupdf': fake_pymupdf}):
            with self.assertRaisesRegex(RuntimeError, 'broken.pdf.*corrupt'):
                tools.pdf_dimensions('broken.pdf')


class ImageIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('identify'), 'ImageMagick is unavailable')
    def test_real_identify_with_spaces_in_filename(self):
        def chunk(kind, data):
            return (struct.pack('>I', len(data)) + kind + data +
                    struct.pack('>I', zlib.crc32(kind + data)))

        # A small reproducible PNG fixture without an imaging dependency.
        width, height = 120, 60
        png = (b'\x89PNG\r\n\x1a\n' +
               chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
               chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\x00\x00' * width) * height)) +
               chunk(b'IEND', b''))
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'figure with spaces.png'
            image.write_bytes(png)
            self.assertEqual(tools.identify_dimensions(image), (120.0, 60.0))

    @unittest.skipUnless(shutil.which('gs'), 'Ghostscript is unavailable')
    def test_real_ghostscript_with_nonzero_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'figure with spaces.eps'
            image.write_text('%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 10 20 110 70\n'
                             'newpath 10 20 moveto 110 20 lineto 110 70 lineto '
                             '10 70 lineto closepath fill\nshowpage\n')
            width, height = tools.gs_dimensions(image)
        self.assertAlmostEqual(width, 100, places=1)
        self.assertAlmostEqual(height, 50, places=1)

    def test_real_pdf_uses_page_rectangle(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest('PyMuPDF is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'figure with spaces.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page(width=200, height=100)
                pdf.save(image)
            self.assertEqual(tools.pdf_dimensions(image), (200.0, 100.0))
