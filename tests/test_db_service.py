"""
数据库服务测试（B端版） — 业务表 CRUD 操作测试

测试新的 db_service.py 中的核心业务函数：
  1. 用户管理：register_user / verify_user / list_all_users / update_password
  2. 客户管理：create_client / get_client / list_clients
  3. 需求管理：create_requirement / get_requirement / list_requirements
  4. 方案管理：create_itinerary / get_itinerary / list_itineraries
  5. 方案修改：update_itinerary / update_itinerary_status / delete_itinerary
  6. 版本管理：get_version_history / get_version

使用临时文件 SQLite 数据库，每个测试类独立建表清理。
注意：db_service.py 中每个函数独立创建 sqlite3.connect(DB_PATH) 连接，
      因此 :memory: 模式不可用（每函数创建新连接 → 新数据库）。
      改用临时文件 + 启动时创建表。
"""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """使用临时文件数据库，测试前后自动建表和清理"""
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-key-for-pytest")

    # 创建临时数据库文件
    tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db_path = tmpfile.name
    tmpfile.close()

    # 导入并初始化数据库服务
    import src.db_service
    # 注意：db_service.py 模块级别 `from src.config import DB_PATH`，
    # 因此需在导入后 patch `src.db_service.DB_PATH`
    monkeypatch.setattr(src.db_service, "DB_PATH", tmp_db_path)

    src.db_service.init_db()
    src.db_service.init_admin()

    yield

    # 测试后清理临时文件
    try:
        os.unlink(tmp_db_path)
    except OSError:
        pass


@pytest.fixture
def sample_client():
    """注册一个测试客户并返回 client_id"""
    from src import db_service
    return db_service.create_client(name="测试客户", phone="00000000000", email="test@example.com")


@pytest.fixture
def sample_requirement(sample_client):
    """创建一个测试需求并返回 requirement_id"""
    from src import db_service
    return db_service.create_requirement(
        client_id=sample_client,
        consultant_id=1,
        destination="桂林",
        travel_days=3,
        traveler_count=4,
        total_budget=6000,
        travel_type="亲子",
        preferences="自然风光",
        special_requirements="老人/儿童适配",
    )


@pytest.fixture
def sample_itinerary_content():
    """符合规范的行程方案 JSON 内容"""
    import json
    content = {
        "title": "桂林3日亲子游方案",
        "overview": "专为亲子家庭设计的桂林3日游路线",
        "daily_plan": [
            {
                "day": 1,
                "date_desc": "第1天",
                "morning": {"activity": "抵达桂林", "location": "桂林", "cost_est": 0, "note": ""},
                "afternoon": {"activity": "游览象鼻山", "location": "象鼻山", "cost_est": 200, "note": ""},
                "evening": {"activity": "逛东西巷", "location": "东西巷", "cost_est": 100, "note": ""},
                "accommodation": "桂林酒店",
                "meals": "含早午餐",
                "transport": "专车",
            }
        ],
        "total_cost_est": 5100,
        "cost_breakdown": "交通: 1200, 住宿: 1800, 餐饮: 900, 门票: 800, 其他: 400",
        "notes": "注意防晒",
        "client_talk": "推荐话术",
        "alternative_routes": "可增加龙脊梯田",
    }
    return json.dumps(content, ensure_ascii=False)


@pytest.fixture
def sample_itinerary(sample_requirement, sample_itinerary_content):
    """创建一个测试方案并返回 itinerary_id
    注意：create_itinerary() 的签名是 (requirement_id, consultant_id, content_json, title, summary)
    destination/travel_days 等字段存储在 travel_requirements 中，通过 JOIN 从 get_itinerary() 返回。
    """
    from src import db_service
    return db_service.create_itinerary(
        requirement_id=sample_requirement,
        consultant_id=1,
        content_json=sample_itinerary_content,
        title="桂林3日亲子游方案",
    )


# =====================================================================
# 测试：用户管理
# =====================================================================

