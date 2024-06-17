#!/usr/bin/env python3

import io
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import List

import colorama
import colorama.ansi
import mockito  # type: ignore
import pytest

import py_proc_watch


def test_command_result() -> None:
    cr = py_proc_watch.CommandResult()

    assert not cr.stdout_lines
    assert cr.exit_status == -1
    assert cr.total_read_bytes == 0
    assert cr.used_bytes == 0

    cr.add_line("foo\n")

    assert cr.stdout_lines
    assert cr.total_read_bytes == len("foo\n")
    assert cr.used_bytes == len("foo\n")

    cr.add_line("foo\n")

    assert cr.stdout_lines
    assert cr.total_read_bytes == len("foo\n") * 2
    assert cr.used_bytes == len("foo\n") * 2


@pytest.mark.parametrize(
    ("buffer", "expected_lines", "max_lines"),
    [
        (io.StringIO("1\n2\n3\n"), ["1\n"], 1),
        (io.StringIO("1\n2\n3\n"), ["1\n", "2\n", "3\n"], 3),
        (io.StringIO("1\n2\n3\n"), ["1\n", "2\n", "3\n"], 100),
        (io.StringIO("1\n2\n3\n" + "filler\n" * io.DEFAULT_BUFFER_SIZE), ["1\n", "2\n"], 2),
    ],
)
def test_reader_thread_func(buffer: io.StringIO, expected_lines: List[str], max_lines: int) -> None:
    result = py_proc_watch.CommandResult()
    py_proc_watch.reader_thread_func(result, buffer, max_lines)

    assert result.total_read_bytes == buffer.tell()
    assert result.stdout_lines == expected_lines


def test_get_output_no_stdout(when: mockito.when) -> None:
    process_mock = mockito.mock({"stdout": None}, spec=subprocess.Popen)
    when(process_mock).__enter__().thenReturn(process_mock)
    when(process_mock).__exit__(*mockito.ARGS)

    when(subprocess).Popen(
        ["a-command"],
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="UTF-8",
        errors="backslashreplace",
    ).thenReturn(process_mock)

    with pytest.raises(ValueError, match=r"Invalid number of maximum lines: -1"):
        py_proc_watch.get_output(["a-command"], True, -1)

    with pytest.raises(py_proc_watch.PyProcWatchError, match=r"Failed to open child process stdout"):
        py_proc_watch.get_output(["a-command"], True, 1)


def test_get_output_failure(when: mockito.when) -> None:
    process_mock = mockito.mock({"stdout": io.StringIO("No such command\n")}, spec=subprocess.Popen)
    when(process_mock).__enter__().thenReturn(process_mock)
    when(process_mock).__exit__(*mockito.ARGS)
    when(process_mock).poll().thenReturn(None, 12345)
    when(process_mock).kill()

    when(subprocess).Popen(
        ["a-command"],
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="UTF-8",
        errors="backslashreplace",
    ).thenReturn(process_mock)

    result = py_proc_watch.get_output(["a-command"], True, 1000)

    assert result.exit_status == 12345
    assert result.stdout_lines == ["No such command\n"]


def test_get_output_small(when: mockito.when) -> None:
    process_mock = mockito.mock(
        {"stdout": io.StringIO("Command result\nSecond line\nThird line\n")}, spec=subprocess.Popen
    )
    when(process_mock).__enter__().thenReturn(process_mock)
    when(process_mock).__exit__(*mockito.ARGS)
    when(process_mock).poll().thenReturn(None, 0)
    when(process_mock).kill()

    when(subprocess).Popen(
        ["a-command"],
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="UTF-8",
        errors="backslashreplace",
    ).thenReturn(process_mock)

    result = py_proc_watch.get_output(["a-command"], True, 1000)

    assert result.exit_status == 0
    assert result.stdout_lines == ["Command result\n", "Second line\n", "Third line\n"]


def test_get_output_large(when: mockito.when) -> None:
    process_mock = mockito.mock(
        {"stdout": io.StringIO("Command result\nSecond line\nThird line\n" + "filler\n" * 1024)}, spec=subprocess.Popen
    )
    when(process_mock).__enter__().thenReturn(process_mock)
    when(process_mock).__exit__(*mockito.ARGS)
    when(process_mock).poll().thenReturn(None, None, None, 0)
    when(process_mock).kill()

    when(subprocess).Popen(
        ["a-command"],
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="UTF-8",
        errors="backslashreplace",
    ).thenReturn(process_mock)

    result = py_proc_watch.get_output(["a-command"], True, 3)

    assert result.exit_status == 0
    assert result.stdout_lines == ["Command result\n", "Second line\n", "Third line\n"]


