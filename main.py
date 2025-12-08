#!/usr/bin/env python
from datetime import datetime
from functools import partial
# from multiprocessing import Pool
from multiprocessing.dummy import Pool
from os import sched_getaffinity
from pathlib import Path
from shutil import move
import shutil
from tempfile import TemporaryDirectory
from typing import Callable

from tqdm import tqdm

from ale import ARCHIVE_DIR
from ale.arxiv import delete, download
from ale.cleaner import ArxivCleaner
from ale.extract import try_extract_composed_tar, try_extract_single_paper_gz_file
from ale.azure_blob import authenticate_service, safe_upload, upload_folder

def clean(archive, output, target_dir, filter_func=lambda _: True, verbose=False):
    # create temporary work directory
    with TemporaryDirectory() as work_dir:
        arxiv_cleaner = ArxivCleaner(
            data_dir=archive,
            work_dir=work_dir,
            target_dir=target_dir,
            filter_func=filter_func
        )

        return arxiv_cleaner.run(out_fname=output, verbose=verbose)

def download_and_extract_composed_tar(task):
    import time
    if isinstance(task, Callable): # handle lazy downloading
        task = task()
    composed_folder = Path(task)
    composed_tar_fpath = composed_folder / f"{composed_folder.name}.tar"
    extracted_folder_name = composed_tar_fpath.name.split('_')[-2]
    if (composed_folder / extracted_folder_name).exists():
        print(f"Skip already extracted composed tar: {composed_tar_fpath}")
        paper_gz_files = list((composed_folder / extracted_folder_name).glob("*.gz"))
    else:
        paper_gz_files = try_extract_composed_tar(composed_tar_fpath)
    time.sleep(0.5)
    return paper_gz_files


def extract_and_upload(archive, **kwargs):
    target_container = kwargs['target_container']
    output_dir = kwargs['output_dir']
    archive = Path(archive)
    main_tex_fpath = None
    try:
        main_tex_fpath = try_extract_single_paper_gz_file(archive)
        if main_tex_fpath is not None:
            existed_blob = list(target_container.list_blobs(name_starts_with=f"{target_prefix}/{main_tex_fpath.parent.name}"))
            if len(existed_blob) > 0:
                print(f"Skip already uploaded archive: {archive}, main tex: {main_tex_fpath}")
            else:
                upload_folder(target_container, main_tex_fpath.parent, f"{target_prefix}/{main_tex_fpath.parent.name}")
                # print(f"Extracted and uploaded archive: {archive}, main tex: {main_tex_fpath}")
            shutil.rmtree(main_tex_fpath.parent)  # remove the extracted folder to save space

    except Exception as e:
        print(e)

    return main_tex_fpath


