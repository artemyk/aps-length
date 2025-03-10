aps-length
==========

(c) James Kermode <james.kermode@gmail.com> 2014

(c) Artemy Kolchinsky <artemyk@gmail.com> 2025


Usage: aps-length [options] tex-files

Count number of equivalent words in an APS manuscript formatted in
LaTeX, following guidelines described at http://journals.aps.org/authors/length-guide

Requires _detex_ (http://www.ctan.org/pkg/detex) and either
_ghostscript_ (http://www.ghostscript.com/) or ImageMagick _identify_
(http://www.imagemagick.org) to be available on your path.

Use `--figs=gs` if you have .eps or .pdf figures, and `--figs=identify` if you have
.png figures.

```
Options:
  -h, --help            show this help message and exit
  -v key value, --var=key value
                        Define TeX variables e.g. to specify location of
                        figure files.
  -e env1,env2,..., --env=env1,env2,...
                        Comma-separated list of LaTeX environments to ignore.
  -x APPENDIX, --appendix=APPENDIX
                        Include text after \appendix environment.
  -m (detex | wordcount), --method=(detex | wordcount)
                        Tool to use to count words in main text. Default is
                        wordcount. detex is also supported (but tends to
                        underestimate word count).
  -f (identify | gs), --figs=(identify | gs)
                        Tool to use to extract bounding box from figure. The
                        default is identify, which works for png, pdf, eps,
                        and most image formats, but requires ImageMagick to be
                        installed. The other option is gs, which works with
                        eps and pdf mages.
  --scale-figs=SCALE_FIGS
                        Scale estimate of figure word counts by factor,
                        default 1.1 (10%)
  -j PRL, --journal=PRL
                        Journal abbreviation (e.g. None, PRL, PRB-RC)
  -l LATEX, --latex=LATEX
                        Latex executable. Default is "pdflatex".
  -o LATEXOPTS, --latexopts=LATEXOPTS
                        Options to latex executable. Default is
                        "-interaction=nonstopmode".
  -i IGNOREERRORS, --ignoreerrors=IGNOREERRORS
                        Try to continue even if LaTeX encounters errors
  --keep_tmp_files      Do not delete temporary latex files after running
                        (useful for debugging)
```
