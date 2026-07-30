import subprocess


def ping(host):
    subprocess.call(f"ping -c 1 {host}", shell=True)