def test_ansi_aware_line_trim() -> None:
    st = f"{colorama.Style.RESET_ALL}"

    with pytest.raises(ValueError, match=r"Invalid maximum width: -1"):
        py_proc_watch.ansi_aware_line_trim("", -1)

    assert py_proc_watch.ansi_aware_line_trim("foo", 80) == f"foo{colorama.ansi.clear_line(0)}\n"
    assert py_proc_watch.ansi_aware_line_trim("f\033[0Koo", 80) == f"foo{colorama.ansi.clear_line(0)}\n"

    assert py_proc_watch.ansi_aware_line_trim("foo", 1) == f"f{st}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[0Koo", 1) == f"f{st}"

    assert py_proc_watch.ansi_aware_line_trim("f\033[0Koo", 2) == f"fo{st}"

    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 1) == f"f{st}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 2) == f"f\033[30mo{st}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 3) == f"f\033[30moo{st}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 4) == f"f\033[30moo{colorama.ansi.clear_line(0)}\n"

    assert (
        py_proc_watch.ansi_aware_line_trim(
            "12345678901234567890123456789012345678901234567890123456789012345678901234567890"
            "12345678901234567890123456789012345678901234567890123456789012345678901234567890",
            159,
        )
        == "12345678901234567890123456789012345678901234567890123456789012345678901234567890"
        f"1234567890123456789012345678901234567890123456789012345678901234567890123456789{st}"
    )


def test_check_shell(when: mockito.when) -> None:
    when(os).getenv("SHELL").thenReturn(None, "/bin/shell", "shell", "missing-shell")

    file_mock = mockito.mock({"is_file": lambda: True}, spec=pathlib.Path)
    non_file_mock = mockito.mock({"is_file": lambda: False}, spec=pathlib.Path)

    when(pathlib).Path("/bin/shell").thenReturn(file_mock)
    when(pathlib).Path("shell").thenReturn(non_file_mock)
    when(pathlib).Path("missing-shell").thenReturn(non_file_mock)

    when(shutil).which("shell").thenReturn("/usr/bin/shell")
    when(shutil).which("missing-shell").thenReturn(None)

    use_shell, cmd = py_proc_watch.check_shell("kubectl get pod")
    assert use_shell
    assert cmd == ["kubectl", "get", "pod"]

    use_shell, cmd = py_proc_watch.check_shell("kubectl get pod")
    assert not use_shell
    assert cmd == ["/bin/shell", "-c", "kubectl get pod"]

    use_shell, cmd = py_proc_watch.check_shell("kubectl get pod")
    assert not use_shell
    assert cmd == ["/usr/bin/shell", "-c", "kubectl get pod"]

    with pytest.raises(py_proc_watch.PyProcWatchError, match=r"Failed to determine shell, tried missing-shell"):
        py_proc_watch.check_shell("kubectl get pod")


def test_watch_invalid_params() -> None:
    with pytest.raises(ValueError, match=r"Invalid command: "):
        py_proc_watch.watch("")

    with pytest.raises(ValueError, match=r"Invalid interval value: -?[\d\.]+"):
        py_proc_watch.watch("a-command", -0.1)
    with pytest.raises(ValueError, match=r"Invalid interval value: -?[\d\.]+"):
        py_proc_watch.watch("a-command", 24 * 60 * 60 + 1)


def test_watch_tty_check(when: mockito.when) -> None:
    when(sys.stdout).isatty().thenReturn(False)

    with pytest.raises(py_proc_watch.PyProcWatchError, match=r"stdout is not a tty!"):
        py_proc_watch.watch("a-command")


def test_watch_screen_size_check(when: mockito.when) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((47, 3))

    with pytest.raises(
        py_proc_watch.PyProcWatchError, match=r"Terminal window too small: \(47x3\), need at least \(\d+x\d+\)"
    ):
        py_proc_watch.watch("a-command")


def test_watch_normal_call(when: mockito.when, expect: mockito.expect) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((50, 4))
    when(time).time().thenReturn(
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    )
    command_result = py_proc_watch.CommandResult()
    command_result.exit_status = 0
    command_result.add_line("1\n")
    command_result.add_line("2\n")
    command_result.add_line("3\n")
    command_result.total_read_bytes *= 2
    when(py_proc_watch).get_output(mockito.ANY, mockito.ANY, 4 - 1).thenReturn(command_result)
    expect(time, times=1).sleep(pytest.approx(1)).thenRaise(KeyboardInterrupt)
    written_output = mockito.matchers.captor()
    expect(sys.stdout, times=1).write(written_output)

    py_proc_watch.watch("a-command")

    assert written_output.value.startswith(
        f"{colorama.Cursor.POS(1, 1)}{colorama.Fore.LIGHTBLACK_EX}Every 1.0s: a-command (exit status: 0) "
    )
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}"
        in written_output.value
    )
    assert written_output.value.endswith("\033[4;50H")


