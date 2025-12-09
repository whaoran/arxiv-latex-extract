import gzip, tarfile
from pathlib import Path


import os
import re

def find_main_tex(dirpath):
    tex_files = list(dirpath.glob('*.tex'))

    if len(tex_files) == 1:
        return tex_files[0], 100
    elif len(tex_files) == 0:
        return None, 0

    scores = {}
    for path in tex_files:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
            text = fp.read()
        score = 0
        # Rule 1: contains \documentclass
        if r'\documentclass' in text:
            score += 100

        # Rule 2: includes others? then it's likely main
        if re.search(r'\\(input|include)\{', text):
            score += 30

        # Rule 3: filename patterns
        if any(k in path.name.lower() for k in ['main', 'root', 'paper', 'ms']):
            score += 50
        # save
        scores[path] = score
    # return file with max score
    return max(scores, key=scores.get), scores


def try_extract_composed_tar(tar_fpath):
    # print("tar_fpath: ", tar_fpath)
    # unzip the composed tar file
    tar_fpath = Path(tar_fpath)
    extract_rpath = tar_fpath.parent
    error_logs = {}
    try:
        with tarfile.open(tar_fpath, "r:*") as tar:
            tar.extractall(extract_rpath)
    except Exception as e:
        error_logs[tar_fpath.stem] = f"extractall error: {str(e)}"

    dirs = [e for e in extract_rpath.iterdir() if e.is_dir()]

    if len(dirs) == 1:
        extracted_folder = dirs[0]  # The extract folder, e.g., arXiv_src_1511_009.tar -> 1511/
        paper_tar_files = list(extracted_folder.glob("*.gz"))
    else:
        error_logs[tar_fpath.stem] = f"extractall error: Abnormal extracted directory count is: {len(dirs)}, they are {dirs}"
        paper_tar_files = []

    if len(error_logs) > 0:
        for key, err_log in error_logs.items():
            print(f"{key}, {err_log}")

    return paper_tar_files  # return all gz files in the extracted folder


def try_extract_single_paper_gz_file(paper_gz_fpath):
    """
    extraction process
    1) First unzip composed tar file, after unzip there will be many *.gz file in the extracter folder, each one is a paper.
    2) Then unzip the gz files. First use tar, then use gzip if failed.
    """

    # unzip every tar file per paper in the extracted folder
    error_logs = {}
    paper_id = paper_gz_fpath.stem
    extracted_folder = paper_gz_fpath.parent
    error_logs[paper_id] = []
    is_tarfile_succeed = False
    # Try tar first
    try:
        with tarfile.open(paper_gz_fpath, "r:*") as tar:
            extract_out_dir = extracted_folder / paper_id
            tar.extractall(extract_out_dir)
            is_tarfile_succeed = True
    except Exception as e:
        error_logs[paper_id].append(f">tar error: {str(e)}")

    gunzip_out = None
    # If tar failed, Then try gunzip
    if not is_tarfile_succeed:
        gunzip_out_dir = extracted_folder / paper_id
        gunzip_out_dir.mkdir(parents=True, exist_ok=True)
        gunzip_out = gunzip_out_dir / "gzip_extracted"
        try:
            with gzip.open(paper_gz_fpath, "rb") as gz, gunzip_out.open("wb") as f:
                f.write(gz.read())
        except Exception as e:
            error_logs[paper_id].append(f">gzip error: {str(e)}")
            gunzip_out = None  # gunzip failed

    # 如果 gunzip 成功
    if gunzip_out and gunzip_out.exists():
        # 2) 尝试作为 tar 解压, 可能还有最后一层压缩包
        try:
            with tarfile.open(gunzip_out, "r") as tar:
                tar.extractall(gunzip_out_dir)
            gunzip_out.unlink()
        except Exception as e:
            # gunzip 成功，但不是 tar → 这是合法的 arXiv 情况，例如只有 TeX 文件。
            error_logs[paper_id].append(f">gzip>tar error: {str(e)}")
            gunzip_out.rename(gunzip_out_dir / f"{paper_id}_main.tex")

    if is_tarfile_succeed or gunzip_out is not None:
        del error_logs[paper_id]

    if len(error_logs) > 0:
        for key, err_log in error_logs.items():
            print(f"{key}, {err_log}")

    # Locate the main tex file path for further process(copy)
    main_tex_fpath, _ = find_main_tex(extracted_folder / paper_id)
    return main_tex_fpath


def _test_extract():
    rpath = Path("/home/azureuser/projects/arxiv-latex-extract/archives/arXiv_src_1511_009")
    for file in rpath.rglob("*.tar"):
        try:
            try_extract_recursively(file)
        except Exception as e:
            print(e)


def _test_find_main_tex():
    rpath = Path("/home/azureuser/projects/arxiv-latex-extract/archives/arXiv_src_1511_009")
    for folder in (rpath / '1511').iterdir():
        if not folder.is_dir():
            continue
        main_file, _ = find_main_tex(folder)
        print("Find main tex file: ", main_file)


if __name__ == "__main__":
    _test_extract()
    _test_find_main_tex()