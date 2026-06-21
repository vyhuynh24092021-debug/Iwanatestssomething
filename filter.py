"""
Bộ lọc tin nhắn - chỉnh sửa tại đây để thay đổi điều kiện lọc
"""

def should_include(msg, thread_author_id):
    """
    Trả về True nếu tin nhắn cần được clone.
    
    Điều kiện hiện tại:
    - Tin đầu tiên của thread (index 0) -> luôn lấy
    - Tin của chủ thread -> lấy
    - Tin của người khác có file/ảnh -> lấy file nhưng bỏ text
    - Tin text thuần của người khác -> bỏ
    """
    author_id = msg.get("author", {}).get("id", "")
    is_thread_author = author_id == thread_author_id
    has_attachments = bool(msg.get("attachments"))
    
    return is_thread_author or has_attachments

def filter_content(msg, thread_author_id):
    """
    Trả về (content, keep_attachments).
    Nếu không phải chủ thread: bỏ text, chỉ giữ file.
    """
    author_id = msg.get("author", {}).get("id", "")
    is_thread_author = author_id == thread_author_id
    
    if is_thread_author:
        return msg.get("content", ""), True
    else:
        # Người khác: bỏ text, chỉ lấy file
        return "", True
