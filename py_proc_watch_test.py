#!/usr/bin/env python3

import io
import subprocess
import unittest.mock
from typing import List

import colorama  # type: ignore
import colorama.ansi  # type: ignore
import pytest

import py_proc_watch


def test_command_result():
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
    ["buffer", "expected_lines", "max_lines"],
    [
        (io.StringIO("1\n2\n3\n"), ["1\n"], 1),
        (io.StringIO("1\n2\n3\n"), ["1\n", "2\n", "3\n"], 3),
        (io.StringIO("1\n2\n3\n"), ["1\n", "2\n", "3\n"], 100),
        (io.StringIO("1\n2\n3\n" + "filler\n" * io.DEFAULT_BUFFER_SIZE), ["1\n", "2\n"], 2),
    ],
)
def test_reader_thread_func(buffer: io.StringIO, expected_lines: List[str], max_lines: int):
    result = py_proc_watch.CommandResult()
    py_proc_watch.reader_thread_func(result, buffer, max_lines)

    assert result.total_read_bytes == buffer.tell()
    assert result.stdout_lines == expected_lines


@unittest.mock.patch("subprocess.Popen")
def test_get_output_no_stdout(mocked_popen: unittest.mock.Mock):
    process_mock = unittest.mock.MagicMock()
    process_mock.__enter__.return_value = process_mock
    process_mock.stdout = None

    mocked_popen.return_value = process_mock

    with pytest.raises(ValueError, match=r"Invalid number of maximum lines: -1"):
        py_proc_watch.get_output(["a-command"], True, -1)

    with pytest.raises(py_proc_watch.PyProcWatchError, match=r"Failed to open child process stdout"):
        py_proc_watch.get_output(["a-command"], True, 1)

    mocked_popen.assert_called_once_with(
        ["a-command"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="UTF-8"
    )

    process_mock.__enter__.assert_called_once()
    process_mock.__exit__.assert_called_once()


@unittest.mock.patch("subprocess.Popen")
def test_get_output_failure(mocked_popen: unittest.mock.Mock):
    process_mock = unittest.mock.MagicMock()
    process_mock.__enter__.return_value = process_mock
    process_mock.stdout = io.StringIO("No such command\n")
    process_mock.poll.side_effect = [None, 12345]

    mocked_popen.return_value = process_mock

    result = py_proc_watch.get_output(["a-command"], True, 1000)

    mocked_popen.assert_called_once_with(
        ["a-command"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="UTF-8"
    )
    process_mock.__enter__.assert_called_once()
    process_mock.kill.assert_called_once()
    process_mock.__exit__.assert_called_once()

    assert result.exit_status == 12345
    assert result.stdout_lines == ["No such command\n"]


@unittest.mock.patch("subprocess.Popen")
def test_get_output_small(mocked_popen: unittest.mock.Mock):
    process_mock = unittest.mock.MagicMock()
    process_mock.__enter__.return_value = process_mock
    process_mock.stdout = io.StringIO("Command result\nSecond line\nThird line\n")
    process_mock.poll.side_effect = [None, 0]

    mocked_popen.return_value = process_mock

    result = py_proc_watch.get_output(["a-command"], True, 1000)

    mocked_popen.assert_called_once_with(
        ["a-command"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="UTF-8"
    )
    process_mock.__enter__.assert_called_once()
    process_mock.kill.assert_called_once()
    process_mock.__exit__.assert_called_once()

    assert result.exit_status == 0
    assert result.stdout_lines == ["Command result\n", "Second line\n", "Third line\n"]


@unittest.mock.patch("subprocess.Popen")
def test_get_output_large(mocked_popen: unittest.mock.Mock):
    process_mock = unittest.mock.MagicMock()
    process_mock.__enter__.return_value = process_mock
    process_mock.stdout = io.StringIO("Command result\nSecond line\nThird line\n" + "filler\n" * 1024)
    process_mock.poll.side_effect = [None, None, None, 0]

    mocked_popen.return_value = process_mock

    result = py_proc_watch.get_output(["a-command"], True, 3)

    mocked_popen.assert_called_once_with(
        ["a-command"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="UTF-8"
    )
    process_mock.__enter__.assert_called_once()
    process_mock.kill.assert_called_once()
    process_mock.__exit__.assert_called_once()

    assert result.exit_status == 0
    assert result.stdout_lines == ["Command result\n", "Second line\n", "Third line\n"]


def test_ansi_aware_line_trim():
    ST = f"{colorama.Style.RESET_ALL}"

    with pytest.raises(ValueError, match=r"Invalid maximum width: -1"):
        py_proc_watch.ansi_aware_line_trim(None, -1)

    assert py_proc_watch.ansi_aware_line_trim("foo", 80) == f"foo{colorama.ansi.clear_line(0)}\n"
    assert py_proc_watch.ansi_aware_line_trim("f\033[0Koo", 80) == f"foo{colorama.ansi.clear_line(0)}\n"

    assert py_proc_watch.ansi_aware_line_trim("foo", 1) == f"f{ST}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[0Koo", 1) == f"f{ST}"

    assert py_proc_watch.ansi_aware_line_trim("f\033[0Koo", 2) == f"fo{ST}"

    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 1) == f"f{ST}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 2) == f"f\033[30mo{ST}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 3) == f"f\033[30moo{ST}"
    assert py_proc_watch.ansi_aware_line_trim("f\033[30moo", 4) == f"f\033[30moo{colorama.ansi.clear_line(0)}\n"

    assert (
        py_proc_watch.ansi_aware_line_trim(
            "12345678901234567890123456789012345678901234567890123456789012345678901234567890"
            "12345678901234567890123456789012345678901234567890123456789012345678901234567890",
            159,
        )
        == "12345678901234567890123456789012345678901234567890123456789012345678901234567890"
        f"1234567890123456789012345678901234567890123456789012345678901234567890123456789{ST}"
    )


@unittest.mock.patch("shutil.which")
@unittest.mock.patch("pathlib.Path")
@unittest.mock.patch("os.getenv")
def test_check_shell(mock_getenv: unittest.mock.Mock, mock_path: unittest.mock.Mock, mock_which: unittest.mock.Mock):
    mock_getenv.side_effect = [None, "/bin/shell", "shell", "missing-shell"]

    file_mock = unittest.mock.MagicMock()
    file_mock.is_file.return_value = True
    non_file_mock = unittest.mock.MagicMock()
    non_file_mock.is_file.return_value = False

    mock_path.side_effect = [file_mock, non_file_mock, non_file_mock]

    mock_which.side_effect = ["/usr/bin/shell", None]

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

    mock_getenv.assert_called()
    mock_path.assert_called()


def test_watch_invalid_params():
    with pytest.raises(ValueError, match=r"Invalid command: None"):
        py_proc_watch.watch(None)

    with pytest.raises(ValueError, match=r"Invalid interval value: -?[\d\.]+"):
        py_proc_watch.watch("a-command", -0.1)
    with pytest.raises(ValueError, match=r"Invalid interval value: -?[\d\.]+"):
        py_proc_watch.watch("a-command", 24 * 60 * 60 + 1)


@unittest.mock.patch("sys.stdout")
def test_watch_tty_check(mock_stdout: unittest.mock.Mock):
    mock_stdout.isatty.return_value = False

    with pytest.raises(py_proc_watch.PyProcWatchError, match=r"stdout is not a tty!"):
        py_proc_watch.watch("a-command")

    mock_stdout.isatty.assert_called_once()


@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_screen_size_check(mock_stdout: unittest.mock.Mock, mock_get_terminal_size: unittest.mock.Mock):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (47, 3)

    with pytest.raises(
        py_proc_watch.PyProcWatchError, match=r"Terminal window too small: \(47x3\), need at least \(\d+x\d+\)"
    ):
        py_proc_watch.watch("a-command")

    mock_get_terminal_size.assert_called_once()


@unittest.mock.patch("time.sleep")
@unittest.mock.patch("py_proc_watch.get_output")
@unittest.mock.patch("time.time")
@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_normal_call(
    mock_stdout: unittest.mock.Mock,
    mock_get_terminal_size: unittest.mock.Mock,
    mock_time: unittest.mock.Mock,
    mock_get_output: unittest.mock.Mock,
    mock_sleep: unittest.mock.Mock,
):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (50, 4)
    mock_time.side_effect = [
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    ]
    mock_get_output.return_value = py_proc_watch.CommandResult()
    mock_get_output.return_value.exit_status = 123
    mock_get_output.return_value.add_line("1\n")
    mock_get_output.return_value.add_line("2\n")
    mock_get_output.return_value.add_line("3\n")
    mock_get_output.return_value.total_read_bytes *= 2
    mock_sleep.side_effect = KeyboardInterrupt()

    py_proc_watch.watch("a-command")

    mock_stdout.isatty.assert_called_once()
    mock_get_terminal_size.assert_called()
    mock_time.assert_called()
    mock_get_output.assert_called_once_with(unittest.mock.ANY, unittest.mock.ANY, 4 - 1)
    mock_stdout.write.assert_called_once()
    written_out = mock_stdout.write.call_args.args[0]
    assert "Every 1.0s: a-command (exit status: 123)" in written_out
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}" in written_out
    )
    assert written_out.endswith("\033[4;50H")
    mock_stdout.flush.assert_called_once()
    mock_sleep.assert_called_once_with(pytest.approx(1.0))


