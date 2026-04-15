import subprocess
from pathlib import Path


def download_tessdata(target_dir: str = "./tessdata"):
    """
    Downloads the Tesseract language models (tessdata) via git clone.
    Only executes if the target directory does not already exist.
    """
    repo_url = "https://github.com/tesseract-ocr/tessdata.git"
    tessdata_path = Path(target_dir)

    # Check if the directory already exists
    if tessdata_path.exists() and tessdata_path.is_dir():
        return

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, target_dir],
            check=True,
            capture_output=False,
        )
        print(f"✅ Successfully downloaded tessdata to '{target_dir}'.")

    except subprocess.CalledProcessError as e:
        print(f"❌ Git clone failed with error code {e.returncode}.")
    except FileNotFoundError:
        print("❌ Error: 'git' command not found. Please ensure Git is installed and added to your system's PATH.")


if __name__ == "__main__":
    download_tessdata()