def safe_call(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            print(f"Error running {fn.__name__}: {e}")
            return None
    return wrapper


def get_args():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--blob_name', type=str, help='Azure blob name for the uploaded file')
    parser.add_argument('--container_name', type=str, help='Container name in Azure blob storage')
    parser.add_argument('--year', type=int, help='target year of arxivSource')
    parser.add_argument('--output_dir', type=str, help='output directory for processed files', default="/data/dataset/arxiv_source")
    parser.add_argument(
        '--test',
        action='store_true',
        help='Debugging only. Set this flag to process a mini batch')

    args = parser.parse_args()
    return args

if __name__ == "__main__":
    def filter_func(tex): return b"tikzpicture" in tex # only process projects which contain tikz

    args = get_args()
    target_year = args.year
    output_dir = Path(args.output_dir)
    target_year_out_dir = output_dir / str(target_year)
    target_year_out_dir.mkdir(exist_ok=True, parents=True)
    tmp_storage_dir = Path(ARCHIVE_DIR, str(target_year))
    tmp_storage_dir.mkdir(exist_ok=True, parents=True)

    azure_account_url = f"https://{args.blob_name}.blob.core.windows.net"
    target_container_name = args.container_name
    target_prefix = f"arxivSource/{target_year}"

    # start_time = datetime(2005, 10, 23) # tikz 1.0 release date
    start_time = datetime(target_year, 1, 1)
    end_time = datetime(target_year, 12, 31)
    blob_service = authenticate_service(azure_account_url)
    target_container = blob_service.get_container_client(target_container_name)

    all_paper_tar_files = []  # Store the main tex file's relative path for further processing
    all_main_tex_fpaths = []  # Store the main tex file's relative path for further processing
    # Parallelize to make things faster
    # num_workers = 10
    with Pool(num_workers:=len(sched_getaffinity(0))) as p:
        print(f"Parallel processing on {num_workers} workers.")

        # save results in a tmpdir first and copy them into OUTPUT_DIR only when
        # processing is finished. This avoids partial files in case of errors
        with TemporaryDirectory() as target_dir:
            downloaded_archives_list =[d for d in tmp_storage_dir.iterdir() if d.is_dir()]
            exclude_list = [d.name for d in downloaded_archives_list]  # exclude already downloaded archives
            tasks = list(download(lazy=True,
                                  start_time=start_time, end_time=end_time,
                                  tmp_storage_dir=tmp_storage_dir,
                                  exclude=exclude_list
                                  )
                        )
            tasks = tasks + downloaded_archives_list
            if args.test:
                test_size = 1
                print(f"Test, shrink the task size: {len(tasks)} -> {test_size}")
                tasks = tasks[:test_size]  # For test
            # kwargs = dict(filter_func=filter_func, target_dir=target_dir)
            kwargs = dict(target_container=target_container, output_dir=target_year_out_dir)

            all_paper_gz_files = []
            print(f"Start processing {len(tasks)} composed tar files...")
            paper_gz_file_list = tqdm(p.imap_unordered(download_and_extract_composed_tar, tasks), total=len(tasks))
            for paper_gz_files in paper_gz_file_list:
                all_paper_gz_files.extend(paper_gz_files)
            # for task in tqdm(tasks, total=len(tasks)):
            #     if isinstance(task, Callable): # handle lazy downloading
            #         task = task()
            #     composed_folder = Path(task)
            #     composed_tar_fpath = composed_folder / f"{composed_folder.name}.tar"
            #     extracted_folder_name = composed_tar_fpath.name.split('_')[-2]
            #     if (composed_folder / extracted_folder_name).exists():
            #         print(f"Skip already extracted composed tar: {composed_tar_fpath}")
            #         paper_gz_files = list((composed_folder / extracted_folder_name).glob("*.gz"))
            #     else:
            #         paper_gz_files = try_extract_composed_tar(composed_tar_fpath)
            #     all_paper_gz_files.extend(paper_gz_files)

            print(f"Start processing {len(all_paper_gz_files)} paper gz files...")
            safe_extract_and_upload = safe_call(partial(extract_and_upload, **kwargs))
            all_main_tex_fpaths = tqdm(p.imap_unordered(safe_extract_and_upload, all_paper_gz_files), total=len(all_paper_gz_files))
            all_main_tex_fpaths = [Path(e) for e in all_main_tex_fpaths if e is not None]

    # print("Moving extracted folders to output directory...")
    # for main_tex_fpath in all_main_tex_fpaths:
    #     main_tex_fpath = Path(main_tex_fpath)
    #     move(main_tex_fpath.parent, target_year_out_dir / main_tex_fpath.parent.name)

    all_main_tex_fpaths = [str(e.relative_to(e.parent.parent)) for e in all_main_tex_fpaths]
    # for paper_tar_files in tqdm(p.imap_unordered(partial(process, **kwargs), tasks), total=len(tasks)):
    #     all_paper_tar_files.extend(paper_tar_files)
    #     for paper_tar_file in paper_tar_files:
    #         safe_upload(target_container, paper_tar_file, f"{target_prefix}/{paper_tar_file.name}")
    #         # if not (output_dir / main_tex_fpath.parent.name).exists():
    #         #     move(main_tex_fpath.parent, output_dir)

    import json

    target_year_out_dir.mkdir(exist_ok=True, parents=True)
    index_json_path = target_year_out_dir / 'main_tex_indexes.json'

    with open(index_json_path, 'w') as wf:
        json.dump(all_main_tex_fpaths, wf, indent=2)
    safe_upload(target_container, index_json_path, f"{target_prefix}/{index_json_path.name}")

    pdf_cnt_path = target_year_out_dir / f"pdf_count_{len(all_main_tex_fpaths)}.txt"
    pdf_cnt_path.touch(exist_ok=True)  # 创建空文件，如果存在则忽略

    safe_upload(target_container, pdf_cnt_path, f"{target_prefix}/{pdf_cnt_path.name}")

    print(f"Year {target_year} of arxiv sources are crawled to {target_year_out_dir}, total {len(all_main_tex_fpaths)} papers.")
