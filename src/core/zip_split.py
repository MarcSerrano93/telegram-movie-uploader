"""
Creates a zip without compression, split into parts of a fixed size: "name.zip.001", "name.zip.002"...
It is what "7z a -tzip -mx0 -v<size>m" does: one normal zip cut into pieces, opened with 7-Zip or WinRAR.
"""
import os
import zipfile

class _SplitWriter:
    """
    Write-only file object for zipfile: writes to base_path.001, base_path.002... of at most part_size bytes each.
    """
    def __init__(self, base_path, part_size):
        self.base_path = base_path
        self.part_size = part_size
        self.part_paths = []
        self.position = 0
        self._part_file = None
        self._part_written = 0

    def _open_next_part(self):
        self.close()
        path = f"{self.base_path}.{len(self.part_paths) + 1:03d}"
        self._part_file = open(path, "wb")
        self._part_written = 0
        self.part_paths.append(path)

    def write(self, data):
        view = memoryview(data)
        while view:
            if self._part_file is None or self._part_written == self.part_size:
                self._open_next_part()
            chunk = view[:self.part_size - self._part_written]
            self._part_file.write(chunk)
            self._part_written += len(chunk)
            view = view[len(chunk):]
        self.position += len(data)
        return len(data)

    def tell(self):
        # zipfile needs the position to write the file offsets; it never seeks, so the parts are written in order
        return self.position

    def flush(self):
        if self._part_file:
            self._part_file.flush()

    def close(self):
        if self._part_file:
            self._part_file.close()
            self._part_file = None

def create_split_zip(source_path, archive_path, part_size):
    """
    Zips source_path into archive_path.001, archive_path.002... of at most part_size bytes each.
    Returns the paths of the parts.
    """
    writer = _SplitWriter(archive_path, part_size)
    try:
        with zipfile.ZipFile(writer, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.write(source_path, os.path.basename(source_path))
    finally:
        writer.close()
    return writer.part_paths