@unittest.mock.patch("time.sleep")
@unittest.mock.patch("py_proc_watch.get_output")
@unittest.mock.patch("time.time")
@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_normal_call_narrow_header(
    mock_stdout: unittest.mock.Mock,
    mock_get_terminal_size: unittest.mock.Mock,
    mock_time: unittest.mock.Mock,
    mock_get_output: unittest.mock.Mock,
    mock_sleep: unittest.mock.Mock,
):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (48, 4)
    mock_time.side_effect = [
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    ]
    mock_get_output.return_value = py_proc_watch.CommandResult()
    mock_get_output.return_value.exit_status = 1234567
    mock_get_output.return_value.add_line("1\n")
    mock_get_output.return_value.add_line("2\n")
    mock_get_output.return_value.add_line("3\n")
    mock_get_output.return_value.total_read_bytes *= 2
    mock_sleep.side_effect = KeyboardInterrupt()

    py_proc_watch.watch("a-command")

    mock_stdout.isatty.assert_called_once()
    mock_get_terminal_size.assert_called()
    mock_time.assert_called()
    mock_get_output.assert_called_once_with(unittest.mock.ANY, unittest.mock.ANY, 4 - 1)
    mock_stdout.write.assert_called_once()
    written_out = mock_stdout.write.call_args.args[0]
    assert "Every 1.0s: a-command (exit status: 12… " in written_out
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}" in written_out
    )
    assert written_out.endswith("\033[4;48H")
    mock_stdout.flush.assert_called_once()
    mock_sleep.assert_called_once_with(pytest.approx(1.0))


