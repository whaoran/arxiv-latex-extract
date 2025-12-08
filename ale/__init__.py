from os import makedirs

ARCHIVE_DIR = "/data/tmp/"
ARXIV_URL = "https://arxiv.org/abs/"

for path in [ARCHIVE_DIR]:
    makedirs(path, exist_ok=True)