def test_watch_normal_call_narrow_header(when: mockito.when, expect: mockito.expect) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((48, 4))
    when(time).time().thenReturn(
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    )
    command_result = py_proc_watch.CommandResult()
    command_result.exit_status = 1234567
    command_result.add_line("1\n")
    command_result.add_line("2\n")
    command_result.add_line("3\n")
    command_result.total_read_bytes *= 2
    when(py_proc_watch).get_output(mockito.ANY, mockito.ANY, 4 - 1).thenReturn(command_result)
    expect(time, times=1).sleep(pytest.approx(1)).thenRaise(KeyboardInterrupt)
    written_output = mockito.matchers.captor()
    expect(sys.stdout, times=1).write(written_output)

    py_proc_watch.watch("a-command")

    assert written_output.value.startswith(
        f"{colorama.Cursor.POS(1, 1)}{colorama.Fore.LIGHTRED_EX}Every 1.0s: a-command (exit status: 12… "
    )
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}"
        in written_output.value
    )
    assert written_output.value.endswith("\033[4;48H")


def test_watch_normal_call_one_line_output(when: mockito.when, expect: mockito.expect) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((50, 4))
    when(time).time().thenReturn(
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    )
    command_result = py_proc_watch.CommandResult()
    command_result.exit_status = 123
    command_result.add_line("1\n")
    command_result.total_read_bytes *= 2
    when(py_proc_watch).get_output(mockito.ANY, mockito.ANY, 4 - 1).thenReturn(command_result)
    expect(time, times=1).sleep(pytest.approx(1)).thenRaise(KeyboardInterrupt)
    written_output = mockito.matchers.captor()
    expect(sys.stdout, times=1).write(written_output)

    py_proc_watch.watch("a-command")

    assert written_output.value.startswith(
        f"{colorama.Cursor.POS(1, 1)}{colorama.Fore.LIGHTRED_EX}Every 1.0s: a-command (exit status: 123) "
    )
    assert (
        f"1{colorama.ansi.clear_line(0)}\n{py_proc_watch.PADDING_LINE}{py_proc_watch.PADDING_LINE.rstrip()}"
        in written_output.value
    )
    assert written_output.value.endswith("\033[4;50H")


def test_watch_precise(when: mockito.when, expect: mockito.expect) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((50, 4))
    when(time).time().thenReturn(
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    )
    command_result = py_proc_watch.CommandResult()
    command_result.exit_status = 0
    command_result.add_line("1\n")
    command_result.add_line("2\n")
    command_result.add_line("3\n")
    command_result.total_read_bytes *= 2
    when(py_proc_watch).get_output(mockito.ANY, mockito.ANY, 4 - 1).thenReturn(command_result)
    expect(time, times=1).sleep(pytest.approx(1.4)).thenRaise(KeyboardInterrupt)
    written_output = mockito.matchers.captor()
    expect(sys.stdout, times=1).write(written_output)

    py_proc_watch.watch("a-command", interval=2.0, precise=True)

    assert written_output.value.startswith(
        f"{colorama.Cursor.POS(1, 1)}{colorama.Fore.LIGHTBLACK_EX}Every 2.0s: a-command (exit status: 0) "
    )
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}"
        in written_output.value
    )
    assert written_output.value.endswith("\033[4;50H")


