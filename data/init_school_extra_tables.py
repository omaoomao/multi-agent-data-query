"""为 school_demo.db 扩展多张演示表，提供丰富的 NL2SQL 查询场景。

新增表:
  1. students        - 学生基本信息（500条）
  2. teachers        - 教师信息（60条）
  3. courses         - 课程目录（120条）
  4. student_scores  - 学生成绩（3000条）
  5. internships     - 实习记录（400条）
  6. graduate_career - 毕业生职业追踪（500条）
"""

import random
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / "school_demo.db"
SEED = 20260507

# ── 数据池 ──────────────────────────────────────────────

SCHOOL_NAMES = [
    "华南理工信息学院", "江南应用科技大学", "北方数字工程学院",
    "东海智能制造大学", "西部新工科大学", "中南产业技术学院",
]

MAJORS = [
    "软件工程", "计算机科学与技术", "人工智能", "电子信息工程",
    "自动化", "数据科学与大数据技术", "护理学", "会计学",
]

GENDERS = ["男", "女"]

PROVINCES = [
    "广东", "广西", "湖南", "湖北", "江西", "福建", "四川", "河南",
    "山东", "浙江", "江苏", "安徽", "重庆", "云南", "贵州", "河北",
]

CITIES = [
    "广州", "深圳", "东莞", "佛山", "珠海", "中山", "惠州",
    "北京", "上海", "杭州", "南京", "成都", "武汉", "长沙", "合肥",
]

FIRST_NAMES_MALE = [
    "伟", "强", "磊", "洋", "勇", "军", "杰", "涛", "明", "辉",
    "鹏", "华", "飞", "刚", "波", "斌", "宇", "浩", "志远", "建国",
]
FIRST_NAMES_FEMALE = [
    "芳", "娜", "敏", "静", "丽", "莉", "婷", "雪", "慧", "玲",
    "颖", "琳", "欣", "佳", "瑶", "雯", "倩", "璐", "梦琪", "诗涵",
]
LAST_NAMES = [
    "王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
]

POSITIONS = [
    "教授", "副教授", "讲师", "助教",
]

COURSE_TYPES = ["必修", "选修", "实践", "通识"]

COURSE_NAMES_POOL = [
    "高等数学", "线性代数", "概率论与数理统计", "离散数学",
    "数据结构与算法", "操作系统原理", "计算机网络", "数据库系统概论",
    "编译原理", "软件工程导论", "Python程序设计", "Java程序设计",
    "C语言程序设计", "Web前端开发", "Web后端开发", "移动应用开发",
    "机器学习", "深度学习", "自然语言处理", "计算机视觉",
    "人工智能导论", "大数据处理技术", "云计算基础", "分布式系统",
    "嵌入式系统设计", "物联网技术", "数字信号处理", "电路分析基础",
    "模拟电子技术", "数字电子技术", "微控制器原理", "FPGA设计",
    "自动控制原理", "传感器技术", "机器人学基础", "工业控制系统",
    "人体解剖学", "生理学", "病理学", "药理学",
    "基础护理学", "内科护理学", "外科护理学", "儿科护理学",
    "护理心理学", "健康评估", "社区护理", "急救护理",
    "基础会计", "中级财务会计", "高级财务会计", "成本会计",
    "管理会计", "审计学", "税法", "财务管理",
    "经济法", "金融市场学", "国际贸易", "微观经济学",
    "宏观经济学", "统计学原理", "运筹学", "管理信息系统",
    "Python数据分析", "R语言统计分析", "数据可视化", "数据挖掘",
    "推荐系统", "知识图谱", "强化学习", "生成对抗网络",
    "软件测试", "DevOps实践", "敏捷项目管理", "系统分析与设计",
    "信息安全", "密码学", "区块链技术", "边缘计算",
    "人机交互", "数字图像处理", "语音识别技术", "智能机器人",
    "金融科技", "电子商务", "供应链管理", "人力资源管理",
    "市场营销", "商业伦理", "创新创业", "毕业设计(论文)",
    "生产实习", "认识实习", "课程设计", "军事理论",
    "思想道德与法治", "中国近现代史纲要", "马克思主义基本原理", "大学英语",
    "大学物理", "体育", "艺术鉴赏", "大学生心理健康",
]

