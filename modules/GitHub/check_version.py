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

def get_github_commit_info(github_api_url: str):
    """
    Возвращает список коммитов (от последнего до первого), каждый как dict:
    {'sha': ..., 'date': ..., 'message': ...}
    """
    try:
        commits = []
        page = 1
        while True:
            url = github_api_url + f"?per_page=100&page={page}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            commit_data = response.json()
            if not commit_data:
                break
            for c in commit_data:
                commits.append({
                    "sha": c["sha"],
                    "date": c["commit"]["committer"]["date"],
                    "message": c["commit"]["message"]
                })
            if len(commit_data) < 100:
                break
            page += 1
        return commits
    except requests.exceptions.Timeout:
        print("❌ **Error fetching GitHub version:** Request timed out. Please check your internet connection.")
        return []
    except requests.exceptions.ConnectionError as e:
        print(f"❌ **Error fetching GitHub version:** Connection error. {e}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"❌ **Error fetching GitHub version:** {e}")
        return []

def compare_versions_and_collect_updates(local_hash: str, commits: list):
    """
    Возвращает (is_latest, updates_list)
    updates_list: список dict с ключами version, date, message
    """
    updates = []
    found_local = False
    for c in commits:
        github_dt = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
        formatted_date = github_dt.strftime("%d.%m.%Y")
        version = github_dt.strftime("%#m.%d.%y") if os.name == "nt" else github_dt.strftime("%-m.%d.%y")
        if not version or version.startswith("%"):
            version = github_dt.strftime("%m.%d.%y").lstrip("0")
        updates.append({
            "sha": c["sha"],
            "version": version,
            "date": formatted_date,
            "message": c["message"]
        })
        if c["sha"] == local_hash:
            found_local = True
            break
    is_latest = (len(updates) == 0) or (updates[0]["sha"] == local_hash)
    return is_latest, updates

def check_version(repo_name: str):
    github_api_url = f"https://api.github.com/repos/DenisHumen/{repo_name}/commits/main"
    github_api_commits_url = f"https://api.github.com/repos/DenisHumen/{repo_name}/commits"

    os.system('cls' if os.name == 'nt' else 'clear')  # Clear the console
    print("🔍 Checking for updates...")

    local_hash, local_date = get_local_commit_info()
    if not local_hash:
        print("❌ **Unable to check version. Missing local commit data.**")
        return

    commits = get_github_commit_info(github_api_commits_url)
    if not commits:
        print("❌ **Unable to check version. No commit data from GitHub.**")
        return

    is_latest, updates = compare_versions_and_collect_updates(local_hash, commits)

    if is_latest:
        print('\n✅ You are using the latest version!\n\n📅 Last update: {}'
              .format(updates[0]["date"] if updates else ""))
        return

    print(f"🔋 New version {updates[0]['version']} available")
    print("+---------+---------------+------------------------------------------------+")
    print("| Version |  Release Date |                    Changes                     |")
    print("+---------+---------------+------------------------------------------------+")
    for upd in updates:
        changes = [line.strip() for line in (upd["message"] or "").split('\n') if line.strip()]
        if not changes:
            changes = ["No description"]
        for idx, line in enumerate(changes):
            if idx == 0:
                print(f"| {upd['version']:<7} | 📅 {upd['date']:<11} | {line:<46} |")
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
