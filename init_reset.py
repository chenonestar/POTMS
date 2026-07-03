"""初始化或重置数据库（独立运行）"""
import os
import sys

# 确保工作目录正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, seed_data

if __name__ == "__main__":
    init_db()
    seed_data()
    print("[OK] Database initialized successfully.")
    print("  Admin account: admin / admin123")
    print(f"  Database file: {os.path.join(os.path.dirname(__file__), 'data.db')}")