INTERNSHIP_COMPANIES = [
    "腾讯", "阿里巴巴", "字节跳动", "华为", "百度", "美团", "京东",
    "网易", "小米", "比亚迪", "中兴", "大疆", "商汤科技", "科大讯飞",
    "蚂蚁金服", "拼多多", "快手", "哔哩哔哩", "滴滴出行", "蔚来汽车",
    "宁德时代", "海康威视", "顺丰科技", "携程", "58同城", "贝壳找房",
    "平安科技", "招商银行科技", "中国移动研究院", "中国电信研究院",
    "南方电网", "广汽集团", "美的集团", "格力电器", "TCL科技",
    "中山大学附属医院", "广东省人民医院", "南方医科大学南方医院",
    "普华永道", "德勤", "安永", "毕马威", "立信会计师事务所",
]

INTERNSHIP_POSITIONS = [
    "软件开发实习生", "后端开发实习生", "前端开发实习生", "测试实习生",
    "数据分析实习生", "算法实习生", "运维实习生", "产品实习生",
    "硬件开发实习生", "嵌入式开发实习生", "通信测试实习生",
    "临床护理实习生", "社区护理实习生", "手术室护理实习生",
    "审计实习生", "财务实习生", "税务实习生", "税务咨询实习生",
]

EVALUATION_EXCELLENT = [
    "工作认真负责，专业能力强，团队协作好，表现优秀。",
    "学习能力突出，能独立完成任务，获得了导师的高度评价。",
    "积极主动，技术基础扎实，在项目中做出了重要贡献。",
    "沟通能力出色，能快速适应工作环境，完成了高质量的工作成果。",
]
EVALUATION_GOOD = [
    "工作态度端正，基本能完成交办的任务，有一定的进步空间。",
    "专业知识掌握较好，工作中表现稳定，团队合作意识较强。",
    "能按时完成工作，有一定的独立思考能力，需要加强实践经验。",
]
EVALUATION_AVERAGE = [
    "工作态度尚可，部分任务完成质量有待提高。",
    "基础知识需要加强，工作中偶有失误，需进一步培养。",
]

CAREER_STATUSES = ["在职", "离职待业", "自主创业", "升学读研", "出国留学", "公务员"]

COMPANIES_FOR_CAREER = INTERNSHIP_COMPANIES + [
    "字节跳动-飞书", "腾讯-微信事业群", "阿里-达摩院", "华为-2012实验室",
    "百度-AI平台", "美团-到店事业群", "京东-技术中台", "网易-有道",
    "OPPO", "vivo", "荣耀", "联想", "浪潮信息", "紫光展锐",
    "寒武纪", "地平线", "小鹏汽车", "理想汽车", "极氪汽车",
    "微众银行", "网商银行", "百信银行",
    "广州市第一人民医院", "深圳市第二人民医院",
    "安永华明会计师事务所", "致同会计师事务所",
]


def _random_phone(rng: random.Random) -> str:
    prefixes = ["130", "131", "132", "133", "134", "135", "136", "137",
                 "138", "139", "150", "151", "152", "153", "155", "156",
                 "157", "158", "159", "170", "171", "172", "173", "175",
                 "176", "177", "178", "180", "181", "182", "183", "184",
                 "185", "186", "187", "188", "189"]
    return rng.choice(prefixes) + "".join(rng.choices("0123456789", k=8))


def _random_name(gender: str, rng: random.Random) -> str:
    last = rng.choice(LAST_NAMES)
    if gender == "男":
        first = rng.choice(FIRST_NAMES_MALE)
    else:
        first = rng.choice(FIRST_NAMES_FEMALE)
    return last + first


