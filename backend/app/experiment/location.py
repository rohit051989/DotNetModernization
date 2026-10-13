"""Where an engagement's experiments live: engagement data, outside the repository.

    <RUNS_DIR>/<engagement>/experiments/<name>/   experiment.yaml, RUNBOOK.md, CALIBRATION.md, REPORT.md

Experiments name a client's repositories, branches and results, so they are never committed (CLAUDE.md: git holds
the platform only). RUNS_DIR is settings.runs_path; a client deployment sets it outside the repository.
"""
from pathlib import Path

from app.config import settings


def experiments_dir(engagement_id: str) -> Path:
    return settings.runs_path / engagement_id / "experiments"


def experiment_dir(engagement_id: str, name: str) -> Path:
    return experiments_dir(engagement_id) / name
