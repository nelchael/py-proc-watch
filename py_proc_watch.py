#!/usr/bin/env python3

import argparse
import dataclasses
import datetime
import io
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from typing import List, Tuple

import colorama  # type: ignore
import colorama.ansi  # type: ignore

REMOVE_OTHER_ANSI_SEQS = re.compile(r"\033\[\d*[ABCDEFGJKST]")
REMOVE_ANSI_COLOR_SEQS = re.compile(r"\033\[\d+(;\d+){0,2}m")
INCOMPLETE_ANSI_SEQ = re.compile(r"\033[\[\d;]*$")
PADDING_LINE = f"{colorama.Fore.LIGHTBLACK_EX}~{colorama.Style.RESET_ALL}{colorama.ansi.clear_line(0)}\n"


class PyProcWatchError(Exception):
    pass


@dataclasses.dataclass(init=False)
class CommandResult:
    stdout_lines: List[str]
    exit_status: int = -1
    total_read_bytes: int = 0
    used_bytes: int = 0

    def __init__(self):
        self.stdout_lines = []

    def add_line(self, line: str):
        self.stdout_lines.append(line)
        line_len = len(line)
        self.total_read_bytes += line_len
        self.used_bytes += line_len


def reader_thread_func(command_result: CommandResult, stream: io.TextIOBase, max_lines: int):
    while True:
        if len(command_result.stdout_lines) >= max_lines:
            read_bytes = len(stream.read(io.DEFAULT_BUFFER_SIZE))
            command_result.total_read_bytes += read_bytes
            if read_bytes < io.DEFAULT_BUFFER_SIZE:
                return
        else:
            line = stream.readline()
            if not line:
                return
            command_result.add_line(line)


def get_output(command: List[str], shell: bool, max_lines: int) -> CommandResult:
    if max_lines < 1 or max_lines > 8192:
        raise ValueError(f"Invalid number of maximum lines: {max_lines}")

    with subprocess.Popen(
        command, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="UTF-8"
    ) as proc:
        if proc.stdout is None:
            raise PyProcWatchError("Failed to open child process stdout")

        result = CommandResult()
        reader_thread = threading.Thread(target=reader_thread_func, args=(result, proc.stdout, max_lines))
        reader_thread.start()

        try:
            while (exit_status := proc.poll()) is None:
                pass
            result.exit_status = exit_status
            reader_thread.join()
        finally:
            proc.kill()

        return result


def ansi_aware_line_trim(line: str, max_width: int) -> str:
    if max_width < 1 or max_width > 8192:
        raise ValueError(f"Invalid maximum width: {max_width}")

    line = REMOVE_OTHER_ANSI_SEQS.sub("", line.rstrip())
    if len(REMOVE_ANSI_COLOR_SEQS.sub("", line)) < max_width:
        return line + colorama.ansi.clear_line(0) + "\n"
    else:
        chop_at = max_width
        while len(INCOMPLETE_ANSI_SEQ.sub("", REMOVE_ANSI_COLOR_SEQS.sub("", line[:chop_at]))) < max_width:
            chop_at += 1
        chopped_line = INCOMPLETE_ANSI_SEQ.sub("", line[:chop_at])
        return chopped_line + colorama.Style.RESET_ALL


def check_shell(command: str) -> Tuple[bool, List[str]]:
    if shell_env := os.getenv("SHELL"):
        shell = shell_env if pathlib.Path(shell_env).is_file() else shutil.which(shell_env)
        if not shell:
            raise PyProcWatchError(f"Failed to determine shell, tried {shell_env}")
        return False, [shell, "-c", command]
    else:
        return True, shlex.split(command)


def watch(command: str, interval: float = 1.0, precise: bool = False, show_debug: bool = False):
    if not command:
        raise ValueError(f"Invalid command: {command}")
    if interval < 0.0 or interval >= 24 * 60 * 60:
        raise ValueError(f"Invalid interval value: {interval}")

    if not sys.stdout.isatty():
        raise PyProcWatchError("stdout is not a tty!")

    use_shell, run_command = check_shell(command)
    try:
        while True:
            width, height = os.get_terminal_size()
            if width < 48 or height < 4:
                raise PyProcWatchError(f"Terminal window too small: ({width}x{height}), need at least (48x4)")

            start_time = time.time()
            command_result = get_output(run_command, use_shell, height - 1)
            execution_time = time.time() - start_time

            start_time = time.time()
            buffer = [
                ansi_aware_line_trim(line, width if index + 2 < height else width - 1)
                for index, line in enumerate(command_result.stdout_lines)
            ]
            if len(buffer) < height - 1:
                buffer.extend([PADDING_LINE] * (height - len(buffer) - 1))
            lines_processing_time = time.time() - start_time

            debug_display = ""
            if show_debug:
                debug_display = (
                    f"<<w={width},h={height} "
                    f"B:{command_result.total_read_bytes}->{command_result.used_bytes} "
                    f"{execution_time:0.03f}s+{lines_processing_time:0.03f}s>>"
                )
            status_line_left = f"Every {interval:0.01f}s: {command} (exit status: {command_result.exit_status})"
            status_line_right = debug_display + datetime.datetime.now().strftime(" %H:%M:%S")

            if (status_len := len(status_line_left) + len(status_line_right)) > width:
                status_line_left = status_line_left[: width - len(status_line_right) - 1] + "…"
            else:
                status_line_left = status_line_left + " " * (width - status_len)

            start_time = time.time()
            sys.stdout.write(
                colorama.Cursor.POS(1, 1)
                + colorama.Fore.LIGHTBLACK_EX
                + status_line_left
                + status_line_right
                + colorama.Fore.RESET
                + "".join(buffer).strip()
                + colorama.Cursor.POS(width, height)
            )
            sys.stdout.flush()
            output_write_time = time.time() - start_time

            if precise:
                time.sleep(max(0, interval - execution_time - lines_processing_time - output_write_time))
            else:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass


def main(command_line_args: List[str]):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-n",
        "--interval",
        action="store",
        default="1.0",
        type=float,
        help="seconds to wait between command runs, positive floats and zero are accepted",
    )
    parser.add_argument(
        "-p", "--precise", action="store_true", default=False, help="try to run the command precisely at intervals"
    )
    parser.add_argument("-v", "--debug", action="store_true", default=False, help="show debug information")
    parser.add_argument(
        "command",
        nargs="+",
        help="command to watch, can be specified as a quoted string or as a list "
        "(use -- to separate pywatch and command options)",
    )
    options = parser.parse_args(command_line_args)

    colorama.init()
    watch(
        command=" ".join(options.command), interval=options.interval, precise=options.precise, show_debug=options.debug
    )


def _entry_point():
    main(sys.argv[1:])  # pragma: no cover


if __name__ == "__main__":
    _entry_point()  # pragma: no cover
