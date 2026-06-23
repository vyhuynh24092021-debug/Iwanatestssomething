"""
Mediafire upload handler
Xử lý upload file quá lớn lên Mediafire
"""

import logging
from pathlib import Path

logger = logging.getLogger("mediafire_uploader")

try:
    from mediafire import MediaFireApi
    from mediafire.client import MediaFireClient
    HAS_MEDIAFIRE = True
except ImportError:
    HAS_MEDIAFIRE = False


class MediaFireUploader:
    """Handler for Mediafire uploads"""
    
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.client = None
        self.api = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Khởi tạo client nếu chưa"""
        if self._initialized:
            return True
        
        if not HAS_MEDIAFIRE:
            logger.error("Mediafire SDK chưa cài. Chạy: pip install mediafire --break-system-packages")
            return False
        
        if not self.email or not self.password:
            logger.error("Thiếu mediafire_email/mediafire_password trong config.json")
            return False
        
        try:
            logging.getLogger("mediafire").setLevel(logging.ERROR)
            self.client = MediaFireClient()
            self.client.login(email=self.email, password=self.password, app_id="42511")
            self.api = self.client.api
            self._initialized = True
            logger.info("Mediafire authenticated")
            return True
        except Exception as e:
            logger.error(f"Mediafire login failed: {e}")
            return False
    
    def upload(self, filepath, filename):
        """
        Upload file lên Mediafire, trả về link download.
        
        Args:
            filepath: đường dẫn file cần upload
            filename: tên file hiển thị
        
        Returns:
            str: link Mediafire hoặc None nếu lỗi
        """
        if not self._ensure_initialized():
            return None
        
        try:
            filepath = Path(filepath)
            if not filepath.exists():
                logger.warning(f"File không tồn tại: {filepath}")
                return None
            
            logger.info(f"Uploading {filename} to Mediafire...")
            
            # Upload file
            with open(filepath, "rb") as f:
                resp = self.api.upload_simple(
                    fd=f,
                    filename=filename,
                    folder_key=None
                )
            
            # Lấy quickkey từ response
            qk = resp.get("quickkey")
            if not qk:
                # Fallback: tìm trong root folder
                for item in self.client.get_folder_contents_iter("mf:/"):
                    if hasattr(item, "get") and item.get("filename") == filename:
                        qk = item.get("quickkey")
                        break
            
            if qk:
                link = f"https://www.mediafire.com/file/{qk}/{filename}/file"
                logger.info(f"Mediafire upload success: {link}")
                return link
            else:
                logger.warning(f"Không lấy được quickkey cho {filename}")
                return None
                
        except Exception as e:
            logger.error(f"Mediafire upload error: {e}")
            return None
    
    def logout(self):
        """Disconnect Mediafire client"""
        if self.client:
            try:
                # Mediafire SDK không có logout() rõ ràng
                self.client = None
                self.api = None
                self._initialized = False
            except Exception as e:
                logger.warning(f"Error during Mediafire logout: {e}")
