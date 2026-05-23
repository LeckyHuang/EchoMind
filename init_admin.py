#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化管理员账号
运行一次即可创建管理员账户
"""

from models import SessionLocal, User, init_db


def create_admin(username: str = "admin", password: str = "123456", email: str = None):
    """
    创建管理员账号
    
    Args:
        username: 管理员用户名，默认 "admin"
        password: 初始密码，默认 "123456"
        email: 管理员邮箱，可选
    """
    init_db()  # 确保数据库已初始化
    
    db = SessionLocal()
    try:
        # 检查是否已存在
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            if existing.role == "admin":
                print(f"ℹ️  管理员 '{username}' 已存在（密码未变更）")
                print(f"   如需重置密码，请调用 reset_admin_password() 或使用 API")
                return existing
            else:
                # 升级为管理员
                existing.role = "admin"
                existing.is_active = True
                db.commit()
                print(f"✅ 用户 '{username}' 已升级为管理员")
                return existing
        
        # 创建新管理员
        admin = User(
            username=username,
            email=email,
            role="admin",
            password_hash=User.hash_password(password),
            is_active=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        print(f"✅ 管理员账号创建成功")
        print(f"   用户名：{username}")
        print(f"   密码：{password}")
        print(f"   邮箱：{email or '未设置'}")
        print(f"   user_id：{admin.user_id}")
        print(f"")
        print(f"⚠️  请登录后立即修改默认密码！")
        
        return admin
        
    finally:
        db.close()


def reset_admin_password(username: str = "admin", new_password: str = "123456"):
    """重置管理员密码"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"❌ 用户 '{username}' 不存在")
            return None
        
        user.password_hash = User.hash_password(new_password)
        db.commit()
        print(f"✅ 管理员 '{username}' 密码已重置为：{new_password}")
        return user
    finally:
        db.close()


def list_users():
    """列出所有用户"""
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        print(f"\n{'='*50}")
        print(f"{'用户列表':^50}")
        print(f"{'='*50}")
        print(f"{'用户名':<20} {'角色':<10} {'状态':<10} {'创建时间'}")
        print(f"{'-'*50}")
        for u in users:
            status = "✅ 激活" if u.is_active else "❌ 禁用"
            print(f"{u.username:<20} {u.role:<10} {status:<10} {u.created_at}")
        print(f"{'='*50}")
        print(f"共 {len(users)} 个用户\n")
        return users
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "list":
            list_users()
        elif cmd == "reset" and len(sys.argv) > 2:
            reset_admin_password(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "123456")
        else:
            print("用法:")
            print("  python init_admin.py          # 创建管理员（默认 admin/123456）")
            print("  python init_admin.py list     # 列出所有用户")
            print("  python init_admin.py reset <username> [new_password]  # 重置密码")
    else:
        # 默认创建 admin 管理员
        create_admin()
        print("")
        list_users()
