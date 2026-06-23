"""
Message filtering logic for Discord Cloner
Chỉnh sửa các hàm này để tùy chỉnh điều kiện lọc tin nhắn
"""

class MessageFilter:
    """Bộ lọc tin nhắn dựa trên chế độ clone"""
    
    FORUM_MODE = "forum"      # Forum threads - có chủ thread
    CHANNEL_MODE = "channel"  # Regular channels - không có chủ thread
    
    def __init__(self, mode):
        self.mode = mode
    
    def should_include(self, msg, thread_author_id=None):
        """Xác định tin nhắn có nên được clone không"""
        if self.mode == self.FORUM_MODE:
            return self._forum_filter(msg, thread_author_id)
        else:  # CHANNEL_MODE
            return self._channel_filter(msg)
    
    def _forum_filter(self, msg, thread_author_id):
        """Lọc cho forum threads: chỉ chủ thread + file đính kèm"""
        author_id = msg.get("author", {}).get("id", "")
        is_author = author_id == thread_author_id
        has_attachments = bool(msg.get("attachments"))
        return is_author or has_attachments
    
    def _channel_filter(self, msg):
        """Lọc cho regular channels: lấy tất cả"""
        return True
    
    def get_content(self, msg, thread_author_id=None):
        """Lấy nội dung tin nhắn dựa trên chế độ"""
        if self.mode == self.FORUM_MODE:
            return self._get_forum_content(msg, thread_author_id)
        else:  # CHANNEL_MODE
            return self._get_channel_content(msg)
    
    def _get_forum_content(self, msg, thread_author_id):
        """
        Forum: nếu chủ thread → lấy content + files
               nếu người khác → chỉ lấy files, bỏ text
        """
        author_id = msg.get("author", {}).get("id", "")
        is_author = author_id == thread_author_id
        
        content = msg.get("content", "") if is_author else ""
        return content
    
    def _get_channel_content(self, msg):
        """Channel: lấy toàn bộ content"""
        return msg.get("content", "")


# Preset filters có thể mở rộng
FILTERS = {
    "forum_author_only": {
        "name": "Forum - Chỉ chủ thread",
        "mode": MessageFilter.FORUM_MODE
    },
    "channel_all": {
        "name": "Channel - Tất cả tin nhắn",
        "mode": MessageFilter.CHANNEL_MODE
    }
}
