"""
Logic cho phần "hệ thống lớp học": vai trò tài khoản (giáo viên/học sinh),
lớp học, giao bài tập trắc nghiệm, bài nộp và lịch sử điểm.

Không chứa code giao diện (Streamlit) - app.py gọi các hàm ở đây.
"""

import datetime
import uuid

import yaml
from yaml.loader import SafeLoader

import config
import rag_utils


# ---------- TÀI KHOẢN: VAI TRÒ (role) + LỚP (class_id) ----------
# Lưu ngay trong auth_config.yaml, mỗi username có thêm 2 trường:
#   role: "teacher" | "student"
#   class_id: id của lớp (chỉ học sinh mới có, giáo viên để trống)

def load_auth_config() -> dict:
    data = rag_utils.load_json(config.AUTH_CONFIG_FILE, default=None)
    if data:
        return data
    with open(config.AUTH_CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLoader)


def get_user_info(username: str) -> dict:
    """Trả về {"name", "role", "class_id"} của 1 username. role mặc định
    "student" nếu tài khoản cũ chưa có trường role (tương thích ngược)."""
    auth_cfg = load_auth_config()
    info = auth_cfg.get("credentials", {}).get("usernames", {}).get(username, {})
    return {
        "name": info.get("name", username),
        "role": info.get("role", "student"),
        "class_id": info.get("class_id"),
    }


def all_users() -> dict:
    """Trả về toàn bộ dict usernames -> {name, role, class_id, ...} từ auth_config."""
    auth_cfg = load_auth_config()
    return auth_cfg.get("credentials", {}).get("usernames", {})


# ---------- LỚP HỌC ----------

def list_classes() -> list:
    return rag_utils.load_json(config.CLASSES_FILE, default=[])


def get_class(class_id: str) -> dict | None:
    for c in list_classes():
        if c["id"] == class_id:
            return c
    return None


def list_classes_for_teacher(teacher_username: str) -> list:
    return [c for c in list_classes() if c.get("teacher_username") == teacher_username]


def create_class(name: str, teacher_username: str) -> dict:
    classes = list_classes()
    new_class = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "teacher_username": teacher_username,
        "created_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    classes.append(new_class)
    rag_utils.save_json(classes, config.CLASSES_FILE)
    return new_class


def list_students_in_class(class_id: str) -> list:
    """Trả về [{"username":..., "name":...}] của học sinh thuộc đúng lớp này."""
    users = all_users()
    return sorted(
        (
            {"username": uname, "name": info.get("name", uname)}
            for uname, info in users.items()
            if info.get("role") == "student" and info.get("class_id") == class_id
        ),
        key=lambda u: u["name"],
    )


# ---------- BÀI TẬP (ASSIGNMENT) ----------

def list_assignments() -> list:
    return rag_utils.load_json(config.ASSIGNMENTS_FILE, default=[])


def list_assignments_for_class(class_id: str) -> list:
    return [a for a in list_assignments() if a["class_id"] == class_id]


def get_assignment(assignment_id: str) -> dict | None:
    for a in list_assignments():
        if a["id"] == assignment_id:
            return a
    return None


def create_assignment(class_id: str, title: str, topic: str, due_date: str,
                       quiz: list, created_by: str, source_doc: str = None) -> dict:
    """quiz: danh sách câu hỏi ĐÃ soạn sẵn (xem config.ASSIGNMENT_QUIZ_PROMPT_TEMPLATE) -
    mọi học sinh trong lớp làm CHUNG 1 bộ câu hỏi này, để điểm có thể so sánh được."""
    assignments = list_assignments()
    new_assignment = {
        "id": str(uuid.uuid4())[:8],
        "class_id": class_id,
        "title": title,
        "topic": topic,
        "due_date": due_date,
        "quiz": quiz,
        "created_by": created_by,
        "source_doc": source_doc,
        "created_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    assignments.append(new_assignment)
    rag_utils.save_json(assignments, config.ASSIGNMENTS_FILE)
    return new_assignment


def delete_assignment(assignment_id: str) -> None:
    assignments = [a for a in list_assignments() if a["id"] != assignment_id]
    rag_utils.save_json(assignments, config.ASSIGNMENTS_FILE)


# ---------- BÀI NỘP (SUBMISSION) ----------

def load_submissions(assignment_id: str) -> dict:
    """Trả về {username: {"answers":[...], "score":int, "total":int, "submitted_at":str}}."""
    return rag_utils.load_json(config.submissions_file(assignment_id), default={})


def get_submission(assignment_id: str, username: str) -> dict | None:
    return load_submissions(assignment_id).get(username)


def record_submission(assignment_id: str, username: str, answers: list, score: int, total: int) -> None:
    submissions = load_submissions(assignment_id)
    submissions[username] = {
        "answers": answers,
        "score": score,
        "total": total,
        "submitted_at": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
    rag_utils.save_json(submissions, config.submissions_file(assignment_id))


# ---------- LỊCH SỬ ĐIỂM TRẮC NGHIỆM (để vẽ biểu đồ tiến độ) ----------

def append_quiz_record(username: str, topic: str, score: int, total: int,
                        source: str, assignment_id: str = None) -> None:
    """source: "tutor" (tự ôn với Gia sư AI) hoặc "assignment" (bài được giao)."""
    history = rag_utils.load_json(config.quiz_history_file(username), default=[])
    history.append({
        "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "topic": topic,
        "score": score,
        "total": total,
        "source": source,
        "assignment_id": assignment_id,
    })
    rag_utils.save_json(history, config.quiz_history_file(username))


def load_quiz_history(username: str) -> list:
    return rag_utils.load_json(config.quiz_history_file(username), default=[])