class TestUserManagement:
    """用户注册/登录/列表测试"""

    def test_register_success(self):
        """注册新用户 → 应返回 True"""
        from src import db_service
        result = db_service.register_user("testuser", "password123", "test@example.com")
        assert result is True

    def test_register_duplicate(self):
        """重复注册用户名 → 应返回 False"""
        from src import db_service
        db_service.register_user("dupeuser", "pass1")
        result = db_service.register_user("dupeuser", "pass2")
        assert result is False

    def test_verify_user_success(self):
        """正确密码 → 应返回用户信息"""
        from src import db_service
        db_service.register_user("verifyuser", "mypassword")
        user = db_service.verify_user("verifyuser", "mypassword")
        assert user is not None
        assert user["username"] == "verifyuser"

    def test_verify_user_wrong_password(self):
        """错误密码 → 应返回 None"""
        from src import db_service
        db_service.register_user("secureuser", "correctpass")
        user = db_service.verify_user("secureuser", "wrongpass")
        assert user is None

    def test_verify_user_nonexistent(self):
        """不存在的用户 → 应返回 None"""
        from src import db_service
        user = db_service.verify_user("nobody", "anypass")
        assert user is None

    def test_user_exists(self):
        """已存在的用户 → 返回 True"""
        from src import db_service
        db_service.register_user("existuser", "pass")
        assert db_service.user_exists("existuser") is True
        assert db_service.user_exists("notexist") is False

    def test_list_all_users(self):
        """列出所有用户 → 应包含刚注册的用户"""
        from src import db_service
        db_service.register_user("user_a", "pass1")
        db_service.register_user("user_b", "pass2")
        users = db_service.list_all_users()
        usernames = [u["username"] for u in users]
        assert "user_a" in usernames
        assert "user_b" in usernames

    def test_update_password(self):
        """修改密码后可用新密码登录"""
        from src import db_service
        db_service.register_user("passuser", "oldpass")
        result = db_service.update_password("passuser", "newpass")
        assert result is True
        # 旧密码无法登录
        assert db_service.verify_user("passuser", "oldpass") is None
        # 新密码可以登录
        assert db_service.verify_user("passuser", "newpass") is not None

    def test_update_password_nonexistent(self):
        """修改不存在的用户密码 → 返回 False"""
        from src import db_service
        result = db_service.update_password("ghost", "anypass")
        assert result is False


# =====================================================================
# 测试：客户管理
# =====================================================================

class TestClientManagement:
    """客户 CRUD 操作测试"""

    def test_create_client(self):
        """创建客户 → 返回正数 client_id"""
        from src import db_service
        cid = db_service.create_client("新客户", "00000000001")
        assert isinstance(cid, int)
        assert cid > 0

    def test_get_client(self, sample_client):
        """获取客户 → 应包含 name/phone/email"""
        from src import db_service
        client = db_service.get_client(sample_client)
        assert client is not None
        assert client["name"] == "测试客户"
        assert client["phone"] == "00000000000"
        assert client["email"] == "test@example.com"

    def test_get_client_nonexistent(self):
        """不存在的客户 → 返回 None"""
        from src import db_service
        assert db_service.get_client(999) is None

    def test_list_clients(self):
        """列出客户 → 按创建时间降序"""
        from src import db_service
        cid1 = db_service.create_client("客户A")
        cid2 = db_service.create_client("客户B")
        clients = db_service.list_clients()
        assert len(clients) >= 2
        # 按名称搜索
        result = db_service.list_clients(search="客户A")
        assert len(result) == 1
        assert result[0]["name"] == "客户A"


# =====================================================================
# 测试：需求管理
# =====================================================================

class TestRequirementManagement:
    """行程需求 CRUD 操作测试"""

    def test_create_requirement(self, sample_client):
        """创建需求 → 返回正数 requirement_id"""
        from src import db_service
        rid = db_service.create_requirement(
            client_id=sample_client,
            consultant_id=1,
            destination="三亚",
            travel_days=4,
            traveler_count=2,
            total_budget=8000,
        )
        assert isinstance(rid, int)
        assert rid > 0

    def test_get_requirement(self, sample_requirement):
        """获取需求 → 应包含联表查询的客户名称"""
        from src import db_service
        req = db_service.get_requirement(sample_requirement)
        assert req is not None
        assert req["destination"] == "桂林"
        assert req["client_name"] == "测试客户"
        assert req["travel_days"] == 3
        assert req["traveler_count"] == 4

    def test_get_requirement_nonexistent(self):
        """不存在的需求 → 返回 None"""
        from src import db_service
        assert db_service.get_requirement(999) is None

    def test_list_requirements(self, sample_requirement):
        """列出需求 → 包含联表字段"""
        from src import db_service
        reqs = db_service.list_requirements()
        assert len(reqs) >= 1
        assert reqs[0]["client_name"] == "测试客户"

    def test_list_requirements_by_consultant(self, sample_requirement):
        """按顾问筛选需求"""
        from src import db_service
        reqs = db_service.list_requirements(consultant_id=1)
        assert len(reqs) >= 1
        # 另一个顾问应无数据
        reqs2 = db_service.list_requirements(consultant_id=999)
        assert len(reqs2) == 0


