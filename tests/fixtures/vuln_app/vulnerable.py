"""Deliberately vulnerable fixture app — scanner integration test target. DO NOT SHIP."""

import pickle
import subprocess

AWS_KEY = "AKIAQ7Z9W2X5V8B1N4M6"  # gitleaks: aws-access-token
AWS_SECRET = "zR8kLmN3pQ7sT2vW5xY9aB4cD6eF1gH3jK5lM7nP"


def run_user_command(cmd: str) -> None:
    subprocess.call(cmd, shell=True)  # semgrep: subprocess-shell


def load_session(data: bytes):
    return pickle.loads(data)  # semgrep: pickle-loads


def render(template: str):
    return eval(template)  # semgrep: eval-exec


def find_user(cursor, name: str):
    cursor.execute("SELECT * FROM users WHERE name = '%s'" % name)  # semgrep: sql-format
