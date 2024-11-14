from abc import ABC, abstractmethod


class Uploader(ABC):
    @abstractmethod
    def upload_stream(self, file_path: str, blob_name: str):
        pass


"""    @abstractmethod
    def get_progress(self):
        pass
"""
