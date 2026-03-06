import zipfile, os, subprocess, sys

zip_path = r"C:\Infineon\Tools\Radar-Development-Kit\3.6.5\assets\software\radar_sdk.zip"
target_whl = "radar_sdk/python_wheels/ifxradarsdk-3.6.4+4b4a6245-py3-none-win_amd64.whl"
out_dir = r"C:\Users\DANA\Downloads\radar-main\radar-main"

print(f"Extracting {target_whl} ...")
z = zipfile.ZipFile(zip_path)
# Extract just the wheel file
whl_data = z.read(target_whl)
whl_filename = os.path.basename(target_whl)
whl_out = os.path.join(out_dir, whl_filename)
with open(whl_out, "wb") as f:
    f.write(whl_data)
print(f"Extracted to: {whl_out}")

print(f"\nInstalling with pip...")
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", whl_out],
    capture_output=False
)
print(f"\nDone. Exit code: {result.returncode}")
