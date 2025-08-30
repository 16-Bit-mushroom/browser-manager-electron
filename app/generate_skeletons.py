import os, shutil, subprocess, time

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BIN_DIR = os.path.join(DATA_DIR, "browser_binaries")

BROWSERS = {
    "FirefoxPortable": {
        "exe": os.path.join(BIN_DIR, "FirefoxPortable", "App", "Firefox64", "firefox.exe"),
        "args": lambda profile: ["-profile", profile, "-no-remote", "-headless"],
    },
    "chrome": {
        "exe": os.path.join(BIN_DIR, "GoogleChromePortable", "App", "Chrome-bin", "chrome.exe"),
        "args": lambda profile: ["--user-data-dir=" + profile, "--headless", "--disable-gpu"],
    }
}

def generate_skeleton(browser):
    browser_info = BROWSERS[browser]
    exe = browser_info["exe"]

    if not os.path.exists(exe):
        print(f"[skeleton] Skipping {browser}: exe not found at {exe}")
        return

    skeleton_dir = os.path.join(DATA_DIR, browser, "DefaultProfileSkeleton")
    temp_profile = os.path.join(DATA_DIR, browser, "__skeleton_temp")

    # Clean old temp
    if os.path.exists(temp_profile):
        shutil.rmtree(temp_profile)
    os.makedirs(temp_profile, exist_ok=True)

    # Launch browser
    args = [exe] + browser_info["args"](temp_profile)
    print(f"[skeleton] Launching {browser} to generate profile...")
    proc = subprocess.Popen(args)

    # Wait a bit for files to generate
    time.sleep(5)

    # Kill browser
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    # Replace skeleton folder
    if os.path.exists(skeleton_dir):
        shutil.rmtree(skeleton_dir)
    shutil.copytree(temp_profile, skeleton_dir)

    print(f"[skeleton] Created skeleton at {skeleton_dir}")

if __name__ == "__main__":
    for b in BROWSERS:
        generate_skeleton(b)