@unittest.mock.patch("time.sleep")
@unittest.mock.patch("py_proc_watch.get_output")
@unittest.mock.patch("time.time")
@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_normal_call_one_line_output(
    mock_stdout: unittest.mock.Mock,
    mock_get_terminal_size: unittest.mock.Mock,
    mock_time: unittest.mock.Mock,
    mock_get_output: unittest.mock.Mock,
    mock_sleep: unittest.mock.Mock,
):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (50, 4)
    mock_time.side_effect = [
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    ]
    mock_get_output.return_value = py_proc_watch.CommandResult()
    mock_get_output.return_value.exit_status = 123
    mock_get_output.return_value.add_line("1\n")
    mock_get_output.return_value.total_read_bytes *= 2
    mock_sleep.side_effect = KeyboardInterrupt()

    py_proc_watch.watch("a-command")

    mock_stdout.isatty.assert_called_once()
    mock_get_terminal_size.assert_called()
    mock_time.assert_called()
    mock_get_output.assert_called_once_with(unittest.mock.ANY, unittest.mock.ANY, 4 - 1)
    mock_stdout.write.assert_called_once()
    written_out = mock_stdout.write.call_args.args[0]
    assert "Every 1.0s: a-command (exit status: 123)" in written_out
    assert (
        f"1{colorama.ansi.clear_line(0)}\n{py_proc_watch.PADDING_LINE}{py_proc_watch.PADDING_LINE.rstrip()}"
        in written_out
    )
    assert written_out.endswith("\033[4;50H")
    mock_stdout.flush.assert_called_once()
    mock_sleep.assert_called_once_with(pytest.approx(1.0))


