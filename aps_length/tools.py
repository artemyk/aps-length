"""External commands and figure metadata, with bounded, readable failures."""

from contextlib import contextmanager
from collections import deque
import locale
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


DEFAULT_TIMEOUT = 120.0
_pymupdf_missing_warned = False


def decode_output(output):
    if isinstance(output, str):
        return output
    return (output or b'').decode(locale.getpreferredencoding(False), errors='replace')


def tail(text, max_lines=20):
    return '\n'.join(text.strip().splitlines()[-max_lines:])


def run_command(command, *, cwd=None, input_text=None, stdin=None, env=None,
                timeout=DEFAULT_TIMEOUT, log_path=None, check=True):
    """Capture bytes consistently; never leave a command waiting on terminal input."""
    try:
        completed = subprocess.run(
            command, cwd=cwd, env=env, timeout=timeout,
            input=input_text.encode('utf-8') if input_text is not None else None,
            stdin=stdin if stdin is not None else (
                subprocess.DEVNULL if input_text is None else None),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise RuntimeError('Could not find command %r' % command[0]) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Command timed out after %g seconds: %s' %
                           (timeout, shlex.join(map(str, command)))) from error
    if check and completed.returncode:
        raise RuntimeError(command_failure(command, completed, log_path))
    return completed


def command_failure(command, completed, log_path=None):
    details = ['Command failed (exit %d): %s' %
               (completed.returncode, shlex.join(map(str, command)))]
    for name in ('stderr', 'stdout'):
        text = tail(decode_output(getattr(completed, name)))
        if text:
            details.append('%s:\n%s' % (name, text))
    if log_path is not None and Path(log_path).is_file():
        # TeX logs do not have a specified encoding.
        with Path(log_path).open(errors='replace') as log:
            text = ''.join(deque(log, maxlen=20)).strip()
        if text:
            details.append('%s:\n%s' % (log_path, text))
    return '\n'.join(details)


@contextmanager
def temporary_workspace(keep=False):
    """Own exactly one directory; never glob or remove manuscript-side files."""
    directory = Path(tempfile.mkdtemp(prefix='aps_length_'))
    try:
        yield directory
    finally:
        if keep:
            print('Temporary files retained in %s' % directory, file=sys.stderr)
        else:
            shutil.rmtree(directory)


def validate_dimensions(width, height, filename):
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise ValueError('Invalid figure dimensions for %s: %s x %s' %
                         (filename, width, height))
    return width, height


def identify_dimensions(filename, *, timeout=DEFAULT_TIMEOUT):
    # Request only machine-readable dimensions. Default identify output embeds
    # the filename, making whitespace-based field indexing unsafe.
    completed = run_command(
        ['identify', '-ping', '-format', '%w %h\n', str(Path(filename).resolve()) + '[0]'],
        timeout=timeout)
    output = decode_output(completed.stdout).strip()
    try:
        width, height = map(float, output.split())
    except ValueError as error:
        raise RuntimeError('Could not parse identify dimensions for %s: %s' %
                           (filename, output)) from error
    return validate_dimensions(width, height, filename)


def gs_dimensions(filename, *, timeout=DEFAULT_TIMEOUT):
    with Path(filename).open('rb') as image:
        completed = run_command(
            ['gs', '-q', '-dSAFER', '-dBATCH', '-dNOPAUSE', '-dFirstPage=1',
             '-dLastPage=1', '-sDEVICE=bbox', '-'], stdin=image, timeout=timeout)
    output = decode_output(completed.stderr)
    for label in ('HiResBoundingBox', 'BoundingBox'):
        match = re.search(r'^%%' + label + r':\s*([^\r\n]+)', output, re.M)
        if match is None:
            continue
        try:
            left, bottom, right, top = map(float, match[1].split())
        except ValueError as error:
            raise RuntimeError('Invalid Ghostscript bounding box for %s: %s' %
                               (filename, match[1])) from error
        return validate_dimensions(right - left, top - bottom, filename)
    raise RuntimeError('Could not parse Ghostscript bounding box for %s: %s' %
                       (filename, tail(output)))


def pdf_dimensions(filename, *, timeout=DEFAULT_TIMEOUT):
    global _pymupdf_missing_warned
    try:
        import pymupdf
    except ImportError:
        if not _pymupdf_missing_warned:
            print('Warning: PyMuPDF is not installed; PDF figures fall back to '
                  'Ghostscript. Install PyMuPDF for more reliable PDF dimensions.',
                  file=sys.stderr)
            _pymupdf_missing_warned = True
        return gs_dimensions(filename, timeout=timeout)

    try:
        with pymupdf.open(filename) as document:
            if not len(document):
                raise ValueError('PDF figure has no pages: %s' % filename)
            page = document[0]
            return validate_dimensions(float(page.rect.width), float(page.rect.height),
                                       filename)
    except Exception as error:
        raise RuntimeError('Could not read PDF figure %s: %s' % (filename, error)) from error


def figure_dimensions(filename, method='identify', *, timeout=DEFAULT_TIMEOUT):
    if Path(filename).suffix.lower() == '.pdf':
        dimensions = pdf_dimensions(filename, timeout=timeout)
    elif method == 'identify':
        dimensions = identify_dimensions(filename, timeout=timeout)
    elif method == 'gs':
        dimensions = gs_dimensions(filename, timeout=timeout)
    else:
        raise ValueError('Unknown figure method %r' % method)
    return validate_dimensions(*dimensions, filename)
