import os
import logging
from datetime import datetime, timedelta
from .abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)

class MockDisplay(AbstractDisplay):
    """Mock display for development without hardware."""

    # Default cleanup settings
    DEFAULT_MAX_FILES = 50      # Keep latest 50 files
    DEFAULT_MAX_DAYS = 7        # Delete files older than 7 days

    def __init__(self, device_config):
        self.device_config = device_config
        resolution = device_config.get_resolution()
        self.width = resolution[0]
        self.height = resolution[1]
        self.output_dir = device_config.get_config('output_dir', 'mock_display_output')
        os.makedirs(self.output_dir, exist_ok=True)

        # Get cleanup settings from config
        self.max_files = device_config.get_config('mock_max_files', self.DEFAULT_MAX_FILES)
        self.max_days = device_config.get_config('mock_max_days', self.DEFAULT_MAX_DAYS)
        self.enable_cleanup = device_config.get_config('mock_enable_cleanup', True)

    def initialize_display(self):
        """Initialize mock display (no-op for development)."""
        logger.info(f"Mock display initialized: {self.width}x{self.height}")
        if self.enable_cleanup:
            logger.info(f"Mock display cleanup enabled: max_files={self.max_files}, max_days={self.max_days}")

    def display_image(self, image, image_settings=[]):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.output_dir, f"display_{timestamp}.png")
        image.save(filepath, "PNG")

        # Also save as latest.png for convenience
        image.save(os.path.join(self.output_dir, 'latest.png'), "PNG")

        # Cleanup old files if enabled
        if self.enable_cleanup:
            self._cleanup_old_files()

    def _cleanup_old_files(self):
        """Clean up old display files based on configured settings."""
        try:
            files = []
            for filename in os.listdir(self.output_dir):
                if filename.startswith('display_') and filename.endswith('.png'):
                    filepath = os.path.join(self.output_dir, filename)
                    # Get file modification time
                    mtime = os.path.getmtime(filepath)
                    files.append((filepath, mtime))

            if not files:
                return

            # Sort by modification time (oldest first)
            files.sort(key=lambda x: x[1])

            # Get current time
            now = datetime.now().timestamp()
            max_age_seconds = self.max_days * 24 * 3600

            deleted_count = 0
            kept_count = 0

            # Process files from oldest to newest
            for filepath, mtime in files:
                file_age = now - mtime
                file_is_old = file_age > max_age_seconds

                # Count how many files are newer than this one
                newer_files = sum(1 for _, f_mtime in files if f_mtime > mtime)

                # Delete if file is too old OR enough newer files exist to
                # fill the retention window (i.e. this file is beyond the
                # newest max_files). The previous condition inverted the
                # comparison and deleted the newest files while keeping the
                # oldest ones.
                if (file_is_old or newer_files >= self.max_files) and newer_files > 0:
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                        logger.debug(f"Deleted old mock display file: {os.path.basename(filepath)}")
                    except OSError as e:
                        logger.warning(f"Failed to delete {filepath}: {e}")
                else:
                    kept_count += 1

            if deleted_count > 0:
                logger.info(f"Mock display cleanup: deleted {deleted_count} old file(s), kept {kept_count} file(s)")

        except Exception as e:
            logger.error(f"Error during mock display cleanup: {e}")