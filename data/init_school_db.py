"""初始化高校招生与就业分析演示数据库。

从 school_demo_employment_data.csv 读取虚构数据，创建 school_employment_stats 表。
"""

import csv
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / "school_demo.db"
CSV_PATH = BASE_DIR / "school_demo_employment_data.csv"


def create_tables(conn: sqlite3.Connection) -> None:
    """创建高校招生与就业统计表。"""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS school_employment_stats (
            stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            school_name TEXT NOT NULL,
            major TEXT NOT NULL,
            admitted INTEGER NOT NULL,
            graduates INTEGER NOT NULL,
            employed INTEGER NOT NULL,
            employment_rate REAL NOT NULL,
            graduate_study_rate REAL NOT NULL,
            avg_starting_salary_yuan INTEGER NOT NULL,
            main_employment_cities TEXT NOT NULL,
            main_employment_directions TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_school_stats_year_major ON school_employment_stats(year, major)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_school_stats_major ON school_employment_stats(major)"
    )
    conn.commit()


def load_rows_from_csv(csv_path: Path):
    """读取 CSV 并转换为适合 SQLite 插入的行。"""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = []
        for row in reader:
            rows.append(
                (
                    int(row["year"]),
                    row["school_name"],
                    row["major"],
                    int(row["admitted"]),
                    int(row["graduates"]),
                    int(row["employed"]),
                    float(row["employment_rate"]),
                    float(row["graduate_study_rate"]),
                    int(row["avg_starting_salary_yuan"]),
                    row["main_employment_cities"],
                    row["main_employment_directions"],
                )
            )
        return rows


def insert_sample_data(conn: sqlite3.Connection) -> None:
    """清空并导入演示数据。"""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM school_employment_stats")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'school_employment_stats'")

    rows = load_rows_from_csv(CSV_PATH)
    cursor.executemany(
        """
        INSERT INTO school_employment_stats (
            year, school_name, major, admitted, graduates, employed,
            employment_rate, graduate_study_rate, avg_starting_salary_yuan,
            main_employment_cities, main_employment_directions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def main() -> None:
    """初始化学校演示数据库。"""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"找不到数据源文件: {CSV_PATH}")

    conn = sqlite3.connect(DATABASE_PATH)
    try:
        create_tables(conn)
        insert_sample_data(conn)
        conn.execute("VACUUM")
    finally:
        conn.close()

    print(f"数据库初始化完成: {DATABASE_PATH}")
    print("表名: school_employment_stats")
    print("数据来源: school_demo_employment_data.csv")


if __name__ == "__main__":
    main()
