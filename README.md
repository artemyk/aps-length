aps-length
==========

(c) James Kermode <james.kermode@gmail.com> 2014

(c) Artemy Kolchinsky <artemyk@gmail.com> 2025


Estimate the equivalent word count of an APS manuscript in LaTeX, including
displayed equations, figures, and tables. The counting formulas come from the
original implementation; see the [APS length guide](https://journals.aps.org/authors/length-guide).
Journal limits supplied by `--journal` are historical values recorded in 2017,
not automatically updated policy.

Usage
-----

Python 3.10 or later is required. Run the checkout directly:

```sh
./aps-length path/to/manuscript.tex
python -m aps_length path/to/manuscript.tex
./aps-length --method=detex --figs=gs manuscript.tex
./aps-length --stop-comment='' --appendix manuscript.tex
./aps-length --var '\figdir' figures manuscript.tex
```

Keep the `aps_length/` directory beside the launcher. For an installed command,
run `python -m pip install .` from the checkout. The Python package has no
mandatory third-party Python dependencies.

Paths may be absolute or relative to the calling directory. Figure paths and
LaTeX inputs are resolved from each manuscript's directory. Multiple manuscripts
are processed independently; a failed manuscript does not prevent later files
from being checked. Exit status is 0 on success, 1 if a manuscript fails, and 2
for invalid command-line arguments. Diagnostics go to stderr.

Dependencies
------------

Only tools needed for the selected backend and figures are required:

- `wordcount` (default): `pdflatex` and the manuscript's TeX packages. BibTeX is
  invoked when the generated auxiliary file contains citations, bibliography
  data, and a bibliography style. `wordcount.tex` is bundled as package data.
- `detex`: [detex](https://www.ctan.org/pkg/detex). This backend is faster but
  can underestimate the text count.
- Raster figures: ImageMagick `identify` by default.
- EPS figures: Ghostscript with `--figs=gs`.
- PDF figures: PyMuPDF when available, otherwise Ghostscript with a warning.
  PDFs always use this selection regardless of `--figs`. The first page is used.

Important options
-----------------

Run `./aps-length --help` for the complete option list.

| Option | Meaning |
| --- | --- |
| `-v KEY VALUE`, `--var KEY VALUE` | Literal substitution in figure filenames; repeat for multiple variables. |
| `-e LIST`, `--env LIST` | Comma-separated environments omitted from the text count in either backend. Replaces the default list. |
| `-x`, `--appendix` | Include the appendix. Bibliography text remains excluded. |
| `--stop-comment TEXT` | Stop before a line with a comment containing TEXT. Default: `!STOP-APS-LENGTH!`; empty disables. |
| `-m METHOD`, `--method METHOD` | `wordcount` (default) or `detex`. |
| `-f METHOD`, `--figs METHOD` | `identify` (default) or `gs` for non-PDF figures. |
| `--scale-figs FACTOR` | Finite, nonnegative multiplier on the total figure estimate; default 1.1. |
| `-j JOURNAL`, `--journal JOURNAL` | Compare against a historical journal limit. Default: no comparison. |
| `-l COMMAND`, `--latex COMMAND` | LaTeX executable or quoted command; default `pdflatex`. |
| `-o OPTIONS`, `--latexopts=OPTIONS` | Quoted LaTeX arguments; default `-halt-on-error`. Use `=` for a value beginning with `-`. |
| `-i`, `--ignoreerrors` | Continue after LaTeX/BibTeX errors when a count log can still be produced. Counts may be incomplete. |
| `--timeout SECONDS` | Positive, finite timeout per external command; default 120 seconds. |
| `--keep-tmp-files`, `--keep_tmp_files` | Retain temporary files and print their directory. |

By default, the text count excludes abstracts, acknowledgments, bibliography
environments, and displayed math. Table cells are omitted while captions remain.
Hyphenated compounds count as multiple words. Temporary TeX sources, logs,
bibliographies, and other build outputs are isolated in a temporary directory;
SyncTeX is enabled. Cleanup also runs after errors and interruptions.

Estimates and limitations
-------------------------

The parser recognizes literal commands and nested environments, including
multiline arguments, comments, starred forms, and multiple commands on one line.
Mismatched literal environments and invalid figure dimensions produce errors.

- Displayed math contributes 16 words per row, or 32 inside `widetext`. A trailing
  row separator does not create an extra row. Nested arrays contribute their
  height to the enclosing row.
- A `table` or `table*` float is counted once using its `tabular`, `tabular*`, or
  `tabularx` rows. Unsupported table bodies produce an error. Captions contribute
  to the text count; REVTeX-generated table labels can also contribute words.
- A figure float is counted once. Multiple panels are approximated as rows,
  separated by explicit line/paragraph breaks. The estimate uses native image
  dimensions; TeX widths, heights, rotations, panel spacing, and mixed image
  units are not evaluated. Inspect complex layouts manually.
- Inline TikZ in a figure, including TikZ found through literal braced
  `\input`/`\include` commands, is rejected. Build it to PDF and use
  `\includegraphics`. Graphics outside figure floats are ignored with a warning.
- Structural counts inspect the main file, without macro expansion or expansion
  of included files. Text backends may read included files, but equations,
  figures, and tables in those files are not added to the structural estimates.
  Use a flattened manuscript for these cases. TeX conditionals, verbatim text,
  and commands generated by macros are not interpreted.
- The abstract length is a source-character estimate excluding delimiters,
  comments, and boundary whitespace. It includes literal TeX markup.

Development
-----------

`aps_length/tex.py` handles source parsing; `tools.py` handles subprocesses and
image metadata; `figures.py` handles figure estimates; `counting.py` handles text,
math, and tables; `cli.py` handles arguments and reports. The launcher contains
no counting logic. The bundled `aps_length/wordcount.tex` is the only copy.

After preprocessing, `tex.ParsedSource` builds a shared environment index for
the manuscript. Every counter uses this index, so nesting and matching are
validated consistently. `tex.iter_rows` handles row syntax; the counters only
evaluate row heights and apply the word-equivalent formulas. Text filtering
preserves source offsets until the LaTeX backend adds its document-class option.

```sh
python -m unittest discover -v
# Or, if pytest is already installed:
python -m pytest -q
```

The tests use the standard library. Most mock external commands; integration
tests run real tools when available and skip when their dependencies are absent.