def test_watch_precise_long_command(when: mockito.when, expect: mockito.expect) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((50, 4))
    when(time).time().thenReturn(
        0.0,
        2.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    )
    command_result = py_proc_watch.CommandResult()
    command_result.exit_status = 123
    command_result.add_line("1\n")
    command_result.add_line("2\n")
    command_result.add_line("3\n")
    command_result.total_read_bytes *= 2
    when(py_proc_watch).get_output(mockito.ANY, mockito.ANY, 4 - 1).thenReturn(command_result)
    expect(time, times=1).sleep(pytest.approx(0)).thenRaise(KeyboardInterrupt)
    written_output = mockito.matchers.captor()
    expect(sys.stdout, times=1).write(written_output)

    py_proc_watch.watch("a-command", interval=2.0, precise=True)

    assert written_output.value.startswith(
        f"{colorama.Cursor.POS(1, 1)}{colorama.Fore.LIGHTRED_EX}Every 2.0s: a-command (exit status: 123) "
    )
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}"
        in written_output.value
    )
    assert written_output.value.endswith("\033[4;50H")


def test_watch_debug(when: mockito.when, expect: mockito.expect) -> None:
    when(sys.stdout).isatty().thenReturn(True)
    when(os).get_terminal_size().thenReturn((99, 4))
    when(time).time().thenReturn(
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    )
    command_result = py_proc_watch.CommandResult()
    command_result.exit_status = 123
    command_result.add_line("1\n")
    command_result.add_line("2\n")
    command_result.add_line("3\n")
    command_result.total_read_bytes *= 2
    when(py_proc_watch).get_output(mockito.ANY, mockito.ANY, 4 - 1).thenReturn(command_result)
    expect(time, times=1).sleep(pytest.approx(1)).thenRaise(KeyboardInterrupt)
    written_output = mockito.matchers.captor()
    expect(sys.stdout, times=1).write(written_output)

    py_proc_watch.watch("a-command", show_debug=True)

    assert written_output.value.startswith(
        f"{colorama.Cursor.POS(1, 1)}{colorama.Fore.LIGHTRED_EX}Every 1.0s: a-command (exit status: 123) "
    )
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}"
        in written_output.value
    )
    assert written_output.value.endswith("\033[4;99H")
    assert "<<w=99,h=4 B:12->6 0.100s+0.200s>>" in written_output.value


@pytest.mark.parametrize(
    ("args", "expected_exit_code"),
    [
        ([], 2),
        (["-h"], 0),
        (["--help"], 0),
        (["-h", "whoami"], 0),
        (["--help", "whoami"], 0),
        (["-p"], 2),
        (["--precise"], 2),
        (["-n"], 2),
        (["-n", "whoami"], 2),
        (["-n", "0.1"], 2),
        (["--interval"], 2),
        (["--interval", "whoami"], 2),
        (["--interval", "0.1"], 2),
        (["-v"], 2),
        (["--debug"], 2),
    ],
    ids=str,
)
def test_main_no_command(expect: mockito.expect, args: List[str], expected_exit_code: int) -> None:
    expect(colorama, times=0).just_fix_windows_console()
    expect(py_proc_watch, times=0).watch(mockito.ANY)

    with pytest.raises(SystemExit) as exception_info:
        py_proc_watch.main(args)

    assert exception_info.value.code == expected_exit_code


@pytest.mark.parametrize(
    ("args", "expected_command", "expected_interval", "expected_precise", "expected_debug"),
    [
        (["whoami"], "whoami", 1.0, False, False),
        (["-p", "whoami"], "whoami", 1.0, True, False),
        (["-p", "whoami", "-v"], "whoami", 1.0, True, True),
        (["-v", "--", "whoami", "-p"], "whoami -p", 1.0, False, True),
        (["-v", "whoami -p"], "whoami -p", 1.0, False, True),
        (["-n", "0.3333333333333333", "whoami"], "whoami", 1 / 3, False, False),
    ],
    ids=str,
)
def test_main_with_command(
    expect: mockito.expect,
    args: List[str],
    expected_command: str,
    expected_interval: float,
    expected_precise: bool,
    expected_debug: bool,
) -> None:
    expect(colorama, times=1).just_fix_windows_console()
    expect(py_proc_watch, times=1).watch(
        command=expected_command,
        interval=pytest.approx(expected_interval),
        precise=expected_precise,
        show_debug=expected_debug,
    )

    py_proc_watch.main(args)
