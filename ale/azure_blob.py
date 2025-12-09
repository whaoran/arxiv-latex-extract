
import time
from pathlib import Path
from azure.storage.blob import BlobServiceClient
from azure.identity import AzureCliCredential
from azure.core.exceptions import ServiceRequestError, ServiceResponseError, HttpResponseError



def authenticate_service(account_url):
    """Authenticate to Azure Blob Storage using DefaultAzureCredential."""
    credential = AzureCliCredential()
    blob_client = BlobServiceClient(account_url, credential=credential)
    return blob_client


def upload_folder(container, local_folder, remote_path=""):
    """
    使用 pathlib 上传整个文件夹到 Azure Blob Storage
    """
    local_folder = Path(local_folder)
    for file_path in local_folder.rglob("*"):
        if file_path.is_file():
            # 相对路径保持子目录结构
            relative_path = file_path.relative_to(local_folder)

            # blob 路径
            blob_path = Path(remote_path) / relative_path
            blob_path = str(blob_path).replace("\\", "/")  # Windows 兼容
            safe_upload(container, file_path, blob_path)
    print(f"Uploaded folder {str(local_folder)} → {remote_path}")



def safe_upload(container, file_path, blob_path, retries=5):
    # print(f"Uploading {file_path} → {blob_path}")
    with file_path.open("rb") as data:
        for i in range(retries):
            try:
                container.upload_blob(name=blob_path, data=data, overwrite=True)
                return
            except (ServiceRequestError, ServiceResponseError, HttpResponseError) as e:
                wait = 0.5 * (2 ** i)
                print(f"Retry {i} for {blob_path}, wait {wait:.2f}s: {e}")
                time.sleep(wait)
        raise RuntimeError(f"Failed to upload {blob_path} after {retries} retries")