"""
Công cụ dòng lệnh để quản lý tài khoản VÀ lớp học - không cần tự tay băm mật
khẩu hay sửa file JSON/YAML bằng tay.

Cách dùng:
    python manage.py

Menu gồm:
    1. Tạo lớp học mới
    2. Tạo tài khoản GIÁO VIÊN
    3. Tạo tài khoản HỌC SINH (gán vào 1 lớp đã có)
    4. Đổi mật khẩu 1 tài khoản đã có
    5. Xem danh sách lớp + học sinh

Lưu ý:
- Tài khoản lưu trong auth_config.yaml (mật khẩu đã băm, không lưu dạng chữ
  thường) - KHÔNG đưa file này lên GitHub.
- Lớp học lưu trong school_data/classes.json.
- Cả 2 file trên đều đã có sẵn trong .gitignore.
"""

import os
import secrets

import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth

import config
import school


# ---------- auth_config.yaml ----------

def _load_or_init_auth() -> dict:
    if os.path.exists(config.AUTH_CONFIG_FILE):
        with open(config.AUTH_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.load(f, Loader=SafeLoader)
        if data:
            return data
    return {
        "credentials": {"usernames": {}},
        "cookie": {
            "name": "physics12_chatbot_cookie",
            "key": secrets.token_hex(16),
            "expiry_days": 30,
        },
        "preauthorized": {"emails": []},
    }


def _save_auth(auth_cfg: dict) -> None:
    with open(config.AUTH_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(auth_cfg, f, allow_unicode=True, sort_keys=False)


# ---------- Các thao tác của menu ----------

def create_class_flow():
    print("\n=== Tạo lớp học mới ===")
    auth_cfg = _load_or_init_auth()
    usernames = auth_cfg["credentials"]["usernames"]
    teachers = {u: i for u, i in usernames.items() if i.get("role") == "teacher"}

    if not teachers:
        print("Chưa có tài khoản giáo viên nào. Hãy tạo tài khoản giáo viên trước (menu 2).")
        return

    print("Giáo viên hiện có:", ", ".join(f"{u} ({i['name']})" for u, i in teachers.items()))
    teacher_username = input("Tên đăng nhập giáo viên phụ trách lớp này: ").strip()
    if teacher_username not in teachers:
        print(f"Không tìm thấy giáo viên '{teacher_username}'.")
        return

    class_name = input("Tên lớp (vd: 12A3 - Vật lý): ").strip()
    if not class_name:
        print("Tên lớp trống, huỷ.")
        return

    new_class = school.create_class(class_name, teacher_username)
    print(f"\nĐã tạo lớp '{new_class['name']}' (mã lớp nội bộ: {new_class['id']}).")
    print("Dùng menu 3 để thêm học sinh vào lớp này.")


def create_teacher_flow():
    print("\n=== Tạo tài khoản GIÁO VIÊN ===")
    auth_cfg = _load_or_init_auth()
    usernames = auth_cfg["credentials"]["usernames"]

    username = input("Tên đăng nhập (không dấu, không khoảng trắng, vd: gv_thuy): ").strip()
    if not username:
        print("Tên đăng nhập trống, huỷ.")
        return
    full_name = input("Họ tên hiển thị (vd: Cô Nguyễn Thị Thuý): ").strip() or username
    password = input("Mật khẩu: ").strip()
    if not password:
        print("Mật khẩu trống, huỷ.")
        return

    hashed = stauth.Hasher([password]).generate()[0]
    usernames[username] = {"name": full_name, "password": hashed, "role": "teacher", "class_id": None}
    _save_auth(auth_cfg)
    print(f"\nĐã tạo tài khoản giáo viên '{username}' ({full_name}).")


def create_student_flow():
    print("\n=== Tạo tài khoản HỌC SINH ===")
    auth_cfg = _load_or_init_auth()
    usernames = auth_cfg["credentials"]["usernames"]

    classes = school.list_classes()
    if not classes:
        print("Chưa có lớp nào. Hãy tạo lớp trước (menu 1).")
        return

    print("Các lớp hiện có:")
    for c in classes:
        n_students = len(school.list_students_in_class(c["id"]))
        print(f"  [{c['id']}] {c['name']} (GV: {c['teacher_username']}, {n_students} học sinh)")

    class_id = input("Nhập mã lớp (trong dấu [ ] ở trên) để thêm học sinh vào: ").strip()
    if class_id not in {c["id"] for c in classes}:
        print("Không tìm thấy mã lớp này.")
        return

    username = input("Tên đăng nhập học sinh (không dấu, không khoảng trắng, vd: hocsinh1): ").strip()
    if not username:
        print("Tên đăng nhập trống, huỷ.")
        return
    is_update = username in usernames
    full_name = input("Họ tên hiển thị (vd: Nguyễn Văn A): ").strip() or username
    password = input("Mật khẩu: ").strip()
    if not password:
        print("Mật khẩu trống, huỷ.")
        return

    hashed = stauth.Hasher([password]).generate()[0]
    usernames[username] = {
        "name": full_name, "password": hashed, "role": "student", "class_id": class_id,
    }
    _save_auth(auth_cfg)
    action = "cập nhật" if is_update else "tạo mới"
    print(f"\nĐã {action} tài khoản học sinh '{username}' ({full_name}), lớp {class_id}.")


def change_password_flow():
    print("\n=== Đổi mật khẩu tài khoản đã có ===")
    auth_cfg = _load_or_init_auth()
    usernames = auth_cfg["credentials"]["usernames"]
    if not usernames:
        print("Chưa có tài khoản nào.")
        return

    print("Tài khoản hiện có:", ", ".join(usernames.keys()))
    username = input("Tên đăng nhập cần đổi mật khẩu: ").strip()
    if username not in usernames:
        print("Không tìm thấy tài khoản này.")
        return
    password = input("Mật khẩu MỚI: ").strip()
    if not password:
        print("Mật khẩu trống, huỷ.")
        return
    usernames[username]["password"] = stauth.Hasher([password]).generate()[0]
    _save_auth(auth_cfg)
    print(f"\nĐã đổi mật khẩu cho '{username}'.")


def list_overview_flow():
    print("\n=== Danh sách lớp + học sinh ===")
    classes = school.list_classes()
    if not classes:
        print("Chưa có lớp nào.")
        return
    for c in classes:
        students = school.list_students_in_class(c["id"])
        print(f"\n[{c['id']}] {c['name']}  (GV: {c['teacher_username']})")
        if not students:
            print("    (chưa có học sinh)")
        for s in students:
            print(f"    - {s['username']} ({s['name']})")


def main():
    menu = """
=== QUẢN LÝ LỚP HỌC - Trợ lý Vật lý 12 ===
1. Tạo lớp học mới
2. Tạo tài khoản GIÁO VIÊN
3. Tạo tài khoản HỌC SINH (gán vào 1 lớp)
4. Đổi mật khẩu 1 tài khoản đã có
5. Xem danh sách lớp + học sinh
0. Thoát
"""
    actions = {
        "1": create_class_flow,
        "2": create_teacher_flow,
        "3": create_student_flow,
        "4": change_password_flow,
        "5": list_overview_flow,
    }
    while True:
        print(menu)
        choice = input("Chọn (0-5): ").strip()
        if choice == "0":
            break
        action = actions.get(choice)
        if action:
            action()
        else:
            print("Lựa chọn không hợp lệ.")


if __name__ == "__main__":
    main()