# =====================================================================
# 测试：方案管理
# =====================================================================

class TestItineraryManagement:
    """行程方案 CRUD 操作测试"""

    def test_create_itinerary(self, sample_requirement, sample_itinerary_content):
        """创建方案 → 返回正数 itinerary_id
        create_itinerary() 的签名: (requirement_id, consultant_id, content_json, title, summary)
        """
        from src import db_service
        iid = db_service.create_itinerary(
            requirement_id=sample_requirement,
            consultant_id=1,
            content_json=sample_itinerary_content,
            title="桂林3日亲子游方案",
        )
        assert isinstance(iid, int)
        assert iid > 0

    def test_get_itinerary(self, sample_itinerary):
        """获取方案 → 应联表查询客户名称和目的地"""
        from src import db_service
        it = db_service.get_itinerary(sample_itinerary)
        assert it is not None
        assert it["client_name"] == "测试客户"
        assert it["destination"] == "桂林"
        assert it["travel_days"] == 3
        assert it["version"] == 1
        assert it["status"] == "draft"

    def test_get_itinerary_nonexistent(self):
        """不存在的方案 → 返回 None"""
        from src import db_service
        assert db_service.get_itinerary(999) is None

    def test_list_itineraries(self, sample_itinerary):
        """列出方案 → 按创建时间降序"""
        from src import db_service
        items = db_service.list_itineraries()
        assert len(items) >= 1
        assert items[0]["client_name"] == "测试客户"

    def test_list_itineraries_by_consultant(self, sample_itinerary):
        """按顾问筛选方案"""
        from src import db_service
        items = db_service.list_itineraries(consultant_id=1)
        assert len(items) >= 1

    def test_list_itineraries_by_status(self, sample_itinerary):
        """按状态筛选方案"""
        from src import db_service
        items = db_service.list_itineraries(status="draft")
        assert len(items) >= 1
        items2 = db_service.list_itineraries(status="sent")
        assert len(items2) == 0


# =====================================================================
# 测试：方案修改与版本管理
# =====================================================================

