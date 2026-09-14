"""One-time script to remove old blog content before first build"""
import shutil
from pathlib import Path


def clean():
    dirs_to_remove = [
        Path("content/blog"),
        Path("docs/blog"),
    ]
    
    for d in dirs_to_remove:
        if d.exists():
            shutil.rmtree(d)
            print(f"Removed: {d}")
    
    print("Cleanup complete!")

if __name__ == "__main__":
    clean()