def _random_id_card(rng: random.Random) -> str:
    province_code = str(rng.randint(11, 65)).zfill(2)
    city_code = str(rng.randint(1, 99)).zfill(2)
    district_code = str(rng.randint(1, 99)).zfill(2)
    birth_year = str(rng.randint(1999, 2005))
    birth_month = str(rng.randint(1, 12)).zfill(2)
    birth_day = str(rng.randint(1, 28)).zfill(2)
    seq = str(rng.randint(1, 999)).zfill(3)
    body = province_code + city_code + district_code + birth_year + birth_month + birth_day + seq
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = "10X98765432"
    s = sum(int(body[i]) * weights[i] for i in range(17))
    return body + check_codes[s % 11]


def _random_email(name: str, rng: random.Random) -> str:
    pinyin_approx = f"{ord(name[0]):x}{ord(name[1]):x}"
    domains = ["163.com", "qq.com", "gmail.com", "stu.edu.cn", "mail.edu.cn"]
    return f"{pinyin_approx}{rng.randint(100, 9999)}@{rng.choice(domains)}"


# ── 建表 ────────────────────────────────────────────────

def create_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # 先删除旧表（按依赖顺序）
    for table in ["student_scores", "internships", "graduate_career",
                   "courses", "teachers", "students"]:
        cur.execute(f"DROP TABLE IF EXISTS [{table}]")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id   TEXT PRIMARY KEY,        -- 学号，如 2022010001
            name         TEXT NOT NULL,
            gender       TEXT NOT NULL CHECK(gender IN ('男','女')),
            id_card      TEXT,                    -- 身份证号（脱敏）
            birth_date   TEXT,                    -- YYYY-MM-DD
            phone        TEXT,
            email        TEXT,
            province     TEXT,                    -- 生源省份
            school_name  TEXT NOT NULL,
            major        TEXT NOT NULL,
            class_name   TEXT,                    -- 班级，如 "软件2201班"
            enrollment_year INTEGER NOT NULL,     -- 入学年份
            status       TEXT NOT NULL DEFAULT '在读' CHECK(status IN ('在读','毕业','休学','退学')),
            gpa          REAL                     -- 绩点 0-4.0
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_students_major ON students(major)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_students_school ON students(school_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_students_enrollment ON students(enrollment_year)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            teacher_id   TEXT PRIMARY KEY,        -- 工号，如 T001
            name         TEXT NOT NULL,
            gender       TEXT NOT NULL CHECK(gender IN ('男','女')),
            title        TEXT NOT NULL,            -- 教授/副教授/讲师/助教
            school_name  TEXT NOT NULL,
            major        TEXT NOT NULL,            -- 所属专业
            phone        TEXT,
            email        TEXT,
            hire_date    TEXT,                     -- 入职日期 YYYY-MM-DD
            research_area TEXT,                    -- 研究方向
            is_supervisor INTEGER NOT NULL DEFAULT 0  -- 是否硕士生导师
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_teachers_major ON teachers(major)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id    TEXT PRIMARY KEY,          -- 课程编号，如 CS101
            course_name  TEXT NOT NULL,
            credit       REAL NOT NULL,             -- 学分
            course_type  TEXT NOT NULL CHECK(course_type IN ('必修','选修','实践','通识')),
            school_name  TEXT NOT NULL,
            major        TEXT,                       -- 所属专业（通识课可为空）
            teacher_id   TEXT,                       -- 授课教师
            semester     TEXT,                       -- 如 "2024-2025-1" 表示第一学期
            max_students INTEGER DEFAULT 120,
            FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_courses_semester ON courses(semester)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_courses_major ON courses(major)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_scores (
            score_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   TEXT NOT NULL,
            course_id    TEXT NOT NULL,
            semester     TEXT NOT NULL,
            usual_score  REAL,                      -- 平时成绩 0-100
            exam_score   REAL,                      -- 考试成绩 0-100
            final_score  REAL NOT NULL,             -- 最终成绩 0-100
            grade_point  REAL,                      -- 绩点 0-4.0
            is_makeup    INTEGER NOT NULL DEFAULT 0,-- 是否补考
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (course_id)  REFERENCES courses(course_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scores_student ON student_scores(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scores_course ON student_scores(course_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS internships (
            internship_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    TEXT NOT NULL,
            company_name  TEXT NOT NULL,
            position      TEXT NOT NULL,
            department    TEXT,                     -- 实习部门
            start_date    TEXT NOT NULL,            -- YYYY-MM-DD
            end_date      TEXT,                     -- NULL 表示仍在实习
            duration_weeks INTEGER,
            salary_monthly INTEGER,                -- 月薪，0 或 NULL 表示无薪
            evaluation    TEXT,                     -- 实习评价
            score         REAL,                     -- 实习评分 0-100
            mentor_name   TEXT,                     -- 企业导师
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_intern_student ON internships(student_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_intern_company ON internships(company_name)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS graduate_career (
            career_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     TEXT NOT NULL,
            graduate_year  INTEGER NOT NULL,        -- 毕业年份
            company_name   TEXT,
            position       TEXT,
            city           TEXT,
            monthly_salary INTEGER,                -- 月薪
            career_status  TEXT NOT NULL CHECK(career_status IN ('在职','离职待业','自主创业','升学读研','出国留学','公务员')),
            satisfaction   INTEGER CHECK(satisfaction BETWEEN 1 AND 5),  -- 工作满意度 1-5
            match_major    INTEGER DEFAULT 1,       -- 是否专业对口
            update_date    TEXT NOT NULL,            -- 记录更新日期
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_career_year ON graduate_career(graduate_year)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_career_status ON graduate_career(career_status)")

    conn.commit()


# ── 生成数据 ─────────────────────────────────────────────

def _gen_students(rng: random.Random, n: int = 500) -> list[tuple]:
    students = []
    for i in range(1, n + 1):
        enroll_year = rng.choice([2020, 2021, 2022, 2023, 2024, 2025])
        school = rng.choice(SCHOOL_NAMES)
        major = rng.choice(MAJORS)
        gender = rng.choice(GENDERS)
        name = _random_name(gender, rng)
        sid = f"{enroll_year}{MAJORS.index(major):02d}{i % 10000:04d}"
        birth_year = enroll_year - rng.randint(18, 22)
        birth_month = rng.randint(1, 12)
        birth_day = rng.randint(1, 28)
        birth_date = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"
        class_num = rng.randint(1, 6)
        class_name = f"{major[:2]}{enroll_year % 100:02d}{class_num:02d}班"

        # 根据入学年份推算状态
        years_since = 2026 - enroll_year
        if years_since >= 4:
            status = rng.choices(["毕业", "休学", "退学"], weights=[92, 5, 3])[0]
        elif years_since >= 1:
            status = rng.choices(["在读", "休学", "退学"], weights=[94, 4, 2])[0]
        else:
            status = "在读"

        gpa = round(rng.uniform(1.5, 4.0), 2) if status != "退学" else None

        students.append((
            sid, name, gender, _random_id_card(rng), birth_date,
            _random_phone(rng), _random_email(name, rng),
            rng.choice(PROVINCES), school, major, class_name,
            enroll_year, status, gpa,
        ))
    return students


def _gen_teachers(rng: random.Random, n: int = 60) -> list[tuple]:
    teachers = []
    for i in range(1, n + 1):
        gender = rng.choice(GENDERS)
        name = _random_name(gender, rng)
        tid = f"T{i:03d}"
        title = rng.choices(POSITIONS, weights=[15, 30, 35, 20])[0]
        school = rng.choice(SCHOOL_NAMES)
        major = rng.choice(MAJORS)
        hire_year = rng.randint(2000, 2023)
        hire_month = rng.randint(1, 12)
        hire_date = f"{hire_year}-{hire_month:02d}-{rng.randint(1, 28):02d}"
        research_areas = [
            "人工智能", "大数据分析", "云计算", "物联网", "网络安全",
            "机器学习", "深度学习", "自然语言处理", "计算机视觉",
            "软件架构", "数据库系统", "嵌入式系统", "机器人技术",
            "护理教育", "临床护理", "社区健康", "老年护理",
            "财务管理", "审计理论", "税务筹划", "公司金融",
            "控制理论", "信号处理", "通信系统", "电力电子",
        ]
        is_supervisor = 1 if title in ("教授", "副教授") and rng.random() < 0.7 else 0
        research = rng.choice(research_areas)

        teachers.append((
            tid, name, gender, title, school, major,
            _random_phone(rng), _random_email(name, rng),
            hire_date, research, is_supervisor,
        ))
    return teachers


def _gen_courses(rng: random.Random, teachers: list[tuple], n: int = 120) -> list[tuple]:
    courses = []
    used_names = set()
    for i in range(1, n + 1):
        # pick a course name, avoid too many duplicates
        name = rng.choice(COURSE_NAMES_POOL)
        if name in used_names and len(used_names) < len(COURSE_NAMES_POOL):
            while name in used_names:
                name = rng.choice(COURSE_NAMES_POOL)
        used_names.add(name)

        cid = f"C{i:03d}"
        credit = rng.choice([1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
        course_type = rng.choices(COURSE_TYPES, weights=[40, 30, 15, 15])[0]
        school = rng.choice(SCHOOL_NAMES)
        major = rng.choice(MAJORS) if course_type != "通识" else None
        teacher_id = rng.choice(teachers)[0] if teachers else None
        year = rng.randint(2022, 2025)
        sem = rng.choice([1, 2])
        semester = f"{year}-{year + 1}-{sem}"
        max_students = rng.choice([60, 80, 100, 120, 150, 200])

        courses.append((
            cid, name, credit, course_type, school, major,
            teacher_id, semester, max_students,
        ))
    return courses


def _score_to_grade_point(score: float) -> float:
    if score >= 90:
        return 4.0
    elif score >= 85:
        return 3.7
    elif score >= 82:
        return 3.3
    elif score >= 78:
        return 3.0
    elif score >= 75:
        return 2.7
    elif score >= 72:
        return 2.3
    elif score >= 68:
        return 2.0
    elif score >= 64:
        return 1.5
    elif score >= 60:
        return 1.0
    else:
        return 0.0


def _gen_student_scores(rng: random.Random, students: list[tuple], courses: list[tuple], n: int = 3000) -> list[tuple]:
    scores = []
    # 每个学生选若干门课
    student_ids = [s[0] for s in students if s[12] != "退学"]  # 排除退学
    course_pool = [(c[0], c[7]) for c in courses]  # (course_id, semester)

    for _ in range(n):
        sid = rng.choice(student_ids)
        cid, semester = rng.choice(course_pool)
        if semester is None:
            semester = "2024-2025-1"

        # 生成合理成绩
        base = rng.gauss(75, 12)
        usual = round(max(0, min(100, base + rng.uniform(-5, 10))), 1)
        exam = round(max(0, min(100, base + rng.uniform(-10, 8))), 1)
        final = round(usual * 0.3 + exam * 0.7, 1)
        gp = _score_to_grade_point(final)
        is_makeup = 1 if final < 60 and rng.random() < 0.6 else 0

        if is_makeup:
            makeup_score = round(max(60, min(75, final + rng.uniform(10, 25))), 1)
            final = makeup_score
            gp = _score_to_grade_point(final)

        scores.append((sid, cid, semester, usual, exam, final, gp, is_makeup))
    return scores


def _gen_internships(rng: random.Random, students: list[tuple], n: int = 400) -> list[tuple]:
    internships = []
    for _ in range(n):
        # 大三大四学生更容易有实习
        eligible = [s for s in students if s[12] in ("在读", "毕业") and s[10] and int(str(s[0])[:4]) <= 2023]
        if not eligible:
            eligible = [s for s in students if s[12] in ("在读", "毕业")]
        s = rng.choice(eligible)
        sid = s[0]
        company = rng.choice(INTERNSHIP_COMPANIES)
        position = rng.choice(INTERNSHIP_POSITIONS)
        dept = rng.choice(["研发部", "产品部", "运营部", "测试部", "数据部", "市场部",
                           "财务部", "人力资源部", "护理部", "审计部", "技术部"])

        start_year = rng.randint(2023, 2025)
        start_month = rng.choice([1, 3, 5, 6, 7, 9, 11])
        start_day = rng.randint(1, 28)
        start_date = f"{start_year}-{start_month:02d}-{start_day:02d}"

        duration = rng.choice([4, 6, 8, 12, 16, 24])
        end_month = start_month + duration // 4
        end_year = start_year + (end_month - 1) // 12
        end_month = ((end_month - 1) % 12) + 1
        if end_year <= 2026:
            end_date = f"{end_year}-{end_month:02d}-{start_day:02d}"
        else:
            end_date = None

        salary = rng.choices(
            [0, rng.randint(1500, 3000), rng.randint(3000, 5000), rng.randint(5000, 8000), rng.randint(8000, 15000)],
            weights=[10, 20, 35, 25, 10],
        )[0]

        ev_pool = EVALUATION_EXCELLENT + EVALUATION_GOOD + EVALUATION_AVERAGE
        ev = rng.choices(ev_pool, weights=[3, 3, 3, 3, 2, 2, 2, 1, 1])[0]
        score = round(rng.uniform(60, 100), 1)
        mentor = _random_name(rng.choice(GENDERS), rng)

        internships.append((
            sid, company, position, dept, start_date, end_date,
            duration, salary, ev, score, mentor,
        ))
    return internships


def _gen_graduate_career(rng: random.Random, students: list[tuple], n: int = 500) -> list[tuple]:
    careers = []
    graduated = [s for s in students if s[12] == "毕业"]
    if len(graduated) < n:
        # 补充在读高年级的
        more = [s for s in students if s[12] == "在读" and int(str(s[0])[:4]) <= 2023]
        graduated = graduated + more

    for i in range(n):
        s = rng.choice(graduated) if graduated else rng.choice(students)
        sid = s[0]
        enroll_year = int(str(sid)[:4])
        grad_year = enroll_year + 4
        if grad_year > 2026:
            grad_year = 2026

        status = rng.choices(
            CAREER_STATUSES, weights=[55, 8, 5, 20, 5, 7],
        )[0]

        company = None
        position = None
        city = None
        salary = None
        satisfaction = None
        match_major = None

        if status == "在职":
            company = rng.choice(COMPANIES_FOR_CAREER)
            positions_by_major = {
                "软件工程": ["后端工程师", "前端工程师", "全栈工程师", "测试工程师", "DevOps工程师"],
                "计算机科学与技术": ["研发工程师", "系统架构师", "平台开发", "安全工程师", "SRE"],
                "人工智能": ["算法工程师", "机器学习工程师", "AI研发", "数据科学家", "NLP工程师"],
                "电子信息工程": ["硬件工程师", "嵌入式工程师", "射频工程师", "芯片验证工程师"],
                "自动化": ["自动化工程师", "PLC工程师", "机器人工程师", "控制工程师"],
                "数据科学与大数据技术": ["数据分析师", "数据工程师", "BI工程师", "数据产品经理"],
                "护理学": ["临床护士", "手术室护士", "ICU护士", "社区护士", "健康管理师"],
                "会计学": ["会计师", "审计师", "税务师", "财务分析师", "成本会计"],
            }
            major = s[9] if len(s) > 9 else "软件工程"
            pos_pool = positions_by_major.get(major, ["工程师", "专员", "分析师"])
            position = rng.choice(pos_pool)
            city = rng.choice(CITIES)
            salary = rng.randint(5000, 35000)
            satisfaction = rng.randint(1, 5)
            match_major = 1 if rng.random() < 0.75 else 0

        elif status == "公务员":
            position = rng.choice(["科员", "副主任科员", "办事员"])
            city = rng.choice(CITIES)
            salary = rng.randint(6000, 15000)
            satisfaction = rng.randint(2, 5)
            match_major = 0

        elif status == "自主创业":
            company = rng.choice(["XX科技工作室", "XX电子商务", "XX咨询", "XX教育科技", "XX设计工作室"])
            position = "创始人/CEO"
            city = rng.choice(CITIES)
            salary = rng.randint(0, 50000)
            satisfaction = rng.randint(3, 5)
            match_major = rng.choice([0, 1])

        elif status in ("升学读研", "出国留学"):
            satisfaction = rng.randint(3, 5)
            match_major = 1

        else:  # 离职待业
            satisfaction = rng.randint(1, 3)
            match_major = 0

        update_month = rng.randint(1, 12)
        update_day = rng.randint(1, 28)
        update_date = f"2026-{update_month:02d}-{update_day:02d}"

        careers.append((
            sid, grad_year, company, position, city, salary,
            status, satisfaction, match_major, update_date,
        ))
    return careers


# ── 插入数据 ─────────────────────────────────────────────

def insert_data(conn: sqlite3.Connection) -> None:
    rng = random.Random(SEED)
    cur = conn.cursor()

    # 表已在 create_tables 中 DROP 重建，无需额外清理

    # 1. students
    students = _gen_students(rng, 500)
    cur.executemany(
        "INSERT INTO students VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", students
    )
    print(f"  students: {len(students)} 条")

    # 2. teachers
    teachers = _gen_teachers(rng, 60)
    cur.executemany(
        "INSERT INTO teachers VALUES (?,?,?,?,?,?,?,?,?,?,?)", teachers
    )
    print(f"  teachers: {len(teachers)} 条")

    # 3. courses
    courses = _gen_courses(rng, teachers, 120)
    cur.executemany(
        "INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", courses
    )
    print(f"  courses: {len(courses)} 条")

    # 4. student_scores
    scores = _gen_student_scores(rng, students, courses, 3000)
    cur.executemany(
        "INSERT INTO student_scores (student_id, course_id, semester, usual_score, exam_score, final_score, grade_point, is_makeup) VALUES (?,?,?,?,?,?,?,?)",
        scores,
    )
    print(f"  student_scores: {len(scores)} 条")

    # 5. internships
    internships = _gen_internships(rng, students, 400)
    cur.executemany(
        "INSERT INTO internships (student_id, company_name, position, department, start_date, end_date, duration_weeks, salary_monthly, evaluation, score, mentor_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        internships,
    )
    print(f"  internships: {len(internships)} 条")

    # 6. graduate_career
    careers = _gen_graduate_career(rng, students, 500)
    cur.executemany(
        "INSERT INTO graduate_career (student_id, graduate_year, company_name, position, city, monthly_salary, career_status, satisfaction, match_major, update_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
        careers,
    )
    print(f"  graduate_career: {len(careers)} 条")

    conn.commit()


# ── 主函数 ──────────────────────────────────────────────

def main() -> None:
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        print("=" * 50)
        print("创建新表...")
        create_tables(conn)
        print("生成并插入数据...")
        insert_data(conn)

        # 打印统计
        cur = conn.cursor()
        print("\n" + "=" * 50)
        print("school_demo.db 当前所有表:")
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for (name,) in cur.fetchall():
            cur.execute(f"SELECT COUNT(*) FROM [{name}]")
            count = cur.fetchone()[0]
            print(f"  {name:30s} -> {count:>6d} 行")
        print("=" * 50)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
