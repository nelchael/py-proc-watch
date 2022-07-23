# py-proc-watch

Library and command line tool for watching process output. This is more or less a simpler version of `watch` from [procps](https://gitlab.com/procps-ng/procps).

The main differences come from defaults:

* `py-proc-watch` always trims long lines so they fit on the screen
* `py-proc-watch` respects color ANSI escape sequences (but strips the rest)
* Python or C for the implementation

## Design goals

`py-proc-watch` library and tool should be:

1. simple
2. fast for very long output of executed command
3. easily tested for correct behavior
4. pure Python to maximize the amount of supported systems
5. easy to use in other tools

## Usage

`pywatch` command line tool supports only a few command line options to keep it simple:

```text
usage: pywatch.py [-h] [-n INTERVAL] [-p] [-v] command [command ...]

positional arguments:
  command               command to watch, can be specified as a quoted string or as a list (use -- to separate pywatch and command options)

options:
  -h, --help            show this help message and exit
  -n INTERVAL, --interval INTERVAL
                        seconds to wait between command runs, positive floats and zero are accepted
  -p, --precise         try to run the command precisely at intervals
  -v, --debug           show debug information
```

`py_proc_watch` can be used also as a Python module to provide "watch-like" functionality easily. The library is quite simple, so just read the source and tests.

## Development

`py-proc-watch` uses [Python Poetry](https://python-poetry.org/) to manage dependencies.

Used tools:

* [`isort`](https://pypi.org/project/isort/) for keeping imports sane
* [`black`](https://pypi.org/project/black/) for enforcing a consistent code style
* [`flake8`](https://pypi.org/project/flake8/) with [`pyproject-flake8`](https://pypi.org/project/pyproject-flake8/) for linting with `pyproject.toml` support
* [`mypy`](https://pypi.org/project/mypy/) for type checking
* [`pytest`](https://pypi.org/project/pytest/) for running test

The _magic_ incantation:

```shell
poetry run isort . && poetry run black . && poetry run pflake8 . && poetry run mypy . && poetry run pytest
```

will run all of the above tools for you.

## Contributing and reporting issues

Please use GitHub Issues and Pull requests. If you're contributing code please see [Development](#development) section.

## License

MIT, see [LICENSE.md](./LICENSE.md) for full text. This is very permissive license, see following pages for more information:

* [Open Source Initiative page about MIT license](https://opensource.org/licenses/MIT)
* [tl;drLegal page about MIT license](https://tldrlegal.com/license/mit-license)
