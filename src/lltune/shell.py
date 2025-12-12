# Copyright (c) 2025 Muhammad Nawaz <m.nawaz2003@gmail.com>
# SPDX-License-Identifier: MIT
"""Shell command execution helper."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import List


logger = logging.getLogger("lltune.shell")


@dataclass
class CmdResult:
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_cmd(
    cmd: List[str], timeout: int = 5, check: bool = False
) -> CmdResult:
    """Execute a shell command with timeout, capturing stdout/stderr."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("Command not found: %s", cmd[0])
        return CmdResult(
            cmd=cmd, returncode=127, stdout="", stderr="command not found"
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "Command timed out after %ss: %s", timeout, " ".join(cmd)
        )
        return CmdResult(cmd=cmd, returncode=124, stdout="", stderr="timeout")

    if proc.returncode != 0:
        logger.debug(
            "Command failed (%s): %s\nstderr: %s",
            proc.returncode,
            " ".join(cmd),
            proc.stderr.strip(),
        )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
        )
    return CmdResult(
        cmd=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
