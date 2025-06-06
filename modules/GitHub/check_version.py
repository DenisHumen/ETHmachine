import os
import subprocess
import requests
from datetime import datetime
from typing import Tuple
from questionary import select, Choice
import textwrap

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

def get_local_version_from_file():
    version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "db", "version")
    if os.path.exists(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return None
    return None

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

def wrap_text(text, width):
    # textwrap.wrap не добавляет пробелы, если строка короче width, поэтому дополняем вручную
    lines = textwrap.wrap(text, width=width) or [""]
    return lines

def calc_table_width(updates, min_width=78):
    # Определяем максимальную ширину для каждого столбца
    version_col = 10
    date_col = 15
    changes_col = 20  # стартовое значение

    for upd in updates:
        changes = [line.strip() for line in (upd["message"] or "").split('\n') if line.strip()]
        for line in changes:
            for part in textwrap.wrap(line, 100):
                changes_col = max(changes_col, len(part))
    # Итоговая ширина таблицы
    total = 4 + version_col + date_col + changes_col  # 4 = | + spaces
    return max(total, min_width), version_col, date_col, changes_col

def print_border(width):
    print("+" + "-" * (width - 2) + "+")

def print_row(version, date, change, version_col, date_col, changes_col, width):
    # Все столбцы строго по ширине, правая стенка всегда ровная
    print(f"| {version:<{version_col-1}}| {date:<{date_col-1}}| {change:<{changes_col}}|".ljust(width-1) + "|")

def check_version(repo_name: str):
    github_api_url = f"https://api.github.com/repos/DenisHumen/{repo_name}/commits/main"
    github_api_commits_url = f"https://api.github.com/repos/DenisHumen/{repo_name}/commits"

    os.system('cls' if os.name == 'nt' else 'clear')  # Clear the console
    print("🔍 Checking for updates...")

    local_hash, local_date = get_local_commit_info()
    if not local_hash:
        print("❌ **Unable to check version. Missing local commit data.**")
        return

    # Получаем локальную версию из файла db/version (если есть)
    local_version_file = get_local_version_from_file()
    if local_version_file:
        print(f"📦 Local version from db/version: {local_version_file}")

    commits = get_github_commit_info(github_api_commits_url)
    if not commits:
        print("❌ **Unable to check version. No commit data from GitHub.**")
        return

    is_latest, updates = compare_versions_and_collect_updates(local_hash, commits)

    # Вычисляем ширину таблицы динамически
    frame_width, version_col, date_col, changes_col = calc_table_width(updates, min_width=78)

    if is_latest:
        print('\n✅ You are using the latest version!\n\n📅 Last update: {}\n'
              .format(updates[0]["date"] if updates else ""))
        return

    print(f"🔋 New version {updates[0]['version']} available")
    print_border(frame_width)
    print_row("Version", "Release Date", "Changes", version_col, date_col, changes_col, frame_width)
    print_border(frame_width)
    for upd in updates:
        changes = [line.strip() for line in (upd["message"] or "").split('\n') if line.strip()]
        if not changes:
            changes = ["No description"]
        first = True
        for line in changes:
            wrapped = wrap_text(line, changes_col)
            for i, part in enumerate(wrapped):
                if first and i == 0:
                    print_row(upd['version'], f"📅 {upd['date']}", part, version_col, date_col, changes_col, frame_width)
                else:
                    print_row("", "", part, version_col, date_col, changes_col, frame_width)
            first = False
        print_border(frame_width)
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
