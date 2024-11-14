import os
import logging
import json
import uuid
from azure.storage.blob import BlobServiceClient
from .uploader import Uploader
from threading import Lock

logger = logging.getLogger(__name__)

class BlobUploader(Uploader):
    lock = Lock()  # Lock to avoid simultaneous writes to the state file

    def __init__(self, connection_string: str, container_name: str):
        if not connection_string or not container_name:
            logger.error("Azure storage connection string or container name is missing.")
            raise ValueError("Missing Azure connection string or container name")

        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_client = self.blob_service_client.get_container_client(container_name)
        self.upload_state_file = "azure_upload_state.json"

    def _load_state(self, blob_name):
        # Load state from JSON file if it exists
        if os.path.exists(self.upload_state_file):
            with self.lock:
                with open(self.upload_state_file, "r") as f:
                    upload_state = json.load(f)
                if upload_state.get("blob_name") == blob_name:
                    return upload_state
        return None

    def _save_state(self, state):
        # Save the state to JSON file
        with self.lock:
            with open(self.upload_state_file, "w") as f:
                json.dump(state, f)

    def upload_stream(self, file_path: str, blob_name: str, chunk_size: int = 4 * 1024 * 1024, max_retries: int = 3):
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            file_size = os.path.getsize(file_path)
            block_ids = []
            uploaded_size = 0

            # Load existing state if available, to resume
            state = self._load_state(blob_name)
            if state:
                uploaded_size = state["uploaded_size"]
                block_ids = state["block_ids"]

            with open(file_path, "rb") as file:
                file.seek(uploaded_size)  # Resume from where left off

                while uploaded_size < file_size:
                    chunk = file.read(chunk_size)
                    if not chunk:
                        break

                    block_id = str(uuid.uuid4())
                    retries = 0
                    while retries <= max_retries:
                        try:
                            # Stage the block (upload chunk)
                            blob_client.stage_block(block_id=block_id, data=chunk)
                            block_ids.append(block_id)
                            uploaded_size += len(chunk)
                            break  # Exit retry loop on success
                        except Exception as e:
                            retries += 1
                            logger.warning(f"Retry {retries}/{max_retries} for block upload due to: {str(e)}")
                            if retries > max_retries:
                                raise

                    # Save state after each successful block upload
                    self.progress = (uploaded_size / file_size) * 100
                    state = {
                        "blob_name": blob_name,
                        "uploaded_size": uploaded_size,
                        "block_ids": block_ids
                    }
                    self._save_state(state)
                    logger.info(f"Uploaded {uploaded_size} of {file_size} bytes ({self.progress:.2f}%)")

            # Commit all blocks after completing all chunks
            blob_client.commit_block_list(block_ids)

            # Clean up state file on successful upload
            if os.path.exists(self.upload_state_file):
                os.remove(self.upload_state_file)

        except Exception as e:
            logger.error(f"Error during Azure Blob upload: {str(e)}")
            raise