@unittest.mock.patch("time.sleep")
@unittest.mock.patch("py_proc_watch.get_output")
@unittest.mock.patch("time.time")
@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_precise(
    mock_stdout: unittest.mock.Mock,
    mock_get_terminal_size: unittest.mock.Mock,
    mock_time: unittest.mock.Mock,
    mock_get_output: unittest.mock.Mock,
    mock_sleep: unittest.mock.Mock,
):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (50, 4)
    mock_time.side_effect = [
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    ]
    mock_get_output.return_value = py_proc_watch.CommandResult()
    mock_get_output.return_value.exit_status = 123
    mock_get_output.return_value.add_line("1\n")
    mock_get_output.return_value.add_line("2\n")
    mock_get_output.return_value.add_line("3\n")
    mock_get_output.return_value.total_read_bytes *= 2
    mock_sleep.side_effect = KeyboardInterrupt()

    py_proc_watch.watch("a-command", interval=2.0, precise=True)

    mock_stdout.isatty.assert_called_once()
    mock_get_terminal_size.assert_called()
    mock_time.assert_called()
    mock_get_output.assert_called_once_with(unittest.mock.ANY, unittest.mock.ANY, 4 - 1)
    mock_stdout.write.assert_called_once()
    written_out = mock_stdout.write.call_args.args[0]
    assert "Every 2.0s: a-command (exit status: 123)" in written_out
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}" in written_out
    )
    assert written_out.endswith("\033[4;50H")
    mock_stdout.flush.assert_called_once()
    mock_sleep.assert_called_once_with(pytest.approx(1.4))


@unittest.mock.patch("time.sleep")
@unittest.mock.patch("py_proc_watch.get_output")
@unittest.mock.patch("time.time")
@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_precise_long_command(
    mock_stdout: unittest.mock.Mock,
    mock_get_terminal_size: unittest.mock.Mock,
    mock_time: unittest.mock.Mock,
    mock_get_output: unittest.mock.Mock,
    mock_sleep: unittest.mock.Mock,
):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (50, 4)
    mock_time.side_effect = [
        0.0,
        2.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    ]
    mock_get_output.return_value = py_proc_watch.CommandResult()
    mock_get_output.return_value.exit_status = 123
    mock_get_output.return_value.add_line("1\n")
    mock_get_output.return_value.add_line("2\n")
    mock_get_output.return_value.add_line("3\n")
    mock_get_output.return_value.total_read_bytes *= 2
    mock_sleep.side_effect = KeyboardInterrupt()

    py_proc_watch.watch("a-command", interval=2.0, precise=True)

    mock_stdout.isatty.assert_called_once()
    mock_get_terminal_size.assert_called()
    mock_time.assert_called()
    mock_get_output.assert_called_once_with(unittest.mock.ANY, unittest.mock.ANY, 4 - 1)
    mock_stdout.write.assert_called_once()
    written_out = mock_stdout.write.call_args.args[0]
    assert "Every 2.0s: a-command (exit status: 123)" in written_out
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}" in written_out
    )
    assert written_out.endswith("\033[4;50H")
    mock_stdout.flush.assert_called_once()
    mock_sleep.assert_called_once_with(pytest.approx(0.0))


