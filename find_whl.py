import zipfile, os

zip_path = r"C:\Infineon\Tools\Radar-Development-Kit\3.6.5\assets\software\radar_sdk.zip"
print(f"Opening: {zip_path}")
print(f"Exists: {os.path.exists(zip_path)}")

z = zipfile.ZipFile(zip_path)
names = z.namelist()
print(f"Total entries: {len(names)}")

whl = [n for n in names if n.endswith(".whl")]
print(f"\nWheels found: {whl}")

py = [n for n in names if "python" in n.lower() and not n.endswith("/")]
print(f"\nPython-related files (first 30):")
for n in py[:30]:
    print(" ", n)
