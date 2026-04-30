import subprocess
import os

from pathlib import Path
from threading import RLock, Condition
from tesserocr import PyTessBaseAPI


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


class TesseractFleetGuard:
    def __init__(self, parent: "TesseractFleet"):
        self.parent = parent
        self.idx: int | None = None
        self.tess: PyTessBaseAPI | None = None

    def __enter__(self):
        self.idx, self.tess = self.parent.get_instance_raw()
        return self.tess

    def __exit__(self, exc_type, exc, tb):
        if self.idx is not None:
            self.parent.release_instance_raw(self.idx)
            self.idx = None
            self.tess = None


class TesseractFleet:
    def __init__(self, num_instances: int | None = None, **kwargs):
        if num_instances is None:
            num_instances = os.cpu_count() or 4

        self.lock = RLock()
        self.cond = Condition(self.lock)
        self.num_instances = num_instances
        self.tess_args = kwargs

        self.tess_list = None
        self.available = [i for i in range(self.num_instances)]

    def __enter__(self):
        self.tess_list = [PyTessBaseAPI(**self.tess_args) for _ in range(self.num_instances)]
        self.available = [i for i in range(self.num_instances)]
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.tess_list is not None:
            tess_list = self.tess_list
            self.tess_list = None

            for t in tess_list:
                t.End()

    def access(self):
        return TesseractFleetGuard(self)

    def get_instance_raw(self) -> tuple[int, PyTessBaseAPI]:
        with self.cond:
            while len(self.available) == 0:
                self.cond.wait(timeout=1)

            idx = self.available.pop()
            tess_list = self.tess_list
            assert tess_list is not None

            return idx, tess_list[idx]

    def release_instance_raw(self, index: int):
        with self.cond:
            if index in self.available:
                raise RuntimeError(f"index {index} is duplicate")

            self.available.append(index)
            self.cond.notify()


if __name__ == "__main__":
    download_tessdata()
