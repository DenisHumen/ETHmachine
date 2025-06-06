import os
import subprocess
import requests
from datetime import datetime
from typing import Tuple
from questionary import select, Choice

def get_local_commit_info() -> Tuple[str, str]:
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__)
        ).decode("utf-8").strip()

        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI"], cwd=os.path.dirname(__file__)
        ).decode("utf-8").strip()

        return commit_hash, commit_date
    except subprocess.CalledProcessError as e:
        print(f"❌ **Error retrieving local commit info:** {e}")
        return None, None

def get_github_commit_info(github_api_url: str) -> Tuple[str, str, str]:
    try:
        response = requests.get(github_api_url, timeout=10)  # Add a timeout to prevent hanging
        response.raise_for_status()
        commit_data = response.json()
        commit_hash = commit_data["sha"]
        commit_date = commit_data["commit"]["committer"]["date"]
        commit_message = commit_data["commit"]["message"]
        return commit_hash, commit_date, commit_message
    except requests.exceptions.Timeout:
        print("❌ **Error fetching GitHub version:** Request timed out. Please check your internet connection.")
        return None, None, None
    except requests.exceptions.ConnectionError as e:
        print(f"❌ **Error fetching GitHub version:** Connection error. {e}")
        return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"❌ **Error fetching GitHub version:** {e}")
        return None, None, None

def compare_versions(
    local_date: str,
    github_date: str,
    local_hash: str,
    github_hash: str,
    commit_message: str,
    repo_name: str,
) -> Tuple[bool, str, str, str]:
    try:
        github_dt = datetime.fromisoformat(github_date.replace("Z", "+00:00"))
        formatted_date = github_dt.strftime("%d.%m.%Y")
        # Кроссплатформенно: без %-m (Windows не поддерживает %-m)
        version = github_dt.strftime("%#m.%d.%y") if os.name == "nt" else github_dt.strftime("%-m.%d.%y")
        # Если не сработало, fallback на обычный формат
        if not version or version.startswith("%"):
            version = github_dt.strftime("%m.%d.%y").lstrip("0")
        if local_hash == github_hash:
            return (
                True,
                f'\n✅ You are using the latest version!\n\n📅 Last update: {formatted_date}\n',
                "",
                ""
            )
        return (
            False,
            version,
            formatted_date,
            commit_message
        )
    except Exception as e:
        print(f"❌ **Error comparing versions:** {e}")
        return False, "", "", ""

def check_version(repo_name: str):
    github_api_url = f"https://api.github.com/repos/DenisHumen/{repo_name}/commits/main"

    os.system('cls' if os.name == 'nt' else 'clear')  # Clear the console
    print("🔍 Checking for updates...")

    local_hash, local_date = get_local_commit_info()
    github_hash, github_date, commit_message = get_github_commit_info(github_api_url)

    if not all([local_hash, local_date, github_hash, github_date]):
        print("❌ **Unable to check version. Missing data.**")
        return

    is_latest, version, formatted_date, commit_message = compare_versions(
        local_date, github_date, local_hash, github_hash, commit_message, repo_name
    )

    if is_latest:
        print(version)
        return

    # Формируем таблицу изменений
    print(f"🔋 New version {version} available")
    print("+---------+---------------+------------------------------------------------+")
    print("| Version |  Release Date |                    Changes                     |")
    print("+---------+---------------+------------------------------------------------+")
    changes = [line.strip() for line in (commit_message or "").split('\n') if line.strip()]
    if not changes:
        changes = ["No description"]
    for idx, line in enumerate(changes):
        if idx == 0:
            print(f"| {version or '':<7} | 📅 {formatted_date or '':<11} | {line:<46} |")
        else:
            print(f"| {'':<7} | {'':<13} | {line:<46} |")
    print("+---------+---------------+------------------------------------------------+")

    answer = select(
        "🛠️ Do you want to update?",
        choices=[
            Choice("⚠️ No, continue without updating", "no"),
            Choice("🆙 Yes, update to the latest version", "yes"),
        ],
        qmark="🛠️",
        pointer="👉"
    ).ask()

    if answer == "yes":
        print("🆙 Running: git pull")
        os.system("git pull")
        print("✅ Update complete. Please restart the script.")
        exit(0)
    else:
        print("⚠️ Continuing without updating.")
