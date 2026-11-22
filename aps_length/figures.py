"""Figure discovery and the existing APS aspect-ratio estimate."""

from pathlib import Path
import math
import re
import sys

from . import tex, tools


def resolve_figure_filename(filename, directory):
    candidates = [directory / (filename + extension)
                  for extension in ('', '.pdf', '.eps', '.png', '.jpg', '.jpeg')]
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        raise FileNotFoundError('Missing picture file %s' % (directory / filename))
    if len(candidates) > 1:
        print('Warning: multiple picture files match %s; using %s' %
              (filename, candidates[0]), file=sys.stderr)
    return candidates[0]


def find_tikz_input(source, directory):
    """Inspect literal input/include commands; resolve paths from TeX's cwd.

    Iterative traversal and resolved paths also handle cycles and symlink aliases.
    This check does not expand the input files into the manuscript's count.
    """
    pending = [match[1] for match in tex.command_matches(tex.INPUT_RE, source)]
    seen = set()
    while pending:
        filename = pending.pop().strip()
        path = directory / filename
        if not path.is_file() and not path.suffix:
            path = path.with_suffix('.tex')
        if not path.is_file():
            continue
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        source = tex.mask_comments(path.read_text(encoding='utf-8'))
        if next(tex.command_matches(tex.TIKZ_RE, source), None):
            return path
        pending.extend(match[1] for match in tex.command_matches(tex.INPUT_RE, source))
    return None


def check_no_tikz(document, directory):
    source = document.source
    for figure in document.find_environments(('figure',)):
        body = source[figure.body_start:figure.body_end]
        input_path = find_tikz_input(body, directory)
        if next(tex.command_matches(tex.TIKZ_RE, body), None) or input_path:
            line = source.count('\n', 0, figure.start) + 1
            message = ('TikZ figure near line %d. Build it to a PDF and include '
                       r'it with \includegraphics.' % line)
            if input_path:
                message += ' TikZ was found in %s.' % input_path
            raise ValueError(message)


def line_break_between(source):
    source = tex.remove_comments(source)
    return (re.search(r'\\\\|\\(?:newline|par)\b', source) is not None or
            re.search(r'\n\s*\n', source) is not None)


def combined_dimensions(source, commands, dimensions):
    """Approximate panels as rows, using native dimensions and explicit breaks.

    As in the original implementation, TeX scaling, spacing, and rotation are
    not evaluated. This remains a geometric heuristic, not a layout engine.
    """
    rows = []
    row = []
    for index, (command, dimension) in enumerate(zip(commands, dimensions, strict=True)):
        if index and line_break_between(source[commands[index - 1].end:command.start]):
            rows.append(row)
            row = []
        row.append(dimension)
    if row:
        rows.append(row)
    if not rows:
        raise ValueError('Cannot combine an empty figure')
    row_sizes = [(sum(width for width, _ in row), max(height for _, height in row))
                 for row in rows]
    return max(width for width, _ in row_sizes), sum(height for _, height in row_sizes)


def count_figures_words(document, opts, directory):
    source = document.source
    figures = document.find_environments(('figure',))
    check_no_tikz(document, directory)
    for command in tex.command_matches(tex.GRAPHICS_RE, source):
        if not any(figure.body_start <= command.start() < figure.body_end
                   for figure in figures):
            print('Warning: ignoring includegraphics outside figure environment '
                  'near line %d' % (source.count('\n', 0, command.start()) + 1),
                  file=sys.stderr)

    total = 0.0
    cache = {}
    variables = sorted(dict(opts.var or ()).items(), key=lambda item: -len(item[0]))
    for index, figure in enumerate(figures, 1):
        body = source[figure.body_start:figure.body_end]
        commands = tex.includegraphics_commands(body)
        if not commands:
            continue
        filenames = []
        dimensions = []
        for command in commands:
            filename = command.filename
            for key, value in variables:
                filename = filename.replace(key, value)
            # Literal TeX escapes are not part of the filesystem name.
            filename = re.sub(r'\\([%_#&$])', r'\1', filename)
            if re.search(r'[\\{}]', filename):
                raise ValueError('Unresolved TeX in figure filename %r; use --var key value' %
                                 filename)
            path = resolve_figure_filename(filename, directory)
            filenames.append(filename)
            if path not in cache:
                cache[path] = tools.figure_dimensions(path, opts.figs, timeout=opts.timeout)
            dimensions.append(cache[path])
        width, height = combined_dimensions(body, commands, dimensions)
        tools.validate_dimensions(width, height, ', '.join(filenames))
        aspect = width / height
        if not math.isfinite(aspect) or aspect <= 0:
            raise ValueError('Invalid combined aspect ratio for %s' % ', '.join(filenames))
        words = 600.0 / aspect + 40.0 if figure.name == 'figure*' else 150.0 / aspect + 20.0
        if not math.isfinite(words):
            raise ValueError('Figure word estimate overflowed for %s' % ', '.join(filenames))
        print('Figure %d: %6d words (%.0fx%.0f aspect %.2f, %s)' %
              (index, int(words), width, height, aspect, ', '.join(filenames)))
        total += words
    scaled = total * opts.scale_figs
    if not math.isfinite(scaled):
        raise ValueError('Figure word estimate overflowed; reduce --scale-figs')
    return int(scaled)