class TestItineraryVersion:
    """方案更新与版本管理测试"""

    def test_update_itinerary(self, sample_itinerary, sample_itinerary_content):
        """更新方案 → 版本号递增并创建版本历史
        update_itinerary() 的签名: (itinerary_id, content_json, title, summary, change_log, consultant_id)
        """
        import json
        from src import db_service

        new_content = json.loads(sample_itinerary_content)
        new_content["title"] = "桂林3日亲子游方案v2"
        new_content_json = json.dumps(new_content, ensure_ascii=False)

        result = db_service.update_itinerary(
            itinerary_id=sample_itinerary,
            content_json=new_content_json,
            title="桂林3日亲子游方案v2",
            consultant_id=1,
        )
        assert result is True

        # 验证版本号递增
        it = db_service.get_itinerary(sample_itinerary)
        assert it["version"] == 2

        # 验证版本历史（create_itinerary 创建了 v1，update 创建了 v2）
        versions = db_service.get_version_history(sample_itinerary)
        assert len(versions) == 2  # v1 (初始) + v2 (更新)
        assert versions[1]["version"] == 1  # 旧版本

    def test_update_itinerary_nonexistent(self, sample_itinerary_content):
        """更新不存在的方案 → 返回 False"""
        from src import db_service
        result = db_service.update_itinerary(999, sample_itinerary_content, "title", consultant_id=1)
        assert result is False

    def test_update_status(self, sample_itinerary):
        """更新方案状态"""
        from src import db_service
        result = db_service.update_itinerary_status(sample_itinerary, "sent")
        assert result is True

        it = db_service.get_itinerary(sample_itinerary)
        assert it["status"] == "sent"

    def test_update_status_invalid(self, sample_itinerary):
        """更新为非法状态 → 实现中不做校验，只要能更新即返回 True"""
        from src import db_service
        # update_itinerary_status() 不校验状态值合法性，仅执行 UPDATE
        result = db_service.update_itinerary_status(sample_itinerary, "invalid_status")
        assert result is True  # 只要行存在，UPDATE 就成功

    def test_delete_itinerary(self, sample_itinerary):
        """删除方案 → 同时删除关联的版本历史"""
        from src import db_service

        # 先创建一个版本历史
        import json
        content = json.loads(db_service.get_itinerary(sample_itinerary)["content_json"])
        content["title"] = "测试v2"
        db_service.update_itinerary(sample_itinerary, json.dumps(content, ensure_ascii=False), 1)

        # 删除方案
        result = db_service.delete_itinerary(sample_itinerary)
        assert result is True

        # 验证方案已删除
        assert db_service.get_itinerary(sample_itinerary) is None
        # 验证版本历史已删除
        assert db_service.get_version_history(sample_itinerary) == []

    def test_get_version_history(self, sample_itinerary, sample_itinerary_content):
        """多次更新 → 返回完整的版本历史
        create_itinerary 自动创建 v1，两次 update 创建 v2、v3，共 3 条
        """
        import json
        from src import db_service

        # 更新两次
        content = json.loads(sample_itinerary_content)
        for i in range(2, 4):
            content["title"] = f"桂林3日亲子游方案v{i}"
            db_service.update_itinerary(
                sample_itinerary,
                json.dumps(content, ensure_ascii=False),
                title=f"桂林3日亲子游方案v{i}",
                consultant_id=1,
            )

        versions = db_service.get_version_history(sample_itinerary)
        # create_itinerary 创建 v1（初始版本），两次 update 创建 v2、v3
        assert len(versions) == 3
        # 按版本号降序排列：v3, v2, v1
        assert versions[0]["version"] == 3
        assert versions[1]["version"] == 2
        assert versions[2]["version"] == 1

    def test_get_specific_version(self, sample_itinerary, sample_itinerary_content):
        """获取指定版本的方案内容"""
        import json
        from src import db_service

        # 更新一次
        content = json.loads(sample_itinerary_content)
        content["title"] = "v2版本"
        new_json = json.dumps(content, ensure_ascii=False)
        db_service.update_itinerary(
            sample_itinerary,
            new_json,
            title="v2版本",
            consultant_id=1,
        )

        # 获取 v1（原始版本）
        v1 = db_service.get_version(sample_itinerary, 1)
        assert v1 is not None
        assert "桂林3日亲子游方案" in v1["content_json"]

        # 获取 v2
        v2 = db_service.get_version(sample_itinerary, 2)
        assert v2 is not None
        assert "v2版本" in v2["content_json"]


# =====================================================================
# 测试：操作审计
# =====================================================================

class TestAuditLog:
    """操作日志写入与查询"""

    def test_log_failed_login_without_user(self):
        """登录失败时 user_id 为空，仍应能落库"""
        from src import db_service

        db_service.log_action(None, "login_failed", username="ghost", detail="密码错误")
        logs = db_service.list_audit_logs(limit=10)
        assert logs
        assert logs[0]["action"] == "login_failed"
        assert logs[0]["username"] == "ghost"

    def test_log_user_action_and_filter(self):
        """登录用户的生成动作可按 user_id 筛选"""
        from src import db_service

        db_service.register_user("audit_user", "pass1234")
        user = db_service.verify_user("audit_user", "pass1234")
        assert user is not None

        db_service.log_action(
            user["user_id"], "generate", "itinerary", 1,
            detail="桂林/3天/亲子", username="audit_user",
        )
        logs = db_service.list_audit_logs(limit=10, user_id=user["user_id"])
        assert len(logs) == 1
        assert logs[0]["target_type"] == "itinerary"
        assert "桂林" in logs[0]["detail"]

    def test_filter_by_action(self):
        """按动作筛选只返回对应记录"""
        from src import db_service

        db_service.log_action(None, "login", username="a")
        db_service.log_action(None, "export", detail="html")
        logs = db_service.list_audit_logs(limit=10, action="export")
        assert len(logs) == 1
        assert logs[0]["action"] == "export"
