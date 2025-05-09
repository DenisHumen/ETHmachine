import os
import subprocess
import requests
from datetime import datetime
from typing import Tuple

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
    """
    Fetch the latest commit information from the GitHub repository.

    Args:
        github_api_url (str): The GitHub API URL for the repository.

    Returns:
        Tuple[str, str, str]: Commit hash, commit date, and commit message.
    """
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
) -> Tuple[bool, str]:
    """
    Compare local and GitHub versions and generate a message.

    Args:
        local_date (str): Local commit date.
        github_date (str): GitHub commit date.
        local_hash (str): Local commit hash.
        github_hash (str): GitHub commit hash.
        commit_message (str): GitHub commit message.
        repo_name (str): The name of the GitHub repository.

    Returns:
        Tuple[bool, str]: Whether the local version is the latest and the message.
    """
    try:
        github_dt = datetime.fromisoformat(github_date.replace("Z", "+00:00"))
        formatted_date = github_dt.strftime("%d.%m.%Y %H:%M UTC")

        if local_hash == github_hash:
            return (
                True,
                f'\n✅ You are using the latest version!\n'
                f'\n\n📅 Last update:** {formatted_date}\n'
            )

        download_link = f"https://github.com/DenisHumen/{repo_name}"
        return (
            False,
            f"⚠️⚠️⚠️ Update available!\n"
            f"📅 Latest update released: {formatted_date}\n"
            f"ℹ️ To update, use: `git pull`\n"
            f"📥 Or download from: \033]8;;{download_link}\033\\{download_link}\033]8;;\033\\",
        )

    except Exception as e:
        print(f"❌ **Error comparing versions:** {e}")
        return False, "Error comparing versions"

def check_version(repo_name: str):
    """
    Check the local version against the latest version on GitHub.

    Args:
        repo_name (str): The name of the GitHub repository.
    """
    github_api_url = f"https://api.github.com/repos/DenisHumen/{repo_name}/commits/main"

    print(
        f"📥 My GitHub: \033]8;;https://github.com/DenisHumen\033\\https://github.com/DenisHumen\033]8;;\033\\\n"
    )

    local_hash, local_date = get_local_commit_info()
    github_hash, github_date, commit_message = get_github_commit_info(github_api_url)

    if not all([local_hash, local_date, github_hash, github_date]):
        print("❌ **Unable to check version. Missing data.**")
        return

    is_latest, message = compare_versions(local_date, github_date, local_hash, github_hash, commit_message, repo_name)
    print(message)