@unittest.mock.patch("time.sleep")
@unittest.mock.patch("py_proc_watch.get_output")
@unittest.mock.patch("time.time")
@unittest.mock.patch("os.get_terminal_size")
@unittest.mock.patch("sys.stdout")
def test_watch_debug(
    mock_stdout: unittest.mock.Mock,
    mock_get_terminal_size: unittest.mock.Mock,
    mock_time: unittest.mock.Mock,
    mock_get_output: unittest.mock.Mock,
    mock_sleep: unittest.mock.Mock,
):
    mock_stdout.isatty.return_value = True
    mock_get_terminal_size.return_value = (99, 4)
    mock_time.side_effect = [
        0.0,
        0.1,  # Execution time
        0.0,
        0.2,  # Line processing time
        0.0,
        0.3,  # Output write time
    ]
    mock_get_output.return_value = py_proc_watch.CommandResult()
    mock_get_output.return_value.exit_status = 123
    mock_get_output.return_value.add_line("1\n")
    mock_get_output.return_value.add_line("2\n")
    mock_get_output.return_value.add_line("3\n")
    mock_get_output.return_value.total_read_bytes *= 2
    mock_sleep.side_effect = KeyboardInterrupt()

    py_proc_watch.watch("a-command", show_debug=True)

    mock_stdout.isatty.assert_called_once()
    mock_get_terminal_size.assert_called()
    mock_time.assert_called()
    mock_get_output.assert_called_once_with(unittest.mock.ANY, unittest.mock.ANY, 4 - 1)
    mock_stdout.write.assert_called_once()
    written_out = mock_stdout.write.call_args.args[0]
    assert "Every 1.0s: a-command (exit status: 123)" in written_out
    assert (
        f"1{colorama.ansi.clear_line(0)}\n2{colorama.ansi.clear_line(0)}\n3{colorama.ansi.clear_line(0)}" in written_out
    )
    assert written_out.endswith("\033[4;99H")
    assert "<<w=99,h=4 B:12->6 0.100s+0.200s>>" in written_out
    mock_stdout.flush.assert_called_once()
    mock_sleep.assert_called_once_with(pytest.approx(1.0))


@unittest.mock.patch("py_proc_watch.watch")
@unittest.mock.patch("colorama.init")
@pytest.mark.parametrize(
    ["args", "expected_exit_code"],
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
def test_main_no_command(
    mocked_colorama_init: unittest.mock.Mock, mocked_watch: unittest.mock.Mock, args: List[str], expected_exit_code: int
):
    with pytest.raises(SystemExit) as exception_info:
        py_proc_watch.main(args)

    assert exception_info.value.code == expected_exit_code

    mocked_colorama_init.assert_not_called()
    mocked_watch.assert_not_called()


@unittest.mock.patch("py_proc_watch.watch")
@unittest.mock.patch("colorama.init")
@pytest.mark.parametrize(
    ["args", "expected_command", "expected_interval", "expected_precise", "expected_debug"],
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
    mocked_colorama_init: unittest.mock.Mock,
    mocked_watch: unittest.mock.Mock,
    args: List[str],
    expected_command: str,
    expected_interval: float,
    expected_precise: bool,
    expected_debug: bool,
):
    py_proc_watch.main(args)

    mocked_colorama_init.assert_called_once()
    mocked_watch.assert_called_once_with(
        command=expected_command,
        interval=pytest.approx(expected_interval),
        precise=expected_precise,
        show_debug=expected_debug,
    )
