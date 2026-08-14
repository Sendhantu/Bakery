# ============================================================
# BAKERY LLM - DATASET 3 COLLECTION
# USDA FoodData Central - Foundation Foods
# ============================================================

import os
import zipfile
import requests


# ------------------------------------------------------------
# STEP 1: YOUR PROJECT PATH
# ------------------------------------------------------------

BASE_PATH = "/Users/sendhanumapathy/Desktop/bakery_llm"

RAW_PATH = os.path.join(
    BASE_PATH,
    "data",
    "raw"
)

os.makedirs(RAW_PATH, exist_ok=True)


# ------------------------------------------------------------
# STEP 2: USDA DATASET URL
# ------------------------------------------------------------

URL = (
    "https://fdc.nal.usda.gov/fdc-datasets/"
    "FoodData_Central_foundation_food_csv_2026-04-30.zip"
)


# ------------------------------------------------------------
# STEP 3: SAVE LOCATIONS
# ------------------------------------------------------------

ZIP_FILE = os.path.join(
    RAW_PATH,
    "FoodData_Central_foundation_food_2026_04.zip"
)

EXTRACT_FOLDER = os.path.join(
    RAW_PATH,
    "usda_foundation_foods_2026_04"
)


# ------------------------------------------------------------
# STEP 4: SHOW CURRENT PATH
# ------------------------------------------------------------

print("=" * 60)
print("BAKERY LLM - DATASET 3")
print("=" * 60)

print("\nRaw folder:")
print(RAW_PATH)

print("\nDownload destination:")
print(ZIP_FILE)


# ------------------------------------------------------------
# STEP 5: DOWNLOAD DATASET
# ------------------------------------------------------------

print("\nDownloading USDA Foundation Foods dataset...")

response = requests.get(
    URL,
    stream=True,
    timeout=120
)

response.raise_for_status()


total_downloaded = 0

with open(ZIP_FILE, "wb") as file:

    for chunk in response.iter_content(
        chunk_size=1024 * 1024
    ):

        if chunk:

            file.write(chunk)

            total_downloaded += len(chunk)

            print(
                f"Downloaded: "
                f"{total_downloaded / (1024 * 1024):.2f} MB",
                end="\r"
            )


print("\n\n✅ Download complete.")


# ------------------------------------------------------------
# STEP 6: VERIFY ZIP FILE
# ------------------------------------------------------------

if not os.path.exists(ZIP_FILE):

    raise FileNotFoundError(
        "Dataset ZIP was not downloaded."
    )


zip_size = (
    os.path.getsize(ZIP_FILE)
    / (1024 * 1024)
)


print("\nZIP file size:")
print(f"{zip_size:.2f} MB")


# ------------------------------------------------------------
# STEP 7: CHECK THAT IT IS A VALID ZIP
# ------------------------------------------------------------

if not zipfile.is_zipfile(ZIP_FILE):

    raise ValueError(
        "Downloaded file is not a valid ZIP file."
    )


print("✅ ZIP file verified.")


# ------------------------------------------------------------
# STEP 8: CREATE EXTRACTION FOLDER
# ------------------------------------------------------------

os.makedirs(
    EXTRACT_FOLDER,
    exist_ok=True
)


# ------------------------------------------------------------
# STEP 9: EXTRACT DATASET
# ------------------------------------------------------------

print("\nExtracting dataset...")


with zipfile.ZipFile(
    ZIP_FILE,
    "r"
) as zip_ref:

    zip_ref.extractall(
        EXTRACT_FOLDER
    )


print("✅ Extraction complete.")


# ------------------------------------------------------------
# STEP 10: LIST EXTRACTED FILES
# ------------------------------------------------------------

print("\n" + "=" * 60)
print("EXTRACTED FILES")
print("=" * 60)


extracted_files = []


for root, dirs, files in os.walk(
    EXTRACT_FOLDER
):

    for filename in files:

        full_path = os.path.join(
            root,
            filename
        )

        size_mb = (
            os.path.getsize(full_path)
            / (1024 * 1024)
        )

        extracted_files.append(
            full_path
        )

        print(
            f"{filename}"
            f"  -->  {size_mb:.2f} MB"
        )


# ------------------------------------------------------------
# STEP 11: COUNT FILES
# ------------------------------------------------------------

print("\nTotal extracted files:")
print(len(extracted_files))


# ------------------------------------------------------------
# STEP 12: FIND CSV FILES
# ------------------------------------------------------------

csv_files = [
    file
    for file in extracted_files
    if file.lower().endswith(".csv")
]


print("\nNumber of CSV files:")
print(len(csv_files))


print("\nCSV files:")

for file in csv_files:

    print(
        "-",
        os.path.basename(file)
    )


# ------------------------------------------------------------
# STEP 13: FINAL RAW DIRECTORY CHECK
# ------------------------------------------------------------

print("\n" + "=" * 60)
print("RAW FOLDER CONTENTS")
print("=" * 60)


for filename in os.listdir(
    RAW_PATH
):

    full_path = os.path.join(
        RAW_PATH,
        filename
    )

    if os.path.isfile(full_path):

        size_mb = (
            os.path.getsize(full_path)
            / (1024 * 1024)
        )

        print(
            f"FILE   : {filename}"
            f" --> {size_mb:.2f} MB"
        )

    elif os.path.isdir(full_path):

        print(
            f"FOLDER : {filename}"
        )


# ------------------------------------------------------------
# STEP 14: FINAL STATUS
# ------------------------------------------------------------

print("\n" + "=" * 60)
print("✅ DATASET 3 COLLECTION COMPLETE")
print("=" * 60)

print("\nSaved ZIP:")
print(ZIP_FILE)

print("\nExtracted dataset:")
print(EXTRACT_FOLDER)

print("\nIMPORTANT:")
print("Do NOT preprocess these files yet.")
print("Keep the USDA files unchanged inside RAW